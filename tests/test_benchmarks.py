import json
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from unittest.mock import Mock

import pytest
import requests
from pydantic import SecretStr
from reconflow import service as invoices
from reconflow.benchmarks import protocol, security, service
from reconflow.benchmarks.provider import SingleAttemptClient, VastProvider
from reconflow.config import Settings, settings
from reconflow.db import transaction
from reconflow.migrate import migrate

OFFER = {
    "id": 42,
    "gpu": "TEST GPU",
    "vram_mib": 16384,
    "num_gpus": 1,
    "hourly_usd": "0.20",
    "storage_usd_gb_month": "0.10",
    "download_usd_gb": "0",
    "upload_usd_gb": "0",
}
MODEL = next(iter(protocol.MODELS))


def test_cost_includes_cleanup_time_and_transfers():
    c = Settings(_env_file=None)
    offer = {**OFFER, "download_usd_gb": "0.01", "upload_usd_gb": "0.02"}
    assert protocol.estimate(offer, 1800, c) == Decimal("0.41433333")
    for bad in ["NaN", "Infinity", "-1"]:
        with pytest.raises(ValueError):
            protocol.decimal(bad)


def test_protocol_is_fixed_and_unknown_fixtures_are_rejected():
    assert len(protocol.suite()) == 16
    assert protocol.suite()[0]["warmup"]
    assert protocol.OPTIONS["num_predict"] == 512
    with pytest.raises(ValueError):
        protocol.workload(["injected"])


def test_provider_preserves_decimal_and_never_retries_or_redirects(monkeypatch):
    response = requests.Response()
    response.status_code = 200
    response._content = b'{"price":0.1234567890123456789}'
    session = Mock()
    session.request.return_value = response
    wrapper = Mock()
    wrapper.__enter__ = Mock(return_value=session)
    wrapper.__exit__ = Mock(return_value=False)
    monkeypatch.setattr(requests, "Session", lambda: wrapper)
    client = SingleAttemptClient("synthetic", "https://console.vast.ai", retry=99)
    result = client.put("/asks/42", json_data={})
    assert result.json()["price"] == Decimal("0.1234567890123456789")
    assert session.request.call_count == 1
    assert session.request.call_args.kwargs["allow_redirects"] is False
    session.request.side_effect = requests.Timeout()
    with pytest.raises(requests.Timeout):
        client.put("/asks/42", json_data={})
    assert session.request.call_count == 2


def test_missing_provider_prices_fail_closed():
    with pytest.raises(KeyError):
        VastProvider.normalize({"id": 42, "gpu_name": "TEST", "gpu_ram": 16384, "num_gpus": 1})


@pytest.fixture
def gpu(monkeypatch):
    c = settings()
    monkeypatch.setattr(c, "benchmarks_enabled", True)
    monkeypatch.setattr(c, "aws_endpoint_url", None)
    monkeypatch.setattr(c, "public_origin", "https://synthetic.example")
    monkeypatch.setattr(c, "vast_api_key", SecretStr("synthetic-only"))
    monkeypatch.setattr(c, "gpu_runner_image", "example/runner@sha256:" + "a" * 64)
    monkeypatch.setattr(c, "gpu_runner_artifact_key", "benchmarks/artifacts/test.tgz")
    monkeypatch.setattr(c, "gpu_runner_artifact_sha256", "b" * 64)
    migrate()
    with transaction() as db:
        original = {r["id"] for r in db.execute("SELECT id FROM gpu_leases")}
    monkeypatch.setattr(service, "VastProvider", lambda: Mock(offers=lambda *_: [dict(OFFER)]))
    monkeypatch.setattr(service, "dispatch", Mock())
    monkeypatch.setattr(
        service.objects, "get", lambda _: {"healthy": True, "at": service.now().isoformat()}
    )
    session = invoices.create_session()
    yield session
    with transaction() as db:
        for row in db.execute("SELECT * FROM gpu_leases"):
            if row["id"] in original:
                continue
            db.execute("DELETE FROM gpu_events WHERE lease_id=:id", {"id": row["id"]})
            db.execute("DELETE FROM gpu_requests WHERE lease_id=:id", {"id": row["id"]})
            db.execute("DELETE FROM gpu_leases WHERE id=:id", {"id": row["id"]})
            if row["debited_eur"] is None:
                db.execute(
                    "UPDATE gpu_months SET reserved_eur=reserved_eur-:amount WHERE month=:month",
                    {"amount": row["reserved_eur"], "month": row["month"]},
                )
            else:
                db.execute(
                    "UPDATE gpu_months SET debited_eur=debited_eur-:amount WHERE month=:month",
                    {"amount": row["debited_eur"], "month": row["month"]},
                )
        db.execute("DELETE FROM sessions WHERE id=:id", {"id": session})
        db.execute(
            "DELETE FROM gpu_rate_limits WHERE key LIKE :rent OR key LIKE :login",
            {"rent": "rent:%", "login": "login:%"},
        )


def test_provider_inventory_paginates_without_float_conversion():
    provider = object.__new__(VastProvider)
    provider.sdk = Mock()
    provider.sdk.show_instances_v1.side_effect = [
        {"instances": [{"id": 1, "dph_total": Decimal("0.21")}], "next_token": "next"},
        {"instances": [{"id": 2, "dph_total": Decimal("0.22")}], "next_token": None},
    ]
    assert [i["id"] for i in provider.instances()] == [1, 2]
    provider.sdk.show_instances.assert_not_called()


def rent(session, key="test-key", mode="live"):
    return service.create_lease(session, "synthetic-ip", key, 42, MODEL, mode, Decimal("0.20"))


@pytest.mark.integration
def test_atomic_admission_and_idempotency(gpu):
    with ThreadPoolExecutor(max_workers=2) as pool:
        rows = list(pool.map(lambda _: rent(gpu), range(2)))
    assert rows[0]["id"] == rows[1]["id"]
    with transaction() as db:
        assert (
            int(db.one("SELECT count(*) AS n FROM gpu_leases WHERE session_id=:s", {"s": gpu})["n"])
            == 1
        )
    with pytest.raises(ValueError, match="belegt"):
        rent(gpu, "different-key")
    with pytest.raises(ValueError, match="anderen Auswahl"):
        rent(gpu, mode="suite")


@pytest.mark.integration
def test_disabled_stale_watchdog_changed_price_and_budget_prevent_rental(gpu, monkeypatch):
    monkeypatch.setattr(settings(), "benchmarks_enabled", False)
    with pytest.raises(ValueError, match="freigeschaltet"):
        rent(gpu)
    monkeypatch.setattr(settings(), "benchmarks_enabled", True)
    monkeypatch.setattr(service.objects, "get", lambda _: None)
    with pytest.raises(ValueError, match="Freigabe"):
        rent(gpu)
    monkeypatch.setattr(
        service.objects, "get", lambda _: {"healthy": True, "at": service.now().isoformat()}
    )
    with pytest.raises(ValueError, match="Preis"):
        service.create_lease(gpu, "ip", "key", 42, MODEL, "live", Decimal("0.1"))
    monkeypatch.setattr(settings(), "gpu_session_budget_eur", Decimal("0.01"))
    with pytest.raises(ValueError, match="Sitzungsbudget"):
        rent(gpu)
    service.dispatch.assert_not_called()


@pytest.mark.integration
def test_signed_labels_and_private_prompt_access(gpu):
    lease = rent(gpu)
    with transaction() as db:
        row = db.one("SELECT label FROM gpu_leases WHERE id=:id", {"id": lease["id"]})
        db.execute("UPDATE gpu_leases SET status='ready' WHERE id=:id", {"id": lease["id"]})
    assert security.parse_label(row["label"])[0] == lease["id"]
    assert security.parse_label(row["label"][:-1] + "x") is None
    with pytest.raises(PermissionError):
        service.new_request(gpu, lease["id"], "private", None, ["free text"])
    request = service.new_request(gpu, lease["id"], "public", ["explain"], None)
    assert service.new_request(gpu, lease["id"], "public", ["explain"], None) == request
    with pytest.raises(LookupError):
        service.get_lease("other-session", lease["id"])
    assert service.workspace(gpu)["leases"][0]["id"] == lease["id"]


@pytest.mark.integration
def test_login_limits_survive_failed_authentication(gpu, monkeypatch):
    monkeypatch.setattr(settings(), "benchmark_operator_password", SecretStr("x" * 32))
    for _ in range(5):
        with pytest.raises(PermissionError):
            service.login(gpu, "wrong", "test-ip")
    with pytest.raises(PermissionError):
        service.login(gpu, "x" * 32, "test-ip")
    assert service.login(gpu, "x" * 32, "different-ip")["operator"]


@pytest.mark.integration
def test_private_data_is_scrubbed_before_session_delete(gpu):
    lease = rent(gpu)
    with transaction() as db:
        req = service.insert_request(db, lease["id"], "private", [{"text": "secret"}], False)
        service.scrub_sessions(db, gpu)
        db.execute("DELETE FROM sessions WHERE id=:id", {"id": gpu})
        assert db.one("SELECT prompts FROM gpu_requests WHERE id=:id", {"id": req})["prompts"] == []
        row = db.one("SELECT * FROM gpu_leases WHERE id=:id", {"id": lease["id"]})
    assert row["status"] == "stopping"
    assert row["session_id"] is None
    assert "secret" not in json.dumps(service.results())
