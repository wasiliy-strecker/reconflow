"""Small shared SQL boundary. No ORM-specific SQL or session-level state.

Only application-authored queries may cross this boundary. Parameters are always bound.
The :name syntax is translated for psycopg; Data API consumes it directly.
"""

import json
import re
from contextlib import contextmanager
from datetime import date, datetime
from decimal import Decimal

import boto3
import psycopg
from psycopg.rows import dict_row

from reconflow.config import settings


def json_value(value):
    if isinstance(value, (Decimal, date, datetime)):
        return str(value)
    raise TypeError(type(value).__name__)


def dumps(value) -> str:
    return json.dumps(value, default=json_value, ensure_ascii=False, allow_nan=False)


def bind_parameter(name, value):
    result = {"name": name}
    if value is None:
        result["value"] = {"isNull": True}
    elif isinstance(value, bool):
        result["value"] = {"booleanValue": value}
    elif isinstance(value, int):
        result["value"] = {"longValue": value}
    else:
        result["value"] = {"stringValue": str(value)}
        if isinstance(value, Decimal):
            result["typeHint"] = "DECIMAL"
        elif isinstance(value, datetime):
            result["value"] = {"stringValue": value.strftime("%Y-%m-%d %H:%M:%S")}
            result["typeHint"] = "TIMESTAMP"
        elif isinstance(value, date):
            result["typeHint"] = "DATE"
    return result


class Connection:
    def __init__(self, config=None):
        self.config = config or settings()
        self.pg = None
        self.client = None
        self.transaction_id = None

    def open(self):
        if self.config.db_driver == "postgres":
            self.pg = psycopg.connect(
                self.config.database_url.get_secret_value(), row_factory=dict_row, connect_timeout=5
            )
        else:
            self.client = boto3.client("rds-data", region_name=self.config.aws_region)
            self.transaction_id = self.client.begin_transaction(**self.base())["transactionId"]

    def base(self):
        return {
            "resourceArn": self.config.db_cluster_arn,
            "secretArn": self.config.db_secret_arn,
            "database": self.config.db_name,
        }

    def execute(self, sql: str, parameters: dict | None = None) -> list[dict]:
        parameters = parameters or {}
        if self.pg:
            translated = re.sub(r"(?<!:):([A-Za-z_]\w*)", r"%(\1)s", sql)
            cursor = self.pg.execute(translated, parameters)
            return cursor.fetchall() if cursor.description else []
        # Return DECIMAL values as strings, never binary floats.
        result = self.client.execute_statement(
            **self.base(),
            transactionId=self.transaction_id,
            sql=sql,
            parameters=[bind_parameter(k, v) for k, v in parameters.items()],
            includeResultMetadata=True,
            resultSetOptions={"decimalReturnType": "STRING", "longReturnType": "LONG"},
        )
        columns = result.get("columnMetadata", [])
        rows = []
        for record in result.get("records", []):
            row = {}
            for meta, field in zip(columns, record, strict=True):
                value = None if field.get("isNull") else next(iter(field.values()))
                if meta.get("typeName") in {"json", "jsonb"} and isinstance(value, str):
                    value = json.loads(value)
                row[meta["name"]] = value
            rows.append(row)
        return rows

    def one(self, sql, parameters=None):
        rows = self.execute(sql, parameters)
        return rows[0] if rows else None

    def finish(self, success):
        if self.pg:
            try:
                self.pg.commit() if success else self.pg.rollback()
            finally:
                self.pg.close()
        elif self.transaction_id:
            method = self.client.commit_transaction if success else self.client.rollback_transaction
            method(
                resourceArn=self.config.db_cluster_arn,
                secretArn=self.config.db_secret_arn,
                transactionId=self.transaction_id,
            )


@contextmanager
def transaction(config=None):
    db = Connection(config)
    db.open()
    try:
        yield db
    except BaseException:
        db.finish(False)
        raise
    else:
        db.finish(True)
