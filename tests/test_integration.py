import io
import uuid
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from openpyxl import load_workbook
from pydantic import SecretStr
from reconflow import ai, fixtures
from reconflow.api import app
from reconflow.config import settings
from reconflow.db import transaction
from reconflow.migrate import migrate
from reconflow.worker import process

pytestmark = pytest.mark.integration


@pytest.fixture
def client():
    with TestClient(app) as client:
        response = client.post("/api/demo-sessions")
        assert response.status_code == 200, response.text
        client.headers["x-csrf-token"] = response.json()["csrf_token"]
        yield client
        client.delete("/api/demo-sessions/current")


def seeded(client):
    response = client.post("/api/demo-sessions/seed")
    assert response.status_code == 200, response.text
    return response.json()


def test_migrations_repeat_safely():
    migrate()
    migrate()


def test_local_bootstrap_repeat_safely():
    from reconflow.bootstrap import bootstrap

    bootstrap()
    bootstrap()


def test_local_document_survives_emulator_object_loss(client, tmp_path, monkeypatch):
    from reconflow import storage

    monkeypatch.setattr(settings(), "local_document_root", str(tmp_path))
    content = fixtures.document(0)[2]
    key = "sessions/test-restart/document"
    storage.put(key, content, "application/pdf")
    storage.client("s3").delete_object(Bucket=settings().s3_bucket, Key=key)
    assert storage.get(key) == content


def test_public_demo_rejects_non_fixture_files(client, monkeypatch):
    seeded(client)
    monkeypatch.setattr(settings(), "app_mode", "demo")
    client.headers["Origin"] = settings().public_origin
    allowed = client.post(
        "/api/documents",
        files={"file": ("example.pdf", fixtures.document(0)[2], "application/pdf")},
    )
    assert allowed.status_code == 200
    rejected = client.post(
        "/api/documents",
        files={"file": ("other.pdf", fixtures.document(0)[2] + b"\n", "application/pdf")},
    )
    assert rejected.status_code == 422


def test_stale_run_and_atomic_decision_version(client):
    from reconflow import service

    workspace = seeded(client)
    job = client.post("/api/reconciliation-runs").json()
    process(job["id"])
    assert client.get("/api/workspace").json()["run"]["stale"] is False
    row = workspace["invoices"][0]
    assert (
        client.put(
            "/api/invoices/" + row["id"], json={"data": row["payload"], "version": row["version"]}
        ).status_code
        == 200
    )
    assert client.get("/api/workspace").json()["run"]["stale"] is True
    session = client.cookies.get("reconflow_session").split(".")[0]
    with pytest.raises(ValueError, match="geändert"):
        service.run_reconciliation(session, {}, {row["id"]: row["version"]})


def test_end_to_end_seed_match_export(client):
    workspace = seeded(client)
    assert len(workspace["invoices"]) == 6
    job = client.post("/api/reconciliation-runs").json()
    process(job["id"])
    result = client.get("/api/jobs/" + job["id"]).json()
    assert result["status"] == "succeeded", result
    workspace = client.get("/api/workspace").json()
    statuses = [r["status"] for r in workspace["run"]["payload"]["results"]]
    assert statuses.count("MATCHED") == 2
    assert "PARTIAL" in statuses and "DUPLICATE" in statuses and "REVIEW" in statuses
    response = client.get("/api/reports/" + workspace["run"]["id"] + ".xlsx")
    assert response.status_code == 200
    workbook = load_workbook(io.BytesIO(response.content))
    assert workbook.sheetnames == ["Abgleich", "Rechnungen", "Zahlungen", "Importe"]


def test_session_isolation_and_csrf(client):
    workspace = seeded(client)
    doc = workspace["documents"][0]["id"]
    with TestClient(app) as other:
        token = other.post("/api/demo-sessions").json()["csrf_token"]
        other.headers["x-csrf-token"] = token
        assert other.get("/api/documents/" + doc + "/file").status_code == 404
        assert other.post("/api/documents/" + doc + "/extract").status_code == 404
        assert other.get("/api/workspace").json()["invoices"] == []
        other.headers.pop("x-csrf-token")
        assert other.post("/api/demo-sessions/seed").status_code == 403
        other.headers["x-csrf-token"] = token
        other.delete("/api/demo-sessions/current")
    assert (
        client.post(
            "/api/demo-sessions/seed", headers={"Origin": "https://attacker.example"}
        ).status_code
        == 403
    )


def test_import_idempotency_and_atomic_validation(client):
    seeded(client)
    response = client.post(
        "/api/imports/payments",
        files={"file": ("payments.csv", fixtures.payment_csv(), "text/csv")},
    )
    assert response.json()["duplicates"] == 6
    invalid = b"payment_id,reference,amount,currency,paid_at,payer\nNEW,A,100,EUR,2026-11-02,A\nBAD,B,NaN,EUR,2026-11-02,B\n"
    response = client.post(
        "/api/imports/payments", files={"file": ("bad.csv", invalid, "text/csv")}
    )
    assert response.json()["inserted"] == 0
    assert len(client.get("/api/workspace").json()["payments"]) == 6


def test_upload_dedup_and_validation(client):
    name, mime, content = fixtures.document(0)
    first = client.post("/api/documents", files={"file": (name, content, mime)}).json()
    again = client.post("/api/documents", files={"file": (name, content, mime)}).json()
    assert again["id"] == first["id"] and again["duplicate"]
    assert (
        client.post(
            "/api/documents", files={"file": ("bad.pdf", b"not a PDF", "application/pdf")}
        ).status_code
        == 422
    )


def test_extraction_keeps_review_and_worker_deduplicates(client, monkeypatch):
    workspace = seeded(client)
    invoice = workspace["invoices"][0]
    calls = []

    def extract(*args):
        calls.append(args[0])
        return fixtures.invoice_data(0)

    monkeypatch.setattr(ai, "extract", extract)
    job = client.post("/api/documents/" + invoice["document_id"] + "/extract").json()
    process(job["id"])
    process(job["id"])
    assert len(calls) == 1
    after = next(
        i for i in client.get("/api/workspace").json()["invoices"] if i["id"] == invoice["id"]
    )
    assert not after["confirmed"] and after["source"] == "openai"
    assert (
        client.put(
            "/api/invoices/" + after["id"],
            json={"data": after["payload"], "version": after["version"]},
        ).status_code
        == 200
    )
    assert (
        client.put(
            "/api/invoices/" + after["id"],
            json={"data": after["payload"], "version": after["version"]},
        ).status_code
        == 422
    )


def test_unknown_ai_outcome_is_not_automatically_retried(client, monkeypatch):
    workspace = seeded(client)
    calls = []

    def fail(*args):
        calls.append(1)
        raise ValueError("Unvollständige KI-Antwort")

    monkeypatch.setattr(ai, "extract", fail)
    job = client.post("/api/documents/" + workspace["documents"][0]["id"] + "/extract").json()
    process(job["id"])
    process(job["id"])
    assert calls == [1]
    assert client.get("/api/jobs/" + job["id"]).json()["status"] == "failed"


def test_manual_assignment_and_export_staleness(client):
    workspace = seeded(client)
    invoice = next(
        i for i in workspace["invoices"] if i["payload"]["customer"] == "Mira Kunsthandel"
    )
    payment = next(p for p in workspace["payments"] if p["payer"] == "Mira Kunsthandel")
    response = client.post(
        "/api/reconciliation-decisions",
        json={
            "invoice_id": invoice["id"],
            "payment_id": payment["id"],
            "invoice_version": invoice["version"],
        },
    )
    assert response.status_code == 200, response.text
    run = response.json()
    assert (
        next(r for r in run["payload"]["results"] if r["invoice_id"] == invoice["id"])["status"]
        == "MATCHED"
    )
    edited = {**invoice["payload"], "customer": '=HYPERLINK("https://example.com")'}
    assert (
        client.put(
            "/api/invoices/" + invoice["id"], json={"data": edited, "version": invoice["version"]}
        ).status_code
        == 200
    )
    assert client.get("/api/reports/" + run["id"] + ".xlsx").status_code == 422
    job = client.post("/api/reconciliation-runs").json()
    process(job["id"])
    latest = client.get("/api/workspace").json()["run"]
    response = client.get("/api/reports/" + latest["id"] + ".xlsx")
    wb = load_workbook(io.BytesIO(response.content))
    cells = [
        c
        for row in wb["Rechnungen"]
        for c in row
        if isinstance(c.value, str) and c.value.startswith("=")
    ]
    assert cells and all(c.data_type == "s" for c in cells)


def test_budget_reservation_is_atomic(monkeypatch):
    month = "test-" + str(uuid.uuid4())
    monkeypatch.setattr(ai, "period", lambda: month)
    monkeypatch.setattr(settings(), "ai_monthly_budget_eur", Decimal("0.25"))
    monkeypatch.setattr(settings(), "openai_api_key", SecretStr("not-a-real-key"))
    monkeypatch.setattr(settings(), "ai_context_token_ceiling", 1050000)

    def reserve(_):
        try:
            ai.reserve("test-" + str(uuid.uuid4()))
            return True
        except ai.BudgetExceeded:
            return False

    try:
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(reserve, range(4)))
        assert sum(results) == 1
        with transaction() as db:
            row = db.one("SELECT * FROM ai_months WHERE month=:month", {"month": month})
            assert Decimal(row["reserved_eur"]) <= Decimal("0.25")
    finally:
        with transaction() as db:
            db.execute("DELETE FROM ai_calls WHERE month=:month", {"month": month})
            db.execute("DELETE FROM ai_months WHERE month=:month", {"month": month})
