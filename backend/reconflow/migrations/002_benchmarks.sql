ALTER TABLE sessions ADD COLUMN operator_until TIMESTAMPTZ;

CREATE TABLE gpu_months (
    month TEXT PRIMARY KEY,
    reserved_eur NUMERIC(18,8) NOT NULL DEFAULT 0 CHECK (reserved_eur >= 0),
    debited_eur NUMERIC(18,8) NOT NULL DEFAULT 0 CHECK (debited_eur >= 0)
);

CREATE TABLE gpu_leases (
    id TEXT PRIMARY KEY,
    session_id TEXT REFERENCES sessions(id) ON DELETE SET NULL,
    request_key TEXT NOT NULL,
    request_hash TEXT NOT NULL,
    ip_hash TEXT NOT NULL,
    month TEXT NOT NULL REFERENCES gpu_months(month),
    model TEXT NOT NULL,
    mode TEXT NOT NULL CHECK (mode IN ('suite','live')),
    status TEXT NOT NULL DEFAULT 'queued' CHECK (status IN ('queued','creating','unknown','starting','ready','busy','stopping','destroyed','failed')),
    offer JSONB NOT NULL,
    label TEXT NOT NULL UNIQUE,
    instance_id BIGINT UNIQUE,
    reserved_eur NUMERIC(18,8) NOT NULL,
    estimated_eur NUMERIC(18,8),
    debited_eur NUMERIC(18,8),
    deadline_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    attempted_at TIMESTAMPTZ,
    last_activity_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    heartbeat_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,
    metadata JSONB NOT NULL DEFAULT '{}',
    error TEXT,
    UNIQUE(session_id, request_key)
);

CREATE UNIQUE INDEX gpu_one_active ON gpu_leases ((1)) WHERE status NOT IN ('destroyed','failed');

CREATE INDEX gpu_leases_session ON gpu_leases(session_id, created_at);

CREATE TABLE gpu_requests (
    id TEXT PRIMARY KEY,
    lease_id TEXT NOT NULL REFERENCES gpu_leases(id),
    request_key TEXT NOT NULL,
    request_hash TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','running','succeeded','failed','unknown')),
    protocol TEXT NOT NULL,
    public BOOLEAN NOT NULL DEFAULT FALSE,
    prompts JSONB NOT NULL,
    progress JSONB NOT NULL DEFAULT '{}',
    result JSONB,
    sequence INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,
    error TEXT,
    UNIQUE(lease_id, request_key)
);

CREATE UNIQUE INDEX gpu_one_request ON gpu_requests(lease_id) WHERE status IN ('pending','running');

CREATE TABLE gpu_rate_limits (
    key TEXT PRIMARY KEY,
    count INTEGER NOT NULL DEFAULT 0,
    expires_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE gpu_events (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    lease_id TEXT NOT NULL REFERENCES gpu_leases(id),
    action TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
