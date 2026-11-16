import hmac
import re
from statistics import median
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from reconflow.benchmarks import objects, protocol, security, service
from reconflow.benchmarks.provider import VastProvider
from reconflow.config import settings
from reconflow.db import dumps, transaction

RUNNER_PATH = re.compile(
    r"^/api/benchmark-runner/[a-f0-9]{32}/(heartbeat|ready|poll|progress|complete|failed)$"
)
Key = Annotated[
    str, Header(alias="Idempotency-Key", min_length=8, max_length=100, pattern=r"^[a-zA-Z0-9_-]+$")
]


class Body(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LeaseBody(Body):
    offer_id: int = Field(gt=0)
    model: str = Field(max_length=80)
    mode: Literal["suite", "live"] = "suite"
    hourly_usd: str = Field(pattern=r"^\d{1,5}(\.\d{1,16})?$")


class PromptBody(Body):
    prompt_ids: list[Annotated[str, Field(max_length=30)]] | None = Field(
        default=None, min_length=1, max_length=5
    )
    custom_prompts: list[Annotated[str, Field(min_length=1, max_length=4000)]] | None = Field(
        default=None, min_length=1, max_length=5
    )


class LoginBody(Body):
    password: str = Field(min_length=1, max_length=256)


class ReadyBody(Body):
    gpu: str = Field(min_length=1, max_length=100)
    vram_total_mib: int = Field(gt=0, le=2000000)
    driver: str = Field(max_length=100)
    runtime_version: str = Field(max_length=100)
    model_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    quantization: str = Field(max_length=30)
    download_ms: float = Field(ge=0, le=600000, allow_inf_nan=False)
    load_ms: float = Field(ge=0, le=600000, allow_inf_nan=False)


class ProgressBody(Body):
    request_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    sequence: int = Field(ge=1, le=100000)
    sample: int = Field(ge=0, le=15)
    text: str = Field(max_length=16000)


class Sample(Body):
    index: int = Field(ge=0, le=15)
    output: str = Field(max_length=16000)
    elapsed_ms: float = Field(ge=0, le=121000, allow_inf_nan=False)
    ttft_ms: float | None = Field(default=None, ge=0, le=121000, allow_inf_nan=False)
    eval_count: int = Field(ge=0, le=512)
    eval_duration: int = Field(ge=0, le=121000000000)
    prompt_eval_count: int = Field(ge=0, le=4096)
    prompt_eval_duration: int = Field(ge=0, le=121000000000)
    prompt_eval_cached_count: int | None = Field(default=None, ge=0, le=4096)
    load_duration: int = Field(ge=0, le=121000000000)
    vram_peak_mib: int | None = Field(default=None, ge=0, le=2000000)
    gpu_utilization_peak: int | None = Field(default=None, ge=0, le=100)
    gpu_only: bool


class CompleteBody(Body):
    request_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    samples: list[Sample] = Field(min_length=1, max_length=16)


class FailureBody(Body):
    code: Literal["startup_failed", "inference_failed", "deadline", "connection_lost"]


class JSON(JSONResponse):
    def render(self, content):
        return dumps(content).encode()


def client_ip(request):
    # API Gateway context is injected by Mangum, never supplied by a client header.
    event = request.scope.get("aws.event", {})
    ip = event.get("requestContext", {}).get("http", {}).get("sourceIp")
    return ip or (request.client.host if request.client else "unknown")


def authenticate_runner(identifier: str, authorization: Annotated[str, Header()] = ""):
    expected = "Bearer " + security.token(identifier, "runner")
    if not re.fullmatch(r"[a-f0-9]{32}", identifier) or not hmac.compare_digest(
        authorization.encode(), expected.encode()
    ):
        raise HTTPException(401, "Ungültiges Runner-Token.")
    return identifier


Runner = Annotated[str, Depends(authenticate_runner)]


def runner_lease(db, identifier, finishing=False):
    row = db.one(
        "SELECT l.*, (s.id IS NULL OR s.expires_at<now()) AS session_expired FROM gpu_leases l LEFT JOIN sessions s ON s.id=l.session_id WHERE l.id=:id FOR UPDATE OF l",
        {"id": identifier},
    )
    if not row or row["session_expired"]:
        raise HTTPException(410, "GPU-Sitzung abgelaufen.")
    if not finishing and (
        row["status"] in service.TERMINAL | {"stopping"}
        or service.timestamp(row["deadline_at"]) <= service.now()
    ):
        raise HTTPException(410, "GPU-Sitzung beendet.")
    return row


def router(session_dependency):
    routes = APIRouter(prefix="/api/benchmarks", tags=["GPU benchmarks"])
    Session = Annotated[str, Depends(session_dependency)]

    @routes.get("/config")
    def config():
        return JSON(service.configuration())

    @routes.get("/offers")
    def offers(s: Session):
        if not settings().vast_api_key.get_secret_value():
            return {"offers": [], "available": False}
        try:
            found = VastProvider().offers()
        except Exception:
            raise HTTPException(503, "GPU-Angebote sind gerade nicht abrufbar.") from None
        for offer in found:
            estimate = protocol.estimate(offer, settings().gpu_max_minutes * 60, settings())
            offer["estimated_eur"] = str(estimate)
            offer["within_budget"] = estimate <= settings().gpu_session_budget_eur
        return {"offers": found, "available": True}

    @routes.get("/workspace")
    def workspace(s: Session):
        return JSON(service.workspace(s))

    @routes.post("/operator/login")
    def login(body: LoginBody, request: Request, s: Session):
        return service.login(s, body.password, client_ip(request))

    @routes.post("/operator/logout")
    def logout(s: Session):
        with transaction() as db:
            db.execute("UPDATE sessions SET operator_until=NULL WHERE id=:id", {"id": s})
        return {"operator": False}

    @routes.post("/leases", status_code=202)
    def create(body: LeaseBody, key: Key, request: Request, s: Session):
        return JSON(
            service.create_lease(
                s,
                client_ip(request),
                key,
                body.offer_id,
                body.model,
                body.mode,
                protocol.decimal(body.hourly_usd),
            ),
            status_code=202,
        )

    @routes.get("/leases/{identifier}")
    def lease(identifier: str, s: Session):
        return JSON(service.get_lease(s, identifier))

    @routes.post("/leases/{identifier}/stop", status_code=202)
    def stop(identifier: str, s: Session):
        return JSON(service.request_stop(s, identifier), status_code=202)

    @routes.post("/leases/{identifier}/requests", status_code=202)
    def prompt(identifier: str, body: PromptBody, key: Key, s: Session):
        if (body.prompt_ids is None) == (body.custom_prompts is None):
            raise ValueError("Entweder vorbereitete oder freie Prompts angeben.")
        return JSON(
            service.new_request(s, identifier, key, body.prompt_ids, body.custom_prompts),
            status_code=202,
        )

    @routes.get("/results")
    def results():
        return JSON({"results": service.results()})

    @routes.get("/results/{identifier}")
    def public_report(identifier: str):
        return JSON(service.report(identifier))

    @routes.get("/requests/{identifier}")
    def private_report(identifier: str, s: Session):
        return JSON(service.report(identifier, s))

    return routes


runner_router = APIRouter(prefix="/api/benchmark-runner", tags=["GPU runner"])


@runner_router.post("/{identifier}/heartbeat")
def heartbeat(identifier: Runner):
    with transaction() as db:
        runner_lease(db, identifier)
        db.execute("UPDATE gpu_leases SET heartbeat_at=now() WHERE id=:id", {"id": identifier})
    return {"ok": True}


@runner_router.post("/{identifier}/ready")
def ready(identifier: Runner, body: ReadyBody):
    with transaction() as db:
        lease = runner_lease(db, identifier)
        expected = protocol.MODELS[lease["model"]]

        def normalize(value):
            return re.sub(
                r"[^a-z0-9]", "", value.lower().replace("nvidia", "").replace("geforce", "")
            )

        if (
            body.model_digest != expected["digest"]
            or body.quantization != expected["quantization"]
            or normalize(body.gpu) != normalize(lease["offer"]["gpu"])
            or body.vram_total_mib < expected["min_vram_mib"]
        ):
            raise ValueError("GPU oder Modelldigest stimmt nicht mit der Bestellung überein.")
        if lease["status"] in {"ready", "busy"}:
            return {"ok": True}
        if lease["status"] not in {"creating", "starting", "unknown"}:
            raise ValueError("GPU noch nicht bestellt.")
        db.execute(
            "UPDATE gpu_leases SET status=:status,metadata=CAST(:metadata AS jsonb),heartbeat_at=now(),last_activity_at=now(),error=NULL WHERE id=:id",
            {
                "id": identifier,
                "metadata": body.model_dump_json(),
                "status": "busy" if lease["mode"] == "suite" else "ready",
            },
        )
        if lease["mode"] == "suite":
            service.insert_request(db, identifier, "standard-suite", protocol.suite(), True)
    return {"ok": True}


@runner_router.post("/{identifier}/poll")
def poll(identifier: Runner):
    with transaction() as db:
        lease = runner_lease(db, identifier)
        request = db.one(
            "SELECT * FROM gpu_requests WHERE lease_id=:id AND status='pending' ORDER BY created_at LIMIT 1 FOR UPDATE",
            {"id": identifier},
        )
        if not request:
            return {"request": None}
        db.execute(
            "UPDATE gpu_requests SET status='running',started_at=now() WHERE id=:id",
            {"id": request["id"]},
        )
    return {
        "request": {
            "id": request["id"],
            "prompts": request["prompts"],
            "options": protocol.OPTIONS,
            "model": lease["model"],
        }
    }


@runner_router.post("/{identifier}/progress")
def progress(identifier: Runner, body: ProgressBody):
    with transaction() as db:
        runner_lease(db, identifier)
        db.execute(
            "UPDATE gpu_requests SET progress=CAST(:progress AS jsonb),sequence=:seq WHERE id=:id AND lease_id=:lease AND status='running' AND sequence<:seq",
            {
                "id": body.request_id,
                "lease": identifier,
                "seq": body.sequence,
                "progress": dumps({"sample": body.sample, "text": body.text}),
            },
        )
    return {"ok": True}


@runner_router.post("/{identifier}/complete")
def complete(identifier: Runner, body: CompleteBody):
    with transaction() as db:
        lease = runner_lease(db, identifier, finishing=True)
        row = db.one(
            "SELECT * FROM gpu_requests WHERE id=:id AND lease_id=:lease FOR UPDATE",
            {"id": body.request_id, "lease": identifier},
        )
        if not row:
            raise LookupError("Auftrag nicht gefunden.")
        if row["status"] == "succeeded":
            return {"ok": True}
        if (
            row["status"] != "running"
            or lease["status"] != "busy"
            or service.timestamp(lease["deadline_at"]) <= service.now()
        ):
            raise ValueError("Auftrag bereits beendet oder abgelaufen.")
        if [s.index for s in body.samples] != list(range(len(row["prompts"]))):
            raise ValueError("Unvollständiger Messbericht.")
        samples = []
        for sample in body.samples:
            if row["public"] and (sample.eval_count == 0 or sample.eval_duration == 0):
                raise ValueError("Ein Standardbenchmark benötigt vollständige Tokenmessungen.")
            if sample.ttft_ms is not None and sample.ttft_ms > sample.elapsed_ms:
                raise ValueError("Ungültige Zeitmessung.")
            samples.append(
                {
                    **sample.model_dump(),
                    "warmup": bool(row["prompts"][sample.index].get("warmup")),
                    "tokens_per_second": sample.eval_count * 1e9 / sample.eval_duration
                    if sample.eval_duration
                    else None,
                }
            )
        measured = [s for s in samples if not s["warmup"] and s["tokens_per_second"] is not None]
        speeds = [s["tokens_per_second"] for s in measured]
        first_tokens = [s["ttft_ms"] for s in measured if s["ttft_ms"] is not None]
        memory = [s["vram_peak_mib"] for s in measured if s["vram_peak_mib"] is not None]
        result = {
            "protocol": row["protocol"],
            "options": protocol.OPTIONS,
            "model": lease["model"],
            "metadata": lease["metadata"],
            "samples": samples,
            "summary": {
                "count": len(speeds),
                "median_tokens_per_second": median(speeds) if speeds else None,
                "min_tokens_per_second": min(speeds) if speeds else None,
                "max_tokens_per_second": max(speeds) if speeds else None,
                "gpu_only": all(s["gpu_only"] for s in samples),
                "median_ttft_ms": median(first_tokens) if first_tokens else None,
                "median_elapsed_ms": median([s["elapsed_ms"] for s in measured])
                if measured
                else None,
                "peak_vram_mib": max(memory) if memory else None,
            },
        }
        if row["public"]:
            objects.put("reports/" + row["id"] + ".json", result)
        db.execute(
            "UPDATE gpu_requests SET status='succeeded',result=CAST(:result AS jsonb),progress='{}',finished_at=now() WHERE id=:id",
            {"id": row["id"], "result": dumps(result)},
        )
        db.execute(
            "UPDATE gpu_leases SET status=:status,last_activity_at=now() WHERE id=:id",
            {"id": identifier, "status": "stopping" if lease["mode"] == "suite" else "ready"},
        )
    return {"ok": True}


@runner_router.post("/{identifier}/failed")
def failed(identifier: Runner, body: FailureBody):
    with transaction() as db:
        runner_lease(db, identifier, finishing=True)
        db.execute(
            "UPDATE gpu_leases SET status='stopping',error=:error WHERE id=:id AND status NOT IN ('destroyed','failed')",
            {"id": identifier, "error": "Runner: " + body.code},
        )
        db.execute(
            "UPDATE gpu_requests SET status='failed',error=:error,finished_at=now() WHERE lease_id=:id AND status IN ('running','pending')",
            {"id": identifier, "error": "Runner: " + body.code},
        )
    return {"ok": True}
