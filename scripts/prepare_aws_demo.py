"""Inspect the Free Plan by default; prepare Express/secret resources only with --apply.

Uses the named AWS login profile through boto3 with CRT support. Secret payloads
stay in process memory, never command arguments, Terraform, logs, or repository files.
"""

import argparse
import json
import re
import secrets
import sys
import time
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import boto3
import psycopg
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError
from dotenv import dotenv_values
from psycopg import sql

REGION = "eu-north-1"
NAME = "reconflow"
DB_USER = "reconflow_app"
TAGS = {"Project": NAME, "Environment": "portfolio-demo", "ManagedBy": "reconflow-free-demo"}
SCALING = {"MinCapacity": 0, "MaxCapacity": 1, "SecondsUntilAutoPause": 300}


class AwsError(RuntimeError):
    def __init__(self, service, operation, code):
        self.code = code
        super().__init__(f"AWS {service}/{operation}: {code}. No automatic mutation retry.")


class Aws:
    def __init__(self, profile, region):
        if region != REGION:
            raise ValueError(f"Only the selected project Region {REGION} is permitted.")
        self.session = boto3.Session(profile_name=profile, region_name=region)
        self.config = Config(
            retries={"total_max_attempts": 1, "mode": "standard"},
            connect_timeout=10,
            read_timeout=60,
            ignore_configured_endpoint_urls=True,
        )
        self.clients = {}

    def run(self, service, operation, parameters=None):
        if service not in self.clients:
            self.clients[service] = self.session.client(service, config=self.config)
        method = getattr(self.clients[service], operation.replace("-", "_"))
        try:
            return method(**(parameters or {}))
        except ClientError as exc:
            # Service messages can echo secret payloads. Expose only the error code.
            raise AwsError(service, operation, exc.response["Error"]["Code"]) from None


def check_free_plan(plan, now=None):
    now = now or datetime.now(UTC)
    if plan.get("accountPlanType") != "FREE" or plan.get("accountPlanStatus") != "ACTIVE":
        raise ValueError("An ACTIVE FREE plan is required; no Paid/Advanced upgrade is performed.")
    credits = plan.get("accountPlanRemainingCredits", {})
    if credits.get("unit") != "USD" or Decimal(str(credits.get("amount", 0))) <= 0:
        raise ValueError("No positive USD Free Plan credit balance confirmed.")
    expiry = plan["accountPlanExpirationDate"]
    if isinstance(expiry, str):
        expiry = datetime.fromisoformat(expiry.replace("Z", "+00:00"))
    if expiry <= now:
        raise ValueError("The Free Plan has expired.")


def owned(tags):
    values = {tag["Key"]: tag["Value"] for tag in tags}
    if any(values.get(key) != value for key, value in TAGS.items()):
        raise ValueError(
            "Refusing an existing resource without ReconFlow preparation ownership tags."
        )


def get_cluster(aws):
    try:
        return aws.run("rds", "describe-db-clusters", {"DBClusterIdentifier": NAME})["DBClusters"][
            0
        ]
    except AwsError as exc:
        if exc.code == "DBClusterNotFoundFault":
            return None
        raise


def check_cluster(cluster, account):
    owned(cluster.get("TagList", []))
    if (
        cluster.get("DBClusterArn") != f"arn:aws:rds:{REGION}:{account}:cluster:{NAME}"
        or cluster.get("Engine") != "aurora-postgresql"
        or cluster.get("VPCNetworkingEnabled") is not False
        or cluster.get("InternetAccessGatewayEnabled") is not True
        or cluster.get("IAMDatabaseAuthenticationEnabled") is not True
        or len(cluster.get("DBClusterMembers", [])) > 1
    ):
        raise ValueError(
            "Existing cluster is not the expected single-writer ReconFlow Express database."
        )


def preflight(aws, expected_account=None):
    identity = aws.run("sts", "get-caller-identity")
    account = identity["Account"]
    if expected_account and account != expected_account:
        raise ValueError("Authenticated AWS project does not match --expected-account-id.")
    plan = {
        key: value
        for key, value in aws.run("freetier", "get-account-plan-state").items()
        if key != "ResponseMetadata"
    }
    check_free_plan(plan)
    limits = aws.run("lambda", "get-account-settings")["AccountLimit"]
    if limits["UnreservedConcurrentExecutions"] < 3:
        raise ValueError("At least three unreserved Lambda slots are needed for the test stack.")
    cluster = get_cluster(aws)
    parameters = {"Engine": "aurora-postgresql"}
    if cluster:
        check_cluster(cluster, account)
        parameters["EngineVersion"] = cluster["EngineVersion"]
    else:
        parameters["DefaultOnly"] = True
    versions = aws.run("rds", "describe-db-engine-versions", parameters)["DBEngineVersions"]
    if not versions or versions[0].get("ServerlessV2FeaturesSupport", {}).get("MinCapacity") != 0:
        raise ValueError(
            "Aurora's selected engine version has not been confirmed to support zero ACUs."
        )
    return {
        "account": account,
        "region": REGION,
        "plan": plan,
        "unreserved_lambda_concurrency": limits["UnreservedConcurrentExecutions"],
        "engine_version": versions[0]["EngineVersion"],
        "cluster_exists": cluster is not None,
    }


def wait_for_cluster(aws, account, *, timeout=900, require_settings=False):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        cluster = get_cluster(aws)
        if cluster and cluster.get("Status") == "available":
            check_cluster(cluster, account)
            members = cluster.get("DBClusterMembers", [])
            if len(members) == 1 and members[0].get("IsClusterWriter"):
                writer = aws.run(
                    "rds",
                    "describe-db-instances",
                    {
                        "DBInstanceIdentifier": members[0]["DBInstanceIdentifier"],
                    },
                )["DBInstances"][0]
                if writer["DBInstanceClass"] != "db.serverless":
                    raise ValueError("Express writer is not serverless.")
                settings_ready = (
                    cluster.get("ServerlessV2ScalingConfiguration") == SCALING
                    and cluster.get("DeletionProtection") is True
                )
                if writer["DBInstanceStatus"] == "available" and (
                    not require_settings or settings_ready
                ):
                    return cluster
        print("Waiting for the Express writer (read-only status check)…", flush=True)
        time.sleep(10)
    raise TimeoutError("Express database is not ready. Inspect it before rerunning preparation.")


def ensure_secret(aws, suffix, value_factory):
    name = f"{NAME}/{suffix}"
    try:
        metadata = aws.run("secretsmanager", "describe-secret", {"SecretId": name})
    except AwsError as exc:
        if exc.code != "ResourceNotFoundException":
            raise
        value = value_factory()
        metadata = aws.run(
            "secretsmanager",
            "create-secret",
            {
                "Name": name,
                "SecretString": value,
                "Tags": [{"Key": k, "Value": v} for k, v in TAGS.items()],
            },
        )
        return metadata["ARN"], value
    owned(metadata.get("Tags", []))
    if metadata.get("DeletedDate"):
        raise ValueError(f"Secret {name} is scheduled for deletion; review it before continuing.")
    # Reuse the persisted value after partial setup; never silently rotate it.
    value = aws.run("secretsmanager", "get-secret-value", {"SecretId": metadata["ARN"]})[
        "SecretString"
    ]
    return metadata["ARN"], value


def configure_sql_user(aws, cluster, credentials):
    if (
        credentials.get("username") != DB_USER
        or not isinstance(credentials.get("password"), str)
        or len(credentials["password"]) < 32
    ):
        raise ValueError(
            "Database secret must contain the expected SQL username and a strong password."
        )
    token = aws.run(
        "rds",
        "generate-db-auth-token",
        {
            "DBHostname": cluster["Endpoint"],
            "Port": cluster["Port"],
            "DBUsername": cluster["MasterUsername"],
            "Region": REGION,
        },
    )
    # Express cannot create an initial database through CreateDBCluster. CREATE
    # DATABASE must run outside a transaction; the session lock serializes setup.
    # Express uses public AWS trust roots. Verify both certificate and hostname.
    connection_options = {
        "host": cluster["Endpoint"],
        "port": cluster["Port"],
        "user": cluster["MasterUsername"],
        "password": token,
        "sslmode": "verify-full",
        "sslrootcert": "system",
        "connect_timeout": 30,
    }
    with psycopg.connect(**connection_options, dbname="postgres", autocommit=True) as admin:
        admin.execute("SELECT pg_advisory_lock(71823761)")
        if not admin.execute("SELECT 1 FROM pg_database WHERE datname=%s", (NAME,)).fetchone():
            admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(NAME)))
    with psycopg.connect(**connection_options, dbname=NAME) as connection:
        connection.execute("SELECT pg_advisory_xact_lock(71823761)")
        exists = connection.execute(
            "SELECT 1 FROM pg_roles WHERE rolname=%s", (DB_USER,)
        ).fetchone()
        if not exists:
            connection.execute(
                sql.SQL("CREATE ROLE {} LOGIN PASSWORD {}").format(
                    sql.Identifier(DB_USER),
                    sql.Literal(credentials["password"]),
                )
            )
        # Do not reset an existing role's password or grant administrator privileges.
        connection.execute(
            sql.SQL("GRANT CONNECT, CREATE ON DATABASE {} TO {}").format(
                sql.Identifier(NAME),
                sql.Identifier(DB_USER),
            )
        )
        connection.execute(
            sql.SQL("GRANT USAGE, CREATE ON SCHEMA public TO {}").format(sql.Identifier(DB_USER))
        )


def apply(aws, report, env_file):
    # Fail before creating resources if the requested OpenAI configuration is missing.
    key = dotenv_values(env_file).get("OPENAI_API_KEY")
    if not key:
        raise ValueError(
            "The private env file must contain OPENAI_API_KEY; no key is printed or copied into state."
        )
    cluster = get_cluster(aws)
    if cluster is None:
        aws.run(
            "rds",
            "create-db-cluster",
            {
                "DBClusterIdentifier": NAME,
                "Engine": "aurora-postgresql",
                "WithExpressConfiguration": True,
                "MasterUsername": "reconflow_admin",
                "DeletionProtection": True,
                "ServerlessV2ScalingConfiguration": SCALING,
                "Tags": [{"Key": k, "Value": v} for k, v in TAGS.items()],
            },
        )
    else:
        check_cluster(cluster, report["account"])
    cluster = wait_for_cluster(aws, report["account"])
    if cluster.get("ServerlessV2ScalingConfiguration") != SCALING or not cluster.get(
        "DeletionProtection"
    ):
        aws.run(
            "rds",
            "modify-db-cluster",
            {
                "DBClusterIdentifier": NAME,
                "ServerlessV2ScalingConfiguration": SCALING,
                "DeletionProtection": True,
                "ApplyImmediately": True,
            },
        )
        cluster = wait_for_cluster(aws, report["account"], require_settings=True)
    if not cluster.get("HttpEndpointEnabled"):
        aws.run("rds", "enable-http-endpoint", {"ResourceArn": cluster["DBClusterArn"]})
    db_arn, db_value = ensure_secret(
        aws,
        "db",
        lambda: json.dumps(
            {
                "username": DB_USER,
                "password": secrets.token_urlsafe(48),
            }
        ),
    )
    configure_sql_user(aws, cluster, json.loads(db_value))
    # A failing authentication check is surfaced, never repaired by password rotation.
    aws.run(
        "rds-data",
        "execute-statement",
        {
            "resourceArn": cluster["DBClusterArn"],
            "secretArn": db_arn,
            "database": NAME,
            "sql": "SELECT 1",
        },
    )
    session_arn, session_value = ensure_secret(aws, "session", lambda: secrets.token_urlsafe(48))
    if len(session_value) < 32:
        raise ValueError("Existing session secret is too short.")
    openai_arn, openai_value = ensure_secret(aws, "openai", lambda: key)
    if not openai_value or openai_value.lstrip().startswith("{"):
        raise ValueError("OpenAI secret must be a plaintext API key, not console JSON.")
    return {
        "database_secret_arn": db_arn,
        "session_secret_arn": session_arn,
        "openai_secret_arn": openai_arn,
        "database_cluster_arn": cluster["DBClusterArn"],
        "engine_version": cluster["EngineVersion"],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", default="portfolio")
    parser.add_argument("--region", choices=[REGION], default=REGION)
    parser.add_argument(
        "--apply", action="store_true", help="Create resources only after deployment approval."
    )
    parser.add_argument(
        "--expected-account-id", help="Required for --apply; obtain from the read-only preflight."
    )
    parser.add_argument(
        "--env-file", type=Path, default=Path(__file__).resolve().parents[1] / ".env"
    )
    args = parser.parse_args()
    if args.apply and not re.fullmatch(r"[0-9]{12}", args.expected_account_id or ""):
        parser.error("--apply requires --expected-account-id with the reviewed 12-digit project ID")
    try:
        aws = Aws(args.profile, args.region)
        report = preflight(aws, args.expected_account_id)
        print(json.dumps(report, indent=2, default=str), flush=True)
        if args.apply:
            print(json.dumps(apply(aws, report, args.env_file), indent=2))
        else:
            print(
                "Read-only preflight complete. Planned: Express 0–1 ACU, Data API, SQL user, three secrets. Nothing created."
            )
    except (
        AwsError,
        ValueError,
        KeyError,
        OSError,
        TimeoutError,
        BotoCoreError,
        psycopg.Error,
    ) as exc:
        # psycopg/server and SDK errors may contain credentials or SQL.
        message = (
            str(exc)
            if isinstance(exc, (AwsError, ValueError)) and not isinstance(exc, json.JSONDecodeError)
            else type(exc).__name__
        )
        print(f"Preparation stopped: {message}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
