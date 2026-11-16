import hmac
import re
import uuid
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from reconflow import service as invoices
from reconflow import storage
from reconflow.benchmarks import objects, protocol, security
from reconflow.benchmarks.provider import VastProvider
from reconflow.config import settings
from reconflow.db import dumps, transaction

TERMINAL = {"destroyed", "failed"}


def now():
    return datetime.now(UTC)


def timestamp(value):
    parsed = (
        value if isinstance(value, datetime) else datetime.fromisoformat(value.replace(" ", "T"))
    )
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def event(db, lease_id, action):
    db.execute(
        "INSERT INTO gpu_events(lease_id,action) VALUES (:id,:action)",
        {"id": lease_id, "action": action},
    )


def configuration():
    c = settings()
    return {
        "enabled": c.benchmarks_enabled,
        "configured": configured(),
        "models": [{"id": k, **v} for k, v in protocol.MODELS.items()],
        "prompts": protocol.PROMPTS,
        "protocol": protocol.PROTOCOL,
        "monthly_budget_eur": str(c.gpu_monthly_budget_eur),
        "session_budget_eur": str(c.gpu_session_budget_eur),
        "max_minutes": c.gpu_max_minutes,
        "idle_seconds": c.gpu_idle_seconds,
    }


def configured():
    c = settings()
    return bool(
        c.vast_api_key.get_secret_value()
        and re.fullmatch(r"[\w./:-]+@sha256:[a-f0-9]{64}", c.gpu_runner_image)
        and c.gpu_runner_artifact_key.startswith("benchmarks/artifacts/")
        and re.fullmatch(r"[a-f0-9]{64}", c.gpu_runner_artifact_sha256)
    )


def admission():
    c = settings()
    if not c.benchmarks_enabled or not configured():
        raise ValueError("GPU-Mieten sind noch nicht freigeschaltet.")
    if c.aws_endpoint_url or not c.public_origin.startswith("https://"):
        raise ValueError(
            "Echte GPU-Mieten benötigen das bereitgestellte HTTPS-Backend und privates AWS S3."
        )
    if not (
        0 < c.gpu_session_budget_eur <= c.gpu_monthly_budget_eur
        and 1 <= c.gpu_max_minutes <= 30
        and c.gpu_usd_to_eur >= 1
    ):
        raise ValueError("Ungültige GPU-Budgetkonfiguration.")
    health = objects.get("watchdog.json")
    if (
        not health
        or not health.get("healthy")
        or not 0 <= (now() - timestamp(health["at"])).total_seconds() < 150
    ):
        raise ValueError(
            "Die automatische GPU-Freigabe ist derzeit nicht bestätigt. Neue Mieten sind gesperrt."
        )


def operator(db, session):
    return bool(
        db.one(
            "SELECT id FROM sessions WHERE id=:id AND expires_at>now() AND operator_until>now()",
            {"id": session},
        )
    )


def rate(db, key, limit, seconds):
    row = db.one(
        "INSERT INTO gpu_rate_limits(key,count,expires_at) VALUES (:key,1,now()+:seconds*interval '1 second') ON CONFLICT(key) DO UPDATE SET count=CASE WHEN gpu_rate_limits.expires_at<now() THEN 1 ELSE gpu_rate_limits.count+1 END, expires_at=CASE WHEN gpu_rate_limits.expires_at<now() THEN excluded.expires_at ELSE gpu_rate_limits.expires_at END RETURNING count",
        {"key": key, "seconds": seconds},
    )
    return int(row["count"]) <= limit


def login(session, password, ip):
    # Commit the attempt even when authentication fails.
    with transaction() as db:
        allowed = rate(db, "login:" + security.token(ip, "ip"), 5, 900)
        expected = settings().benchmark_operator_password.get_secret_value()
        valid = (
            allowed
            and len(expected) >= 32
            and hmac.compare_digest(password.encode(), expected.encode())
        )
        if valid:
            db.execute(
                "UPDATE sessions SET operator_until=now()+interval '1 hour' WHERE id=:id",
                {"id": session},
            )
    if not valid:
        raise PermissionError("Anmeldung nicht möglich oder Versuchslimit erreicht.")
    return {"operator": True}


def dispatch(lease_id):
    objects.put("control/" + lease_id + ".json", {"id": lease_id, "created_at": now().isoformat()})
    storage.client("sqs").send_message(
        QueueUrl=settings().sqs_queue_url, MessageBody=dumps({"benchmark_lease_id": lease_id})
    )


def create_lease(session, ip, key, offer_id, model, mode, expected_hourly):
    payload_hash = protocol.fingerprint(dumps([offer_id, model, mode, str(expected_hourly)]))
    with transaction() as db:
        existing = db.one(
            "SELECT * FROM gpu_leases WHERE session_id=:session AND request_key=:key",
            {"session": session, "key": key},
        )
    if existing:
        if existing["request_hash"] != payload_hash:
            raise ValueError("Dieser Anfrageschlüssel gehört zu einer anderen Auswahl.")
        if existing["status"] == "queued":
            dispatch(existing["id"])
        return public_lease(existing)
    admission()
    offers = VastProvider().offers(offer_id)
    offer = next((o for o in offers if o["id"] == offer_id), None)
    if (
        model not in protocol.MODELS
        or not offer
        or offer["num_gpus"] != 1
        or offer["vram_mib"] < protocol.MODELS[model]["min_vram_mib"]
    ):
        raise ValueError("Das Angebot ist nicht verfügbar oder hat zu wenig VRAM.")
    if protocol.decimal(offer["hourly_usd"]) != expected_hourly:
        raise ValueError("Der Preis hat sich geändert. Bitte das Angebot erneut auswählen.")
    c = settings()
    current = now()
    berlin = current.astimezone(ZoneInfo("Europe/Berlin"))
    month = berlin.strftime("%Y-%m")
    next_month = (berlin.replace(day=28) + timedelta(days=4)).replace(
        day=1, hour=0, minute=0, second=0, microsecond=0
    )
    deadline = min(current + timedelta(minutes=c.gpu_max_minutes), next_month.astimezone(UTC))
    if (deadline - current).total_seconds() < c.gpu_startup_seconds:
        raise ValueError("Vor dem Monatswechsel reicht die sichere Laufzeit nicht mehr aus.")
    estimate = protocol.estimate(offer, c.gpu_max_minutes * 60, c)
    if estimate > c.gpu_session_budget_eur:
        raise ValueError(
            "Dieses Angebot überschreitet mit Speicher und Datentransfer das Sitzungsbudget."
        )
    identifier = uuid.uuid4().hex
    ip_hash = security.token(ip, "ip")
    with transaction() as db:
        db.execute("SELECT pg_advisory_xact_lock(71823762) IS NULL AS locked")
        invoices.active_session(db, session)
        repeated = db.one(
            "SELECT * FROM gpu_leases WHERE session_id=:session AND request_key=:key",
            {"session": session, "key": key},
        )
        if repeated:
            if repeated["request_hash"] != payload_hash:
                raise ValueError("Anfrageschlüssel bereits belegt.")
            identifier = repeated["id"]
        else:
            if db.one("SELECT id FROM gpu_leases WHERE status NOT IN ('destroyed','failed')"):
                raise ValueError("Die Demo-GPU ist gerade belegt. Bitte später erneut versuchen.")
            if not operator(db, session) and db.one(
                "SELECT id FROM gpu_leases WHERE session_id=:session", {"session": session}
            ):
                raise ValueError("Pro Demo-Sitzung ist eine GPU-Miete möglich.")
            if not rate(db, "rent:" + ip_hash, 2, 86400):
                raise ValueError("Das tägliche GPU-Startlimit wurde erreicht.")
            db.execute(
                "INSERT INTO gpu_months(month) VALUES (:month) ON CONFLICT DO NOTHING",
                {"month": month},
            )
            budget = db.one(
                "SELECT * FROM gpu_months WHERE month=:month FOR UPDATE", {"month": month}
            )
            if (
                protocol.decimal(budget["reserved_eur"])
                + protocol.decimal(budget["debited_eur"])
                + c.gpu_session_budget_eur
                > c.gpu_monthly_budget_eur
            ):
                raise ValueError("Das monatliche GPU-Budget ist ausgeschöpft.")
            db.execute(
                "UPDATE gpu_months SET reserved_eur=reserved_eur+:amount WHERE month=:month",
                {"amount": c.gpu_session_budget_eur, "month": month},
            )
            db.execute(
                "INSERT INTO gpu_leases(id,session_id,request_key,request_hash,ip_hash,month,model,mode,offer,label,reserved_eur,estimated_eur,deadline_at) VALUES (:id,:session,:key,:hash,:ip,:month,:model,:mode,CAST(:offer AS jsonb),:label,:amount,:estimate,:deadline)",
                {
                    "id": identifier,
                    "session": session,
                    "key": key,
                    "hash": payload_hash,
                    "ip": ip_hash,
                    "month": month,
                    "model": model,
                    "mode": mode,
                    "offer": dumps(offer),
                    "label": security.label(identifier, int(deadline.timestamp())),
                    "amount": c.gpu_session_budget_eur,
                    "estimate": estimate,
                    "deadline": deadline,
                },
            )
            event(db, identifier, "reserved")
            # Persist recovery intent before SQL commits. A failed write rolls back
            # the reservation; the reaper gives uncommitted/orphan controls a grace
            # period. Thus a crash before SQS dispatch cannot strand the global slot.
            objects.put(
                "control/" + identifier + ".json",
                {"id": identifier, "created_at": current.isoformat()},
            )
    dispatch(identifier)
    return get_lease(session, identifier)


def public_lease(row):
    return {
        k: row[k]
        for k in (
            "id",
            "model",
            "mode",
            "status",
            "offer",
            "reserved_eur",
            "estimated_eur",
            "debited_eur",
            "deadline_at",
            "created_at",
            "finished_at",
            "error",
        )
    }


def get_lease(session, identifier):
    with transaction() as db:
        row = db.one(
            "SELECT * FROM gpu_leases WHERE id=:id AND session_id=:session",
            {"id": identifier, "session": session},
        )
    if not row:
        raise LookupError("GPU-Sitzung nicht gefunden.")
    return public_lease(row)


def workspace(session):
    with transaction() as db:
        rows = db.execute(
            "SELECT * FROM gpu_leases WHERE session_id=:session ORDER BY created_at DESC LIMIT 20",
            {"session": session},
        )
        requests = db.execute(
            "SELECT r.id,r.lease_id,r.status,r.progress,r.result - 'samples' AS result,r.error,r.created_at FROM gpu_requests r JOIN gpu_leases l ON l.id=r.lease_id WHERE l.session_id=:session ORDER BY r.created_at DESC LIMIT 10",
            {"session": session},
        )
        budget = db.one(
            "SELECT * FROM gpu_months WHERE month=:month",
            {"month": now().astimezone(ZoneInfo("Europe/Berlin")).strftime("%Y-%m")},
        )
        owner = operator(db, session)
    return {
        "leases": [public_lease(r) for r in rows],
        "requests": requests,
        "operator": owner,
        "budget": budget,
    }


def request_stop(session, identifier):
    with transaction() as db:
        row = db.one(
            "SELECT * FROM gpu_leases WHERE id=:id AND session_id=:session FOR UPDATE",
            {"id": identifier, "session": session},
        )
        if not row:
            raise LookupError("GPU-Sitzung nicht gefunden.")
        if row["status"] not in TERMINAL:
            db.execute("UPDATE gpu_leases SET status='stopping' WHERE id=:id", {"id": identifier})
            event(db, identifier, "stop_requested")
    dispatch(identifier)
    return get_lease(session, identifier)


def new_request(session, identifier, key, ids, custom):
    prompts = protocol.workload(ids, custom)
    hashed = protocol.fingerprint(dumps(prompts))
    with transaction() as db:
        row = db.one(
            "SELECT * FROM gpu_leases WHERE id=:id AND session_id=:session FOR UPDATE",
            {"id": identifier, "session": session},
        )
        if not row:
            raise LookupError("GPU-Sitzung nicht gefunden.")
        existing = db.one(
            "SELECT id,request_hash FROM gpu_requests WHERE lease_id=:id AND request_key=:key",
            {"id": identifier, "key": key},
        )
        if existing:
            if existing["request_hash"] != hashed:
                raise ValueError("Anfrageschlüssel bereits belegt.")
            return {"id": existing["id"]}
        if custom is not None and not operator(db, session):
            raise PermissionError("Freie Prompts benötigen den Betreiberzugang.")
        if (
            row["mode"] != "live"
            or row["status"] != "ready"
            or timestamp(row["deadline_at"]) <= now()
        ):
            raise ValueError("Die GPU ist noch nicht bereit oder bereits beschäftigt.")
        count = db.one(
            "SELECT count(*) AS count FROM gpu_requests WHERE lease_id=:id", {"id": identifier}
        )
        if int(count["count"]) >= 20:
            raise ValueError("Das Anfragelimit dieser GPU-Sitzung ist erreicht.")
        result = insert_request(db, identifier, key, prompts, False, hashed)
        db.execute(
            "UPDATE gpu_leases SET status='busy',last_activity_at=now() WHERE id=:id",
            {"id": identifier},
        )
    return {"id": result}


def insert_request(db, lease_id, key, prompts, public, hashed=None):
    identifier = uuid.uuid4().hex
    db.execute(
        "INSERT INTO gpu_requests(id,lease_id,request_key,request_hash,protocol,public,prompts) VALUES (:id,:lease,:key,:hash,:protocol,:public,CAST(:prompts AS jsonb))",
        {
            "id": identifier,
            "lease": lease_id,
            "key": key,
            "hash": hashed or protocol.fingerprint(dumps(prompts)),
            "protocol": protocol.PROTOCOL if public else "live-v1",
            "public": public,
            "prompts": dumps(prompts),
        },
    )
    return identifier


def scrub_sessions(db, session=None):
    db.execute("DELETE FROM gpu_rate_limits WHERE expires_at<now()")
    predicate = "s.id=:session" if session else "s.expires_at<now()"
    params = {"session": session} if session else {}
    leases = f"SELECT l.id FROM gpu_leases l JOIN sessions s ON s.id=l.session_id WHERE {predicate}"
    db.execute(
        f"UPDATE gpu_requests SET prompts='[]',progress='{{}}',result=NULL WHERE NOT public AND lease_id IN ({leases})",
        params,
    )
    db.execute(
        f"UPDATE gpu_leases SET status='stopping' WHERE status NOT IN ('destroyed','failed') AND id IN ({leases})",
        params,
    )


def results():
    with transaction() as db:
        return db.execute(
            "SELECT r.id,r.protocol,r.result - 'samples' AS result,r.finished_at,l.model,l.offer->>'gpu' AS gpu FROM gpu_requests r JOIN gpu_leases l ON l.id=r.lease_id WHERE r.public AND r.status='succeeded' ORDER BY r.finished_at DESC LIMIT 100"
        )


def report(identifier, session=None):
    with transaction() as db:
        row = db.one(
            "SELECT r.result FROM gpu_requests r JOIN gpu_leases l ON l.id=r.lease_id WHERE r.id=:id AND r.status='succeeded' AND ((CAST(:session AS text) IS NULL AND r.public) OR l.session_id=:session)",
            {"id": identifier, "session": session},
        )
    if not row:
        raise LookupError("Messbericht nicht gefunden.")
    return row
