import io
from datetime import timedelta
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient
from reconflow.api import app
from reconflow.benchmarks import lifecycle, protocol, runner, security, service
from reconflow.config import settings
from reconflow.db import transaction
from test_benchmarks import MODEL, OFFER, rent
from test_benchmarks import gpu as gpu_fixture

gpu = gpu_fixture


@pytest.fixture
def objects(monkeypatch):
    data = {}
    monkeypatch.setattr(lifecycle.objects, "put", lambda key, value: data.update({key: value}))
    monkeypatch.setattr(lifecycle.objects, "get", lambda key: data.get(key))
    monkeypatch.setattr(lifecycle.objects, "remove", lambda key: data.pop(key, None))
    monkeypatch.setattr(
        lifecycle.objects,
        "controls",
        lambda: [
            k.split("/")[1].removesuffix(".json") for k in list(data) if k.startswith("control/")
        ],
    )
    monkeypatch.setattr(
        lifecycle.objects, "artifact_url", lambda: "https://synthetic.example/runner.zip"
    )
    data["watchdog.json"] = {"healthy": True, "at": service.now().isoformat()}
    return data


@pytest.fixture
def provider(monkeypatch):
    fake = Mock()
    fake.offers.return_value = [dict(OFFER)]
    fake.create.return_value = {"success": True, "new_contract": 123}
    fake.instances.return_value = []
    monkeypatch.setattr(lifecycle, "VastProvider", lambda: fake)
    return fake


def row(identifier):
    with transaction() as db:
        return db.one("SELECT * FROM gpu_leases WHERE id=:id", {"id": identifier})


@pytest.mark.integration
def test_ambiguous_rental_is_reconciled_and_never_repeated(gpu, objects, provider):
    lease = rent(gpu)
    provider.create.side_effect = TimeoutError()
    lifecycle.process(lease["id"])
    lifecycle.process(lease["id"])
    assert provider.create.call_count == 1
    assert row(lease["id"])["status"] == "unknown"
    provider.instances.return_value = [{"id": 123, "label": row(lease["id"])["label"]}]
    lifecycle.sweep(provider)
    assert row(lease["id"])["status"] == "starting"
    assert row(lease["id"])["instance_id"] == 123


@pytest.mark.integration
def test_watchdog_destroys_without_database_and_ignores_foreign_instances(
    gpu, objects, provider, monkeypatch
):
    lease = rent(gpu)
    label = row(lease["id"])["label"]
    provider.instances.return_value = [
        {"id": 123, "label": label},
        {"id": 999, "label": "someone-elses-gpu"},
    ]
    monkeypatch.setattr(
        lifecycle, "transaction", Mock(side_effect=RuntimeError("database offline"))
    )
    with pytest.raises(RuntimeError, match="cleanup required"):
        lifecycle.sweep(provider)
    provider.destroy.assert_called_once_with(123)
    assert objects["watchdog.json"]["healthy"] is False


@pytest.mark.integration
def test_idle_cleanup_debits_only_after_repeated_absence(gpu, objects, provider, monkeypatch):
    lease = rent(gpu)
    lifecycle.process(lease["id"])
    with transaction() as db:
        db.execute(
            "UPDATE gpu_leases SET status='ready',heartbeat_at=now(),last_activity_at=now()-interval '6 minutes' WHERE id=:id",
            {"id": lease["id"]},
        )
    provider.instances.return_value = [{"id": 123, "label": row(lease["id"])["label"]}]
    objects["control/" + lease["id"] + ".json"] = {"id": lease["id"]}
    lifecycle.sweep(provider)
    provider.destroy.assert_called_once_with(123)
    assert row(lease["id"])["status"] == "stopping"
    assert row(lease["id"])["debited_eur"] is None
    provider.instances.return_value = []
    current = service.now()
    for minute in range(3):
        monkeypatch.setattr(
            service, "now", lambda minute=minute: current + timedelta(minutes=minute)
        )
        lifecycle.sweep(provider)
    assert row(lease["id"])["status"] == "destroyed"
    assert row(lease["id"])["debited_eur"] == row(lease["id"])["reserved_eur"]
    assert "control/" + lease["id"] + ".json" not in objects


def test_idle_watchdog_does_not_wake_database(objects, provider, monkeypatch):
    db = Mock(side_effect=AssertionError("must not access SQL"))
    monkeypatch.setattr(lifecycle, "transaction", db)
    assert lifecycle.sweep(provider) == {"checked": 0}
    db.assert_not_called()


@pytest.mark.integration
def test_ready_claim_progress_and_completion_are_scoped_and_idempotent(
    gpu, objects, provider, monkeypatch
):
    monkeypatch.setattr(settings(), "app_mode", "demo")
    lease = rent(gpu, mode="suite")
    lifecycle.process(lease["id"])
    url = "/api/benchmark-runner/" + lease["id"]
    auth = {"Authorization": "Bearer " + security.token(lease["id"], "runner")}
    metadata = {
        "gpu": OFFER["gpu"],
        "vram_total_mib": 16384,
        "driver": "test",
        "runtime_version": "test",
        "model_digest": protocol.MODELS[MODEL]["digest"],
        "quantization": "Q4_K_M",
        "download_ms": 100,
        "load_ms": 10,
    }
    with TestClient(app) as client:
        assert client.post("/api/benchmarks/leases", json={}).status_code == 403
        assert client.post(url + "/ready", json=metadata).status_code == 401
        assert (
            client.post(
                url + "/ready", headers=auth, json={**metadata, "model_digest": "f" * 64}
            ).status_code
            == 422
        )
        assert client.post(url + "/ready", headers=auth, json=metadata).status_code == 200
        assert client.post(url + "/ready", headers=auth, json=metadata).status_code == 200
        job = client.post(url + "/poll", headers=auth, json={}).json()["request"]
        assert len(job["prompts"]) == 16
        assert client.post(url + "/poll", headers=auth, json={}).json()["request"] is None
        for seq, text in [(2, "new"), (1, "stale")]:
            response = client.post(
                url + "/progress",
                headers=auth,
                json={"request_id": job["id"], "sequence": seq, "sample": 0, "text": text},
            )
            assert response.status_code == 200
        assert service.workspace(gpu)["requests"][0]["progress"]["text"] == "new"
        samples = [
            {
                "index": i,
                "output": "synthetic test adapter output",
                "elapsed_ms": 100,
                "ttft_ms": 20,
                "eval_count": 10,
                "eval_duration": 50000000,
                "prompt_eval_count": 12,
                "prompt_eval_duration": 10000000,
                "load_duration": 0,
                "gpu_only": True,
            }
            for i in range(16)
        ]
        body = {"request_id": job["id"], "samples": samples}
        assert (
            client.post(
                url + "/complete", headers=auth, json={**body, "samples": samples[:1]}
            ).status_code
            == 422
        )
        assert client.post(url + "/complete", headers=auth, json=body).status_code == 200
        assert client.post(url + "/complete", headers=auth, json=body).status_code == 200
    assert row(lease["id"])["status"] == "stopping"
    result = next(r for r in service.results() if r["id"] == job["id"])["result"]
    assert result["summary"]["count"] == 15
    assert result["summary"]["median_tokens_per_second"] == 200
    assert "samples" not in result
    assert service.report(job["id"])["result"]["samples"][0]["vram_peak_mib"] is None
    assert "reports/" + job["id"] + ".json" in objects
    with transaction() as db:
        db.execute("UPDATE gpu_requests SET public=FALSE WHERE id=:id", {"id": job["id"]})
    with pytest.raises(LookupError):
        service.report(job["id"])
    with pytest.raises(LookupError):
        service.report(job["id"], "foreign-session")
    assert service.report(job["id"], gpu)["result"]["summary"]["count"] == 15


def test_stream_metrics_use_actual_token_counters(monkeypatch):
    monkeypatch.setenv("RF_REQUEST_SECONDS", "120")
    control = Mock(deadline=9999999999, sequence=0)
    lines = b'{"response":"Hello","done":false}\n{"done":true,"eval_count":1,"eval_duration":1000000,"prompt_eval_count":3,"prompt_eval_duration":2000000,"load_duration":0}\n'
    monkeypatch.setattr(runner, "request_json", lambda *a, **kw: io.BytesIO(lines))
    monkeypatch.setattr(
        runner, "ollama", lambda *_: {"models": [{"name": MODEL, "size": 10, "size_vram": 10}]}
    )
    monkeypatch.setattr(runner.Telemetry, "sample", lambda _: None)
    result = runner.generate(
        control, {"id": "test", "model": MODEL, "options": protocol.OPTIONS}, {"text": "fixture"}, 0
    )
    assert result["output"] == "Hello"
    assert result["eval_count"] == 1
    assert result["ttft_ms"] is not None
    assert result["gpu_only"] is True
    assert result["vram_peak_mib"] is None
