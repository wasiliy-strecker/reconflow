"""Operator preparation must never spend credits during preflight or leak secrets."""

import importlib.util
import json
import uuid
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from botocore.exceptions import ClientError
from reconflow.config import settings

spec = importlib.util.spec_from_file_location(
    "prepare_aws_demo", Path(__file__).resolve().parents[1] / "scripts/prepare_aws_demo.py"
)
prepare = importlib.util.module_from_spec(spec)
spec.loader.exec_module(prepare)

ACCOUNT = "123456789012"
FREE = {
    "accountPlanType": "FREE",
    "accountPlanStatus": "ACTIVE",
    "accountPlanRemainingCredits": {"amount": "100.0", "unit": "USD"},
    "accountPlanExpirationDate": "2030-01-01T00:00:00+00:00",
}


class FakeAws:
    def __init__(self):
        self.calls = []
        self.cluster = None
        self.secrets = {}
        self.plan = deepcopy(FREE)
        self.concurrency = 10

    def run(self, service, operation, parameters=None, **kwargs):
        self.calls.append((service, operation, parameters))
        if operation == "get-caller-identity":
            return {"Account": ACCOUNT}
        if operation == "get-account-plan-state":
            return self.plan
        if operation == "get-account-settings":
            return {"AccountLimit": {"UnreservedConcurrentExecutions": self.concurrency}}
        if operation == "describe-db-clusters":
            if self.cluster is None:
                raise prepare.AwsError(service, operation, "DBClusterNotFoundFault")
            return {"DBClusters": [deepcopy(self.cluster)]}
        if operation == "describe-db-engine-versions":
            return {
                "DBEngineVersions": [
                    {"EngineVersion": "17.9", "ServerlessV2FeaturesSupport": {"MinCapacity": 0}}
                ]
            }
        if operation == "create-db-cluster":
            assert self.cluster is None
            assert parameters["WithExpressConfiguration"] is True
            assert "EngineVersion" not in parameters
            assert "DatabaseName" not in parameters
            self.cluster = {
                **parameters,
                "EngineVersion": "17.9",
                "Status": "available",
                "DBClusterArn": f"arn:aws:rds:eu-north-1:{ACCOUNT}:cluster:reconflow",
                "TagList": parameters["Tags"],
                "VPCNetworkingEnabled": False,
                "InternetAccessGatewayEnabled": True,
                "IAMDatabaseAuthenticationEnabled": True,
                "Endpoint": "example.eu-north-1.rds.amazonaws.com",
                "Port": 5432,
                "DBClusterMembers": [{"DBInstanceIdentifier": "writer", "IsClusterWriter": True}],
            }
            return {"DBCluster": self.cluster}
        if operation == "describe-db-instances":
            return {
                "DBInstances": [
                    {"DBInstanceClass": "db.serverless", "DBInstanceStatus": "available"}
                ]
            }
        if operation == "enable-http-endpoint":
            self.cluster["HttpEndpointEnabled"] = True
            return {}
        if operation == "modify-db-cluster":
            self.cluster.update(parameters)
            return {}
        if operation == "describe-secret":
            name = parameters["SecretId"]
            if name not in self.secrets:
                raise prepare.AwsError(service, operation, "ResourceNotFoundException")
            return self.secrets[name]
        if operation == "create-secret":
            name = parameters["Name"]
            self.secrets[name] = {
                **parameters,
                "ARN": f"arn:aws:secretsmanager:eu-north-1:{ACCOUNT}:secret:{name}-abcdef",
            }
            return self.secrets[name]
        if operation == "get-secret-value":
            return next(s for s in self.secrets.values() if s["ARN"] == parameters["SecretId"])
        if operation == "execute-statement":
            assert self.cluster["HttpEndpointEnabled"]
            return {"records": [[{"longValue": 1}]]}
        raise AssertionError((service, operation))


def test_preflight_never_mutates_or_reads_secret_values():
    aws = FakeAws()
    report = prepare.preflight(aws)
    assert report["cluster_exists"] is False
    assert report["engine_version"] == "17.9"
    assert all(op.startswith(("get-", "describe-")) for _, op, _ in aws.calls)
    assert all(service != "secretsmanager" for service, _, _ in aws.calls)


@pytest.mark.parametrize(
    "field,value",
    [
        ("accountPlanType", "PAID"),
        ("accountPlanStatus", "EXPIRED"),
        ("accountPlanExpirationDate", "2020-01-01T00:00:00+00:00"),
    ],
)
def test_non_free_or_expired_plan_rejected_before_resource_access(field, value):
    aws = FakeAws()
    aws.plan[field] = value
    with pytest.raises(ValueError):
        prepare.preflight(aws)
    assert [op for _, op, _ in aws.calls] == ["get-caller-identity", "get-account-plan-state"]


def test_empty_credits_and_wrong_project_or_region_rejected():
    plan = deepcopy(FREE)
    plan["accountPlanRemainingCredits"]["amount"] = "0"
    with pytest.raises(ValueError, match="credit"):
        prepare.check_free_plan(plan, datetime(2026, 11, 15, tzinfo=UTC))
    aws = FakeAws()
    with pytest.raises(ValueError, match="project"):
        prepare.preflight(aws, "999999999999")
    assert len(aws.calls) == 1
    with pytest.raises(ValueError, match="Region"):
        prepare.Aws("portfolio", "eu-central-1")
    aws.concurrency = 2
    with pytest.raises(ValueError, match="Lambda"):
        prepare.preflight(aws)


def test_repeated_apply_preserves_cluster_and_all_secret_values(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("OPENAI_API_KEY=synthetic-not-a-real-key\n")
    aws = FakeAws()
    configured = []
    monkeypatch.setattr(
        prepare, "configure_sql_user", lambda _, cluster, creds: configured.append(creds)
    )
    first = prepare.apply(aws, prepare.preflight(aws), env)
    values = deepcopy(aws.secrets)
    # Even a changed local key must not silently rotate the AWS secret on rerun.
    env.write_text("OPENAI_API_KEY=another-synthetic-key\n")
    second = prepare.apply(aws, prepare.preflight(aws), env)
    assert first == second
    assert aws.secrets == values
    assert configured[0] == configured[1]
    assert sum(op == "create-db-cluster" for _, op, _ in aws.calls) == 1
    assert sum(op == "create-secret" for _, op, _ in aws.calls) == 3
    assert "synthetic" not in json.dumps(first)


def test_unowned_cluster_and_secrets_are_never_adopted(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("OPENAI_API_KEY=synthetic-test\n")
    aws = FakeAws()
    monkeypatch.setattr(prepare, "configure_sql_user", lambda *args: None)
    prepare.apply(aws, prepare.preflight(aws), env)
    aws.cluster["TagList"] = []
    with pytest.raises(ValueError, match="ownership"):
        prepare.preflight(aws)
    aws.secrets["reconflow/db"]["Tags"] = []
    with pytest.raises(ValueError, match="ownership"):
        prepare.ensure_secret(aws, "db", lambda: pytest.fail("Must not overwrite"))


def test_missing_openai_key_stops_before_any_mutation(tmp_path):
    aws = FakeAws()
    with pytest.raises(ValueError, match="OPENAI_API_KEY"):
        prepare.apply(aws, {"account": ACCOUNT}, tmp_path / "absent.env")
    assert aws.calls == []


def test_sdk_errors_are_redacted_and_mutations_not_retried(monkeypatch):
    captured = []
    secret = "synthetic-password-that-must-not-appear-in-errors"

    def create_secret(**kwargs):
        captured.append(kwargs)
        raise ClientError(
            {"Error": {"Code": "AccessDeniedException", "Message": secret}}, "CreateSecret"
        )

    client = SimpleNamespace(create_secret=create_secret)
    monkeypatch.setattr(
        prepare.boto3,
        "Session",
        lambda **kwargs: SimpleNamespace(client=lambda *args, **kw: client),
    )
    aws = prepare.Aws("portfolio", "eu-north-1")
    with pytest.raises(prepare.AwsError) as error:
        aws.run("secretsmanager", "create-secret", {"SecretString": secret})
    assert secret not in str(error.value)
    assert captured == [{"SecretString": secret}]
    assert aws.config.retries["total_max_attempts"] == 1


def test_ambiguous_cluster_create_is_not_repeated(tmp_path):
    class AmbiguousAws(FakeAws):
        def run(self, service, operation, parameters=None, **kwargs):
            result = super().run(service, operation, parameters, **kwargs)
            if operation == "create-db-cluster":
                raise TimeoutError("Unknown creation outcome")
            return result

    env = tmp_path / ".env"
    env.write_text("OPENAI_API_KEY=synthetic-test\n")
    aws = AmbiguousAws()
    with pytest.raises(TimeoutError):
        prepare.apply(aws, prepare.preflight(aws), env)
    assert aws.cluster is not None
    assert sum(op == "create-db-cluster" for _, op, _ in aws.calls) == 1
    assert aws.secrets == {}


@pytest.mark.integration
def test_sql_login_creation_reuses_password_and_grants_no_admin(monkeypatch):
    username = "rf_setup_" + uuid.uuid4().hex[:16]
    database = "rf_setup_" + uuid.uuid4().hex[:16]
    password = "synthetic-test-password-with-quote-'" + uuid.uuid4().hex
    monkeypatch.setattr(prepare, "DB_USER", username)
    monkeypatch.setattr(prepare, "NAME", database)
    connect = prepare.psycopg.connect
    url = settings().database_url.get_secret_value()

    def local_connection(**kwargs):
        assert kwargs["sslmode"] == "verify-full"
        assert kwargs["sslrootcert"] == prepare.ssl.get_default_verify_paths().cafile
        assert kwargs["password"] == "synthetic-iam-token"
        return connect(url, dbname=kwargs["dbname"], autocommit=kwargs.get("autocommit", False))

    monkeypatch.setattr(prepare.psycopg, "connect", local_connection)
    aws = SimpleNamespace(run=lambda *args, **kwargs: "synthetic-iam-token")
    cluster = {"Endpoint": "synthetic", "Port": 5432, "MasterUsername": "admin"}
    try:
        prepare.configure_sql_user(aws, cluster, {"username": username, "password": password})
        with connect(url, dbname=database) as db:
            first = db.execute(
                "SELECT rolpassword, rolsuper, rolcreaterole, rolcreatedb FROM pg_authid WHERE rolname=%s",
                (username,),
            ).fetchone()
            assert first[1:] == (False, False, False)
            assert db.execute(
                "SELECT has_database_privilege(%s, %s, 'CONNECT'), has_schema_privilege(%s, 'public', 'CREATE')",
                (username, database, username),
            ).fetchone() == (True, True)
        prepare.configure_sql_user(
            aws,
            cluster,
            {"username": username, "password": "different-password-that-must-not-be-used"},
        )
        with connect(url) as db:
            assert (
                db.execute(
                    "SELECT rolpassword FROM pg_authid WHERE rolname=%s", (username,)
                ).fetchone()[0]
                == first[0]
            )
    finally:
        with connect(url, autocommit=True) as db:
            db.execute(
                prepare.sql.SQL("DROP DATABASE IF EXISTS {}").format(
                    prepare.sql.Identifier(database)
                )
            )
            if db.execute("SELECT 1 FROM pg_roles WHERE rolname=%s", (username,)).fetchone():
                db.execute(
                    prepare.sql.SQL("DROP OWNED BY {}").format(prepare.sql.Identifier(username))
                )
                db.execute(prepare.sql.SQL("DROP ROLE {}").format(prepare.sql.Identifier(username)))
