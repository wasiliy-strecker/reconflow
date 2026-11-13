import io
import re
import uuid

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill

from reconflow import fixtures, storage
from reconflow.config import settings
from reconflow.db import dumps, transaction
from reconflow.domain import InvoiceData, invoice_issues, parse_payments, read_csv, reconcile


def uid():
    return str(uuid.uuid4())


def audit(db, session, action, target, payload):
    db.execute(
        "INSERT INTO audit_events(session_id,action,target,payload) VALUES (:session,:action,:target,CAST(:payload AS jsonb))",
        {"session": session, "action": action, "target": target, "payload": dumps(payload)},
    )


def active_session(db, session):
    if not db.one("SELECT id FROM sessions WHERE id=:id AND expires_at>now()", {"id": session}):
        raise PermissionError("Die Demo-Sitzung ist abgelaufen. Bitte neu starten.")


def create_session():
    session = uid()
    # Advisory lock makes the demo's global admission limit atomic across Lambda instances.
    with transaction() as db:
        db.execute("SELECT pg_advisory_xact_lock(71823761)")
        count = db.one(
            "SELECT count(*) AS count FROM sessions WHERE created_at>now()-interval '1 hour'"
        )
        if int(count["count"]) >= settings().max_sessions_per_hour:
            raise ValueError(
                "Die Demo ist gerade stark ausgelastet. Bitte später erneut versuchen."
            )
        db.execute("DELETE FROM sessions WHERE expires_at<now()")
        db.execute("INSERT INTO sessions(id) VALUES (:id)", {"id": session})
    return session


def upload_document(session, filename, content):
    mime = storage.validate_document(content)
    sha = storage.digest(content)
    if settings().public_demo and sha not in {
        storage.digest(fixtures.document(i)[2]) for i in range(len(fixtures.SPECS))
    }:
        raise ValueError(
            "Die öffentliche Demo akzeptiert ausschließlich die bereitgestellten Beispieldateien."
        )
    # Both upload and confirmation use the session row lock for consistent snapshots.
    with transaction() as db:
        active_session(db, session)
        db.one("SELECT id FROM sessions WHERE id=:id FOR UPDATE", {"id": session})
        previous = db.one(
            "SELECT * FROM documents WHERE session_id=:session AND sha256=:sha",
            {"session": session, "sha": sha},
        )
        if previous:
            return {**previous, "duplicate": True}
        count = db.one(
            "SELECT count(*) AS count FROM documents WHERE session_id=:session",
            {"session": session},
        )
        if int(count["count"]) >= settings().max_documents:
            raise ValueError("Diese Sitzung enthält bereits die maximale Anzahl Dokumente.")
        identifier = uid()
        filename = re.sub(r"[^\w. -]", "_", filename)[:150] or "rechnung"
        key = f"sessions/{session}/{identifier}"
        storage.put(key, content, mime)
        row = {
            "id": identifier,
            "session": session,
            "filename": filename,
            "mime": mime,
            "sha": sha,
            "key": key,
        }
        db.execute(
            "INSERT INTO documents(id,session_id,filename,mime,sha256,storage_key) VALUES (:id,:session,:filename,:mime,:sha,:key)",
            row,
        )
        audit(db, session, "document.uploaded", identifier, {"sha256": sha})
        return db.one("SELECT * FROM documents WHERE id=:id", {"id": identifier})


def seed(session):
    for i in range(len(fixtures.SPECS)):
        name, _, content = fixtures.document(i)
        doc = upload_document(session, name, content)
        with transaction() as db:
            db.execute(
                "INSERT INTO invoices(id,session_id,document_id,payload,confirmed,source) VALUES (:id,:session,:document,CAST(:payload AS jsonb),TRUE,'example') ON CONFLICT (document_id) DO NOTHING",
                {
                    "id": uid(),
                    "session": session,
                    "document": doc["id"],
                    "payload": fixtures.invoice_data(i).model_dump_json(),
                },
            )
    import_payments(session, fixtures.payment_csv())
    return overview(session)


def overview(session):
    with transaction() as db:
        active_session(db, session)
        invoices = db.execute(
            "SELECT i.*,d.filename,d.mime FROM invoices i LEFT JOIN documents d ON d.id=i.document_id WHERE i.session_id=:session ORDER BY i.created_at,i.id",
            {"session": session},
        )
        docs = db.execute(
            "SELECT id,filename,mime,created_at FROM documents WHERE session_id=:session ORDER BY created_at",
            {"session": session},
        )
        payments = db.execute(
            "SELECT * FROM payments WHERE session_id=:session ORDER BY paid_at,external_id",
            {"session": session},
        )
        jobs = db.execute(
            "SELECT id,kind,target,status,error,payload,created_at FROM jobs WHERE session_id=:session ORDER BY created_at DESC LIMIT 30",
            {"session": session},
        )
        run = db.one(
            "SELECT * FROM runs WHERE session_id=:session ORDER BY created_at DESC,id DESC LIMIT 1",
            {"session": session},
        )
        imports = db.execute(
            "SELECT id,kind,payload,created_at FROM imports WHERE session_id=:session ORDER BY created_at DESC LIMIT 20",
            {"session": session},
        )
    for invoice in invoices:
        invoice["issues"] = invoice_issues(InvoiceData.model_validate(invoice["payload"]))
    return {
        "invoices": invoices,
        "documents": docs,
        "payments": payments,
        "jobs": jobs,
        "run": run,
        "imports": imports,
    }


def confirm_invoice(session, identifier, data, version):
    issues = invoice_issues(data)
    if issues:
        raise ValueError(" ".join(issues))
    with transaction() as db:
        active_session(db, session)
        db.one("SELECT id FROM sessions WHERE id=:id FOR UPDATE", {"id": session})
        old = db.one(
            "SELECT * FROM invoices WHERE id=:id AND session_id=:session FOR UPDATE",
            {"id": identifier, "session": session},
        )
        if not old:
            raise LookupError("Rechnung nicht gefunden.")
        if old["version"] != version:
            raise ValueError("Die Rechnung wurde inzwischen geändert. Bitte neu laden.")
        db.execute(
            "UPDATE invoices SET payload=CAST(:payload AS jsonb),confirmed=TRUE,version=version+1 WHERE id=:id",
            {"id": identifier, "payload": data.model_dump_json()},
        )
        audit(
            db,
            session,
            "invoice.confirmed",
            identifier,
            {"before": old["payload"], "after": data.model_dump(mode="json")},
        )
    return {"id": identifier, "confirmed": True, "version": version + 1}


def import_payments(session, content):
    if settings().public_demo and storage.digest(content) != storage.digest(fixtures.payment_csv()):
        raise ValueError("Bitte die bereitgestellte Zahlungs-CSV verwenden.")
    payments, errors = parse_payments(content, settings().max_csv_rows)
    if errors:
        return {"inserted": 0, "duplicates": 0, "errors": errors}
    sha = storage.digest(content)
    with transaction() as db:
        active_session(db, session)
        db.one("SELECT id FROM sessions WHERE id=:id FOR UPDATE", {"id": session})
        old = db.one(
            "SELECT payload FROM imports WHERE session_id=:session AND sha256=:sha AND kind='payments'",
            {"session": session, "sha": sha},
        )
        if old:
            return {
                "inserted": 0,
                "duplicates": len(payments),
                "errors": [],
                "repeated_import": True,
            }
        current = db.execute(
            "SELECT * FROM payments WHERE session_id=:session", {"session": session}
        )
        existing = {p["external_id"]: p for p in current}
        if len(existing) + len(payments) > settings().max_csv_rows:
            raise ValueError("Die Sitzung enthält zu viele Zahlungszeilen.")
        for p in payments:
            if p["external_id"] in existing:
                old = existing[p["external_id"]]
                if any(
                    str(old[k]) != str(p[k])
                    for k in ["reference", "amount", "currency", "paid_at", "payer"]
                ):
                    raise ValueError(
                        "Eine vorhandene payment_id enthält abweichende Daten. Import abgebrochen."
                    )
        inserted = 0
        for payment in payments:
            if payment["external_id"] not in existing:
                db.execute(
                    "INSERT INTO payments(id,session_id,external_id,reference,amount,currency,paid_at,payer) VALUES (:id,:session,:external_id,:reference,:amount,:currency,CAST(:paid_at AS date),:payer)",
                    {"id": uid(), "session": session, **payment},
                )
                inserted += 1
        result = {"inserted": inserted, "duplicates": len(payments) - inserted, "errors": []}
        db.execute(
            "INSERT INTO imports(id,session_id,sha256,kind,payload) VALUES (:id,:session,:sha,'payments',CAST(:payload AS jsonb))",
            {"id": uid(), "session": session, "sha": sha, "payload": dumps(result)},
        )
        audit(db, session, "payments.imported", sha, result)
        return result


def import_invoices(session, content):
    if settings().public_demo:
        raise ValueError("Rechnungs-CSV ist in der lokalen Umgebung verfügbar.")
    rows, errors = read_csv(
        content,
        {"invoice_number", "issuer", "customer", "invoice_date", "currency", "gross_amount"},
    )
    parsed = []
    for line, row in rows:
        try:
            data = InvoiceData.model_validate({key: value or None for key, value in row.items()})
            parsed.append(data)
        except ValueError:
            errors.append(
                {
                    "line": line,
                    "message": "Rechnungsdaten sind ungültig. Bitte Vorlage und Beträge prüfen.",
                }
            )
    if errors:
        return {"inserted": 0, "errors": errors}
    sha = storage.digest(content)
    with transaction() as db:
        active_session(db, session)
        db.one("SELECT id FROM sessions WHERE id=:id FOR UPDATE", {"id": session})
        if db.one(
            "SELECT id FROM imports WHERE session_id=:session AND sha256=:sha AND kind='invoices'",
            {"session": session, "sha": sha},
        ):
            return {"inserted": 0, "errors": [], "repeated_import": True}
        if len(parsed) > settings().max_documents:
            raise ValueError("Höchstens 20 Rechnungen pro Import.")
        for data in parsed:
            db.execute(
                "INSERT INTO invoices(id,session_id,payload,source) VALUES (:id,:session,CAST(:payload AS jsonb),'csv')",
                {"id": uid(), "session": session, "payload": data.model_dump_json()},
            )
        result = {"inserted": len(parsed), "errors": []}
        db.execute(
            "INSERT INTO imports(id,session_id,sha256,kind,payload) VALUES (:id,:session,:sha,'invoices',CAST(:payload AS jsonb))",
            {"id": uid(), "session": session, "sha": sha, "payload": dumps(result)},
        )
        return result


def create_job(session, kind, target, payload=None, retry=False):
    request_key = target + (":" + uid() if retry else "")
    with transaction() as db:
        active_session(db, session)
        db.one("SELECT id FROM sessions WHERE id=:id FOR UPDATE", {"id": session})
        existing = db.one(
            "SELECT * FROM jobs WHERE session_id=:session AND kind=:kind AND request_key=:key",
            {"session": session, "kind": kind, "key": request_key},
        )
        if existing:
            job = existing
        else:
            count = db.one(
                "SELECT count(*) AS count FROM jobs WHERE session_id=:session", {"session": session}
            )
            if int(count["count"]) >= settings().max_jobs_per_session:
                raise ValueError("Das Verarbeitungslimit dieser Sitzung ist erreicht.")
            job = {
                "id": uid(),
                "session": session,
                "kind": kind,
                "target": target,
                "key": request_key,
                "payload": dumps(payload or {}),
            }
            db.execute(
                "INSERT INTO jobs(id,session_id,kind,target,request_key,payload) VALUES (:id,:session,:kind,:target,:key,CAST(:payload AS jsonb))",
                job,
            )
            job = db.one("SELECT * FROM jobs WHERE id=:id", {"id": job["id"]})
    # Persist first. If dispatch fails, the same request resends the pending job.
    if job["status"] == "pending":
        storage.enqueue(job["id"])
    return job


def run_reconciliation(session, decisions=None):
    with transaction() as db:
        active_session(db, session)
        db.one("SELECT id FROM sessions WHERE id=:id FOR UPDATE", {"id": session})
        invoices = db.execute(
            "SELECT * FROM invoices WHERE session_id=:session ORDER BY id", {"session": session}
        )
        payments = db.execute(
            "SELECT * FROM payments WHERE session_id=:session ORDER BY id", {"session": session}
        )
        previous = db.one(
            "SELECT payload FROM runs WHERE session_id=:session ORDER BY created_at DESC,id DESC LIMIT 1",
            {"session": session},
        )
        saved = previous["payload"].get("decisions", {}) if previous else {}
        saved.update(decisions or {})
        for payment_id, invoice_id in saved.items():
            p = next((p for p in payments if p["id"] == payment_id), None)
            i = next((i for i in invoices if i["id"] == invoice_id and i["confirmed"]), None)
            if not p or not i or p["currency"] != i["payload"]["currency"]:
                raise ValueError("Ungültige Zuordnung oder abweichende Währung.")
        rows = reconcile(invoices, payments, saved)
        identifier = uid()
        result = {
            "results": rows,
            "decisions": saved,
            "invoice_versions": {i["id"]: i["version"] for i in invoices},
            "payment_ids": [p["id"] for p in payments],
        }
        db.execute(
            "INSERT INTO runs(id,session_id,payload) VALUES (:id,:session,CAST(:payload AS jsonb))",
            {"id": identifier, "session": session, "payload": dumps(result)},
        )
        audit(
            db,
            session,
            "reconciliation.completed",
            identifier,
            {"decisions": decisions or {}, "rows": len(rows)},
        )
        return {"id": identifier, "payload": result}


def excel(session, run_id):
    with transaction() as db:
        active_session(db, session)
        run = db.one(
            "SELECT * FROM runs WHERE id=:id AND session_id=:session",
            {"id": run_id, "session": session},
        )
        if not run:
            raise LookupError("Abgleich nicht gefunden.")
        invoices = db.execute(
            "SELECT * FROM invoices WHERE session_id=:session ORDER BY id", {"session": session}
        )
        payments = db.execute(
            "SELECT * FROM payments WHERE session_id=:session ORDER BY id", {"session": session}
        )
        imports = db.execute(
            "SELECT kind,payload,created_at FROM imports WHERE session_id=:session",
            {"session": session},
        )
    if run["payload"]["invoice_versions"] != {i["id"]: i["version"] for i in invoices} or run[
        "payload"
    ]["payment_ids"] != [p["id"] for p in payments]:
        raise ValueError("Die Daten wurden geändert. Bitte zuerst einen neuen Abgleich starten.")
    wb = Workbook()
    wb.remove(wb.active)
    sheets = {
        "Abgleich": [
            [
                "Rechnung",
                "Kunde",
                "Status",
                "Erwartet",
                "Erhalten",
                "Differenz",
                "Währung",
                "Begründung",
            ]
        ]
        + [
            [
                r["invoice_number"],
                r["customer"],
                r["status"],
                r["expected"],
                r["received"],
                r["difference"],
                r["currency"],
                r["reason"],
            ]
            for r in run["payload"]["results"]
        ],
        "Rechnungen": [["Nummer", "Kunde", "Brutto", "Währung", "Bestätigt", "Quelle"]]
        + [
            [
                i["payload"].get("invoice_number"),
                i["payload"].get("customer"),
                i["payload"].get("gross_amount"),
                i["payload"].get("currency"),
                i["confirmed"],
                i["source"],
            ]
            for i in invoices
        ],
        "Zahlungen": [["ID", "Referenz", "Betrag", "Währung", "Datum", "Zahler"]]
        + [
            [
                p["external_id"],
                p["reference"],
                str(p["amount"]),
                p["currency"],
                str(p["paid_at"]),
                p["payer"],
            ]
            for p in payments
        ],
        "Importe": [["Art", "Zeitpunkt", "Ergebnis"]]
        + [[i["kind"], str(i["created_at"]), dumps(i["payload"])] for i in imports],
    }
    for title, rows in sheets.items():
        sheet = wb.create_sheet(title)
        for row in rows:
            sheet.append(row)
            # Never interpret user-controlled strings as spreadsheet formulas.
            for cell in sheet[sheet.max_row]:
                if isinstance(cell.value, str):
                    cell.data_type = "s"
        sheet.freeze_panes = "A2"
        sheet.auto_filter.ref = sheet.dimensions
        for cell in sheet[1]:
            cell.font = Font(bold=True, color="FFFFFF")
            cell.fill = PatternFill("solid", fgColor="143D35")
        for column in sheet.columns:
            sheet.column_dimensions[column[0].column_letter].width = min(
                55, max(15, max(len(str(c.value or "")) for c in column) + 2)
            )
    output = io.BytesIO()
    wb.save(output)
    return output.getvalue()
