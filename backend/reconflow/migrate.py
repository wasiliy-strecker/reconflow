"""Execute reviewed, versioned SQL statements in one transaction per migration.

Migration files use a blank line between statements and do not contain procedural SQL.
The same files and checksum checks are used locally and through the AWS Data API.
"""

import hashlib
from pathlib import Path

from reconflow.db import transaction


def migrate():
    with transaction() as db:
        db.execute("SELECT pg_advisory_xact_lock(71823760) IS NULL AS locked")
        db.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations (version TEXT PRIMARY KEY, checksum TEXT NOT NULL, applied_at TIMESTAMPTZ DEFAULT now())"
        )
        for path in sorted((Path(__file__).parent / "migrations").glob("*.sql")):
            text = path.read_text()
            checksum = hashlib.sha256(text.encode()).hexdigest()
            previous = db.one(
                "SELECT checksum FROM schema_migrations WHERE version=:version",
                {"version": path.name},
            )
            if previous:
                if previous["checksum"] != checksum:
                    raise RuntimeError(f"Previously applied migration was edited: {path.name}")
                continue
            for statement in text.split(";\n"):
                if statement.strip():
                    db.execute(statement.strip().removesuffix(";"))
            db.execute(
                "INSERT INTO schema_migrations(version,checksum) VALUES (:version,:checksum)",
                {"version": path.name, "checksum": checksum},
            )
            print(f"Applied {path.name}")


def handler(event, context):
    migrate()
    return {"ok": True}


if __name__ == "__main__":
    migrate()
