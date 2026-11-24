import hashlib
import hmac
from typing import Annotated

from botocore.exceptions import ClientError
from fastapi import Depends, FastAPI, HTTPException, Request, Response, UploadFile
from fastapi.responses import JSONResponse
from mangum import Mangum
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from reconflow import fixtures, service, storage
from reconflow.config import settings
from reconflow.db import dumps, transaction
from reconflow.domain import InvoiceData

app = FastAPI(
    title="ReconFlow API",
    version="0.1.0",
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
    redoc_url=None,
)


class BodyLimit:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        size = 0

        async def limited_receive():
            nonlocal size
            message = await receive()
            size += len(message.get("body", b""))
            if size > 5 * 1024 * 1024:
                raise HTTPException(413, "Anfrage ist zu groß.")
            return message

        await self.app(scope, limited_receive, send)


app.add_middleware(BodyLimit)


class SafeJSON(JSONResponse):
    def render(self, content):
        return dumps(content).encode()


def signature(session, purpose):
    return hmac.new(
        settings().session_secret.get_secret_value().encode(),
        (purpose + ":" + session).encode(),
        hashlib.sha256,
    ).hexdigest()


@app.middleware("http")
async def guards(request: Request, call_next):
    if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
        origin = request.headers.get("origin")
        if origin and origin != settings().public_origin:
            return JSONResponse({"detail": "Diese Herkunft ist nicht erlaubt."}, status_code=403)
        if not origin and settings().public_demo:
            return JSONResponse({"detail": "Origin-Header erforderlich."}, status_code=403)
        size = request.headers.get("content-length")
        if size and (not size.isdigit() or int(size) > 5 * 1024 * 1024):
            return JSONResponse({"detail": "Anfrage ist zu groß."}, status_code=413)
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "same-origin"
    response.headers["Cache-Control"] = "no-store"
    return response


@app.exception_handler(ValueError)
async def invalid(request, exc):
    return JSONResponse({"detail": str(exc)}, status_code=422)


@app.exception_handler(PermissionError)
async def forbidden(request, exc):
    return JSONResponse({"detail": str(exc)}, status_code=401)


@app.exception_handler(LookupError)
async def missing(request, exc):
    return JSONResponse({"detail": str(exc)}, status_code=404)


@app.exception_handler(ClientError)
async def aws_unavailable(request, exc):
    return JSONResponse(
        {
            "detail": "Die Demo wird gestartet oder ein Dienst ist vorübergehend nicht verfügbar. Bitte kurz warten."
        },
        status_code=503,
        headers={"Retry-After": "5"},
    )


def session(request: Request):
    cookie = request.cookies.get("reconflow_session", "")
    identifier, _, mac = cookie.partition(".")
    if not identifier or not hmac.compare_digest(signature(identifier, "cookie"), mac):
        raise PermissionError("Bitte zuerst eine Demo-Sitzung starten.")
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        if not hmac.compare_digest(
            signature(identifier, "csrf"), request.headers.get("x-csrf-token", "")
        ):
            raise HTTPException(403, "Ungültiges Sitzungstoken.")
    with transaction() as db:
        service.active_session(db, identifier)
    return identifier


Session = Annotated[str, Depends(session)]


@app.get("/health")
def health():
    return {"status": "ok", "version": "0.1.0"}


@app.get("/api/config")
def config():
    c = settings()
    return {
        "mode": c.app_mode,
        "ai_available": bool(c.openai_api_key.get_secret_value()),
        "model": c.openai_model,
        "monthly_budget_eur": str(c.ai_monthly_budget_eur),
    }


@app.post("/api/demo-sessions")
def new_session(response: Response):
    identifier = service.create_session()
    response.set_cookie(
        "reconflow_session",
        identifier + "." + signature(identifier, "cookie"),
        max_age=86400,
        httponly=True,
        secure=settings().public_demo,
        samesite="lax",
        path="/",
    )
    return {"csrf_token": signature(identifier, "csrf")}


@app.get("/api/demo-sessions/current")
def current_session(s: Session):
    return {"csrf_token": signature(s, "csrf")}


@app.delete("/api/demo-sessions/current")
def delete_session(s: Session, response: Response):
    with transaction() as db:
        db.execute("DELETE FROM sessions WHERE id=:id", {"id": s})
    # S3 lifecycle expires files independently, even if the user closes the browser.
    response.delete_cookie("reconflow_session", path="/")
    return {"deleted": True}


@app.post("/api/demo-sessions/seed")
def seed(s: Session):
    return SafeJSON(service.seed(s))


@app.get("/api/workspace")
def workspace(s: Session):
    return SafeJSON(service.overview(s))


@app.get("/api/examples/{index}")
def example(index: int):
    if index < 0 or index >= len(fixtures.SPECS):
        raise LookupError("Beispiel nicht gefunden.")
    name, mime, content = fixtures.document(index)
    return Response(
        content, media_type=mime, headers={"Content-Disposition": f'attachment; filename="{name}"'}
    )


@app.get("/api/examples-payments")
def example_payments():
    return Response(
        fixtures.payment_csv(),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="zahlungen-beispiel.csv"'},
    )


@app.post("/api/documents")
async def upload(s: Session, file: UploadFile):
    content = await file.read(settings().max_upload_bytes + 1)
    return SafeJSON(
        await run_in_threadpool(service.upload_document, s, file.filename or "rechnung", content)
    )


@app.get("/api/documents/{identifier}/file")
def document_file(identifier: str, s: Session):
    with transaction() as db:
        row = db.one(
            "SELECT * FROM documents WHERE id=:id AND session_id=:session",
            {"id": identifier, "session": s},
        )
    if not row:
        raise LookupError("Dokument nicht gefunden.")
    return Response(
        storage.get(row["storage_key"]),
        media_type=row["mime"],
        headers={
            "Content-Disposition": 'inline; filename="rechnung"',
            "Content-Security-Policy": "sandbox",
        },
    )


@app.post("/api/documents/{identifier}/extract")
def extract(identifier: str, s: Session):
    with transaction() as db:
        if not db.one(
            "SELECT id FROM documents WHERE id=:id AND session_id=:session",
            {"id": identifier, "session": s},
        ):
            raise LookupError("Dokument nicht gefunden.")
    return SafeJSON(service.create_job(s, "extract", identifier))


class Confirmation(BaseModel):
    data: InvoiceData
    version: int


@app.put("/api/invoices/{identifier}")
def confirm(identifier: str, body: Confirmation, s: Session):
    return service.confirm_invoice(s, identifier, body.data, body.version)


@app.post("/api/imports/payments")
async def payments_import(s: Session, file: UploadFile):
    content = await file.read(settings().max_upload_bytes + 1)
    if len(content) > settings().max_upload_bytes:
        raise ValueError("Datei ist zu groß.")
    return await run_in_threadpool(service.import_payments, s, content)


@app.post("/api/imports/invoices")
async def invoices_import(s: Session, file: UploadFile):
    content = await file.read(settings().max_upload_bytes + 1)
    if len(content) > settings().max_upload_bytes:
        raise ValueError("Datei ist zu groß.")
    return await run_in_threadpool(service.import_invoices, s, content)


@app.get("/api/jobs/{identifier}")
def job(identifier: str, s: Session):
    with transaction() as db:
        db.execute(
            "UPDATE jobs SET status='failed',error='Verarbeitung unterbrochen. Ein begonnener KI-Aufruf wird nicht automatisch wiederholt.',finished_at=now() WHERE id=:id AND session_id=:session AND status='running' AND started_at<now()-interval '5 minutes'",
            {"id": identifier, "session": s},
        )
        row = db.one(
            "SELECT * FROM jobs WHERE id=:id AND session_id=:session",
            {"id": identifier, "session": s},
        )
    if not row:
        raise LookupError("Auftrag nicht gefunden.")
    if row["status"] == "pending":
        storage.enqueue(identifier)
    return SafeJSON(row)


@app.post("/api/jobs/{identifier}/retry")
def retry(identifier: str, s: Session):
    with transaction() as db:
        row = db.one(
            "SELECT * FROM jobs WHERE id=:id AND session_id=:session",
            {"id": identifier, "session": s},
        )
    if not row or row["status"] != "failed":
        raise ValueError(
            "Nur fehlgeschlagene Aufträge können ausdrücklich erneut gestartet werden."
        )
    return SafeJSON(service.create_job(s, row["kind"], row["target"], row["payload"], retry=True))


@app.post("/api/reconciliation-runs")
def reconcile(s: Session):
    with transaction() as db:
        invoices = db.execute(
            "SELECT id,version FROM invoices WHERE session_id=:session ORDER BY id", {"session": s}
        )
        payments = db.execute(
            "SELECT id FROM payments WHERE session_id=:session ORDER BY id", {"session": s}
        )
    if not invoices:
        raise ValueError("Bitte zuerst Rechnungen laden.")
    target = hashlib.sha256(dumps([invoices, payments]).encode()).hexdigest()
    return SafeJSON(service.create_job(s, "reconcile", target))


@app.get("/api/reconciliation-runs/{identifier}")
def get_run(identifier: str, s: Session):
    with transaction() as db:
        row = db.one(
            "SELECT * FROM runs WHERE id=:id AND session_id=:session",
            {"id": identifier, "session": s},
        )
    if not row:
        raise LookupError("Abgleich nicht gefunden.")
    return SafeJSON(row)


@app.post("/api/payments/{identifier}/suggest")
def suggest(identifier: str, s: Session):
    with transaction() as db:
        row = db.one(
            "SELECT * FROM payments WHERE id=:id AND session_id=:session",
            {"id": identifier, "session": s},
        )
        invoices = db.execute(
            "SELECT id,payload,version FROM invoices WHERE session_id=:session AND confirmed=TRUE ORDER BY id",
            {"session": s},
        )
    if not row:
        raise LookupError("Zahlung nicht gefunden.")
    candidates = [
        i
        for i in invoices
        if i["payload"]["currency"] == row["currency"]
        and i["payload"].get("gross_amount") == str(row["amount"])
    ]
    if not candidates or len(candidates) > 10:
        raise ValueError("Kein ausreichend eingegrenzter Kandidatenkreis. Bitte manuell prüfen.")
    key = hashlib.sha256(dumps([(i["id"], i["version"]) for i in candidates]).encode()).hexdigest()
    # target is the payment ID; the candidate snapshot is included in the job key.
    return SafeJSON(
        service.create_job(
            s, "suggest", identifier, {"candidates": [i["id"] for i in candidates], "snapshot": key}
        )
    )


class Decision(BaseModel):
    payment_id: str
    invoice_id: str
    invoice_version: int


@app.post("/api/reconciliation-decisions")
def decision(body: Decision, s: Session):
    with transaction() as db:
        row = db.one(
            "SELECT version FROM invoices WHERE id=:id AND session_id=:session",
            {"id": body.invoice_id, "session": s},
        )
    if not row or row["version"] != body.invoice_version:
        raise ValueError("Die Rechnung wurde geändert. Bitte erneut prüfen.")
    return SafeJSON(
        service.run_reconciliation(
            s, {body.payment_id: body.invoice_id}, {body.invoice_id: body.invoice_version}
        )
    )


@app.get("/api/reports/{identifier}.xlsx")
def report(identifier: str, s: Session):
    return Response(
        service.excel(s, identifier),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="ReconFlow-Abgleich.xlsx"'},
    )


@app.get("/api/ai-usage")
def usage(s: Session):
    # Return the session's own calls, not other applications or other visitors.
    with transaction() as db:
        rows = db.execute(
            "SELECT c.model,c.status,c.cost_eur,c.reserved_eur,c.input_tokens,c.output_tokens,c.created_at FROM ai_calls c JOIN jobs j ON j.id=c.job_id WHERE j.session_id=:session ORDER BY c.created_at DESC",
            {"session": s},
        )
    return SafeJSON({"calls": rows, "budget_eur": str(settings().ai_monthly_budget_eur)})


handler = Mangum(app, lifespan="off")
