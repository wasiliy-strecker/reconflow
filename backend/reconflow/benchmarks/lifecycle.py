"""Short, durable transitions; no Lambda waits for a model download or generation."""

import logging
import time

from reconflow.benchmarks import objects, security, service
from reconflow.benchmarks.provider import VastProvider
from reconflow.config import settings
from reconflow.db import dumps, transaction

logger = logging.getLogger("reconflow.benchmarks")

# Only fixed code is executed. All variable values arrive as environment fields.
BOOTSTRAP = """python3 - <<'RF_BOOT'
import hashlib, io, os, pathlib, subprocess, urllib.request, zipfile
with urllib.request.urlopen(os.environ['RF_ARTIFACT_URL'], timeout=30) as r:
    data = r.read(2 * 1024 * 1024 + 1)
if len(data) > 2 * 1024 * 1024 or hashlib.sha256(data).hexdigest() != os.environ['RF_ARTIFACT_SHA256']:
    raise RuntimeError('Invalid runner artifact')
root = pathlib.Path('/tmp/reconflow-runner')
root.mkdir(mode=0o700, exist_ok=True)
with zipfile.ZipFile(io.BytesIO(data)) as z:
    if set(z.namelist()) != {'runner.py', 'bootstrap.py', 'manifest.json'}:
        raise RuntimeError('Invalid runner members')
    for name in z.namelist():
        (root / name).write_bytes(z.read(name))
subprocess.run(['python3', str(root / 'bootstrap.py')], check=True)
RF_BOOT"""


def finish(identifier, failed=False, message=None):
    with transaction() as db:
        row = db.one("SELECT * FROM gpu_leases WHERE id=:id FOR UPDATE", {"id": identifier})
        if not row or row["status"] in service.TERMINAL:
            return
        # Until an actual provider invoice is reconciled, debit the whole reserved
        # allowance. Never advertise an estimate as a confirmed provider charge.
        debit = 0 if failed and row["attempted_at"] is None else row["reserved_eur"]
        db.execute(
            "UPDATE gpu_months SET reserved_eur=reserved_eur-:reserved,debited_eur=debited_eur+:debit WHERE month=:month",
            {"reserved": row["reserved_eur"], "debit": debit, "month": row["month"]},
        )
        db.execute(
            "UPDATE gpu_leases SET status=:status,debited_eur=:debit,finished_at=now(),error=COALESCE(:error,error) WHERE id=:id",
            {
                "id": identifier,
                "status": "failed" if failed else "destroyed",
                "debit": debit,
                "error": message,
            },
        )
        db.execute(
            "UPDATE gpu_requests SET status=CASE WHEN status='running' THEN 'unknown' ELSE 'failed' END,error='GPU-Sitzung beendet; Anfrage wird nicht wiederholt.',finished_at=now() WHERE lease_id=:id AND status IN ('pending','running')",
            {"id": identifier},
        )
        service.event(db, identifier, "failed" if failed else "destroyed_confirmed")
    objects.remove("control/" + identifier + ".json")


def process(identifier):
    with transaction() as db:
        row = db.one("SELECT * FROM gpu_leases WHERE id=:id", {"id": identifier})
    if not row or row["status"] != "queued":
        return
    try:
        service.admission()
        provider = VastProvider()
        current = next(
            (o for o in provider.offers(row["offer"]["id"]) if o["id"] == row["offer"]["id"]), None
        )
        if current != row["offer"]:
            raise ValueError("Das GPU-Angebot hat sich vor der Miete geändert.")
        env = {
            "RF_API": settings().public_origin,
            "RF_LEASE": identifier,
            "RF_TOKEN": security.token(identifier, "runner"),
            "RF_DEADLINE": str(int(service.timestamp(row["deadline_at"]).timestamp())),
            "RF_STARTUP_SECONDS": str(settings().gpu_startup_seconds),
            "RF_REQUEST_SECONDS": str(settings().gpu_request_seconds),
            "RF_MODEL": row["model"],
            "RF_ARTIFACT_URL": objects.artifact_url(),
            "RF_ARTIFACT_SHA256": settings().gpu_runner_artifact_sha256,
            "NVIDIA_VISIBLE_DEVICES": "all",
            "NVIDIA_DRIVER_CAPABILITIES": "compute,utility",
        }
    except Exception:
        finish(
            identifier,
            failed=True,
            message="Startvorbereitung fehlgeschlagen. Es wurde keine GPU gemietet.",
        )
        return
    with transaction() as db:
        row = db.one("SELECT * FROM gpu_leases WHERE id=:id FOR UPDATE", {"id": identifier})
        if row["status"] != "queued":
            return
        if service.timestamp(row["deadline_at"]) <= service.now() or row["session_id"] is None:
            db.execute("UPDATE gpu_leases SET status='stopping' WHERE id=:id", {"id": identifier})
            return
        db.execute(
            "UPDATE gpu_leases SET status='creating',attempted_at=now() WHERE id=:id",
            {"id": identifier},
        )
        service.event(db, identifier, "create_attempted")
    try:
        response = provider.create(row["offer"]["id"], row["label"], env, BOOTSTRAP)
        if response.get("success") is not True or not isinstance(response.get("new_contract"), int):
            raise ValueError("Ambiguous provider response")
        with transaction() as db:
            db.execute(
                "UPDATE gpu_leases SET instance_id=:instance,status=CASE WHEN status='creating' THEN 'starting' ELSE status END WHERE id=:id",
                {"id": identifier, "instance": response["new_contract"]},
            )
    except Exception:
        # Even a rejected HTTP request may have passed a proxy after acceptance.
        # Reconcile by the signed label, never repeat this create.
        with transaction() as db:
            db.execute(
                "UPDATE gpu_leases SET status=CASE WHEN status='creating' THEN 'unknown' ELSE status END,error='Mietantwort unklar. Automatischer Abgleich läuft; keine erneute Miete.' WHERE id=:id",
                {"id": identifier},
            )
        logger.warning(dumps({"event": "gpu.create_unknown", "lease_id": identifier}))


def needs_stop(row, current):
    c = settings()
    if row["status"] == "stopping" or row["session_id"] is None or row.get("session_expired"):
        return True
    if service.timestamp(row["deadline_at"]) <= current:
        return True
    if row["status"] in {"creating", "unknown", "starting"}:
        return (
            current - service.timestamp(row["created_at"])
        ).total_seconds() > c.gpu_startup_seconds
    if row["status"] in {"ready", "busy"}:
        if (
            not row["heartbeat_at"]
            or (current - service.timestamp(row["heartbeat_at"])).total_seconds() > 90
        ):
            return True
        if (
            row["status"] == "ready"
            and (current - service.timestamp(row["last_activity_at"])).total_seconds()
            > c.gpu_idle_seconds
        ):
            return True
    return False


def sweep(provider=None):
    """Also deletes signed orphan rentals when the SQL transport is unavailable."""
    provider = provider or VastProvider()
    current = service.now()
    instances = provider.instances()  # Failure leaves the previous health record stale.
    owned = {}
    for instance in instances:
        parsed = security.parse_label(instance.get("label", ""))
        if parsed:
            owned.setdefault(parsed[0], []).append((instance, parsed[1]))
    controls = set(objects.controls())
    healthy = True

    def destroy(instance_id):
        nonlocal healthy
        try:
            provider.destroy(instance_id)
        except Exception:
            healthy = False
            logger.error('{"event":"gpu.destroy_unconfirmed"}')

    for identifier in controls | set(owned):
        matches = owned.get(identifier, [])
        try:
            with transaction() as db:
                row = db.one(
                    "SELECT l.*, (s.id IS NULL OR s.expires_at<now()) AS session_expired FROM gpu_leases l LEFT JOIN sessions s ON s.id=l.session_id WHERE l.id=:id",
                    {"id": identifier},
                )
        except Exception:
            # Fail closed: no database is needed to authenticate owned labels.
            for instance, _ in matches:
                destroy(instance["id"])
            healthy = False
            logger.error(dumps({"event": "gpu.cleanup_without_database", "lease_id": identifier}))
            continue
        if not row:
            for instance, _ in matches:
                destroy(instance["id"])
            if not matches:
                objects.remove("control/" + identifier + ".json")
            continue
        if matches:
            objects.remove("absence/" + identifier + ".json")
            for instance, expiry in matches:
                stop = (
                    row["status"] in service.TERMINAL
                    or len(matches) != 1
                    or expiry <= int(current.timestamp())
                    or needs_stop(row, current)
                )
                if stop:
                    with transaction() as db:
                        if row["status"] not in service.TERMINAL:
                            db.execute(
                                "UPDATE gpu_leases SET status='stopping' WHERE id=:id",
                                {"id": identifier},
                            )
                    destroy(instance["id"])
                    # A successful destroy response alone is not proof of absence.
                elif row["instance_id"] is None or row["status"] in {"creating", "unknown"}:
                    with transaction() as db:
                        db.execute(
                            "UPDATE gpu_leases SET instance_id=:instance,status=CASE WHEN status IN ('creating','unknown') THEN 'starting' ELSE status END,error=NULL WHERE id=:id AND status NOT IN ('stopping','destroyed','failed')",
                            {"instance": instance["id"], "id": identifier},
                        )
        elif row["status"] in service.TERMINAL:
            objects.remove("control/" + identifier + ".json")
        elif row["attempted_at"] is None:
            if needs_stop(row, current):
                finish(identifier, failed=True)
            elif row["status"] == "queued":
                service.dispatch(identifier)  # Recover a failed SQL-to-SQS handoff.
        else:
            # Three independent scans at least a minute apart, and no early refund
            # of unknown creation. A late instance retains its signed hard deadline.
            previous = objects.get("absence/" + identifier + ".json") or {
                "count": 0,
                "at": "1970-01-01T00:00:00+00:00",
            }
            if (current - service.timestamp(previous["at"])).total_seconds() >= 55:
                previous = {"count": previous["count"] + 1, "at": current.isoformat()}
                objects.put("absence/" + identifier + ".json", previous)
            safe = (
                row["instance_id"] is not None or service.timestamp(row["deadline_at"]) <= current
            )
            if previous["count"] >= 3 and safe:
                finish(identifier)
                objects.remove("absence/" + identifier + ".json")
    objects.put("watchdog.json", {"healthy": healthy, "at": current.isoformat()})
    if not healthy:
        raise RuntimeError("GPU cleanup required; admissions disabled")
    return {"checked": len(controls | set(owned))}


def handler(event, context):
    # Feature disabling stops admission, never cleanup. No OpenAI call is made.
    try:
        if not settings().vast_api_key.get_secret_value():
            return {"configured": False}
        return sweep()
    except Exception:
        logger.error('{"event":"gpu.watchdog_failed"}')
        raise


def main():
    logging.basicConfig(level=logging.INFO)
    while True:
        try:
            sweep()
        except Exception:
            logger.error('{"event":"gpu.watchdog_failed"}')
        time.sleep(60)


if __name__ == "__main__":
    main()
