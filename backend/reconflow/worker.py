import json
import logging
import time

from openai import APIConnectionError, APIStatusError, APITimeoutError

from reconflow import ai, service, storage
from reconflow.config import settings
from reconflow.db import dumps, transaction
from reconflow.domain import invoice_issues

logger = logging.getLogger("reconflow.worker")


def process(job_id):
    with transaction() as db:
        job = db.one("SELECT * FROM jobs WHERE id=:id FOR UPDATE", {"id": job_id})
        if not job or job["status"] != "pending":
            return
        service.active_session(db, job["session_id"])
        db.execute("UPDATE jobs SET status='running',started_at=now() WHERE id=:id", {"id": job_id})
    session = job["session_id"]
    try:
        if job["kind"] == "extract":
            with transaction() as db:
                document = db.one(
                    "SELECT * FROM documents WHERE id=:id AND session_id=:session",
                    {"id": job["target"], "session": session},
                )
                if not document:
                    raise ValueError("Dokument nicht gefunden.")
                old = db.one(
                    "SELECT version FROM invoices WHERE document_id=:id", {"id": document["id"]}
                )
                version = old["version"] if old else None
            data = ai.extract(
                job_id, storage.get(document["storage_key"]), document["mime"], document["filename"]
            )
            with transaction() as db:
                service.active_session(db, session)
                db.one("SELECT id FROM sessions WHERE id=:id FOR UPDATE", {"id": session})
                existing = db.one(
                    "SELECT * FROM invoices WHERE document_id=:id FOR UPDATE",
                    {"id": document["id"]},
                )
                if existing and existing["version"] != version:
                    raise ValueError(
                        "Die Rechnung wurde während der KI-Auswertung bearbeitet. Ergebnis nicht übernommen."
                    )
                if existing:
                    identifier = existing["id"]
                    db.execute(
                        "UPDATE invoices SET payload=CAST(:payload AS jsonb),confirmed=FALSE,source='openai',version=version+1 WHERE id=:id",
                        {"payload": data.model_dump_json(), "id": identifier},
                    )
                else:
                    identifier = service.uid()
                    db.execute(
                        "INSERT INTO invoices(id,session_id,document_id,payload,source) VALUES (:id,:session,:document,CAST(:payload AS jsonb),'openai')",
                        {
                            "id": identifier,
                            "session": session,
                            "document": document["id"],
                            "payload": data.model_dump_json(),
                        },
                    )
                result = {
                    "invoice_id": identifier,
                    "issues": invoice_issues(data),
                    "source": "openai",
                    "model": settings().openai_model,
                }
                service.audit(
                    db,
                    session,
                    "invoice.extracted",
                    identifier,
                    {"model": settings().openai_model, "prompt_version": ai.PROMPT_VERSION},
                )
        elif job["kind"] == "reconcile":
            result = service.run_reconciliation(session)
        elif job["kind"] == "suggest":
            with transaction() as db:
                payment = db.one(
                    "SELECT * FROM payments WHERE id=:id AND session_id=:session",
                    {"id": job["target"], "session": session},
                )
                candidates = []
                for identifier in job["payload"]["candidates"]:
                    invoice = db.one(
                        "SELECT id,payload,version FROM invoices WHERE id=:id AND session_id=:session AND confirmed=TRUE",
                        {"id": identifier, "session": session},
                    )
                    if invoice and invoice["payload"]["currency"] == payment["currency"]:
                        candidates.append(invoice)
                if not candidates:
                    raise ValueError("Keine passenden bestätigten Rechnungen für einen Vorschlag.")
            result = ai.suggest(job_id, payment, candidates).model_dump()
            result["versions"] = {i["id"]: i["version"] for i in candidates}
            result["payment_id"] = payment["id"]
        else:
            raise ValueError("Unbekannter Auftrag.")
        with transaction() as db:
            db.execute(
                "UPDATE jobs SET status='succeeded',payload=CAST(:payload AS jsonb),finished_at=now() WHERE id=:id AND status='running'",
                {"id": job_id, "payload": dumps(result)},
            )
        logger.info(dumps({"event": "job.succeeded", "job_id": job_id, "kind": job["kind"]}))
    except Exception as exc:
        if isinstance(exc, (APITimeoutError, APIConnectionError)):
            message = "OpenAI war nicht erreichbar oder antwortete nicht rechtzeitig. Ein begonnenes KI-Budget bleibt vorsorglich reserviert."
        elif isinstance(exc, APIStatusError):
            message = "OpenAI hat die Anfrage abgelehnt. Modellzugriff, API-Limit oder Kontoguthaben prüfen."
        elif isinstance(exc, (ValueError, PermissionError)):
            message = str(exc)[:500]
        else:
            message = "Die Verarbeitung ist fehlgeschlagen. Es wurde nichts automatisch bestätigt."
        with transaction() as db:
            db.execute(
                "UPDATE jobs SET status='failed',error=:error,finished_at=now() WHERE id=:id",
                {"id": job_id, "error": message},
            )
        logger.warning(
            dumps({"event": "job.failed", "job_id": job_id, "error_type": type(exc).__name__})
        )


def handler(event, context):
    failures = []
    for record in event.get("Records", []):
        try:
            dispatch(json.loads(record["body"]))
        except Exception:
            # Infrastructure errors before/after the durable claim can be redelivered.
            # A claimed/running job is never sent to OpenAI a second time.
            failures.append({"itemIdentifier": record["messageId"]})
    return {"batchItemFailures": failures}


def dispatch(message):
    if "benchmark_lease_id" in message:
        from reconflow.benchmarks.lifecycle import process as process_benchmark

        process_benchmark(message["benchmark_lease_id"])
    else:
        process(message["job_id"])


def main():
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    queue = storage.client("sqs")
    while True:
        try:
            response = queue.receive_message(
                QueueUrl=settings().sqs_queue_url, WaitTimeSeconds=10, MaxNumberOfMessages=1
            )
            for item in response.get("Messages", []):
                dispatch(json.loads(item["Body"]))
                queue.delete_message(
                    QueueUrl=settings().sqs_queue_url, ReceiptHandle=item["ReceiptHandle"]
                )
        except KeyboardInterrupt:
            return
        except Exception as exc:
            logger.warning(dumps({"event": "worker.unavailable", "error_type": type(exc).__name__}))
            time.sleep(3)


if __name__ == "__main__":
    main()
