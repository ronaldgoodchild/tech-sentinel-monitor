-- Tech Sentinel Monitor — Initial Schema (TimescaleDB / PostgreSQL 16)

-- Enable TimescaleDB extension
CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE;

-- ── Tenants ──────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS tenants (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    slug        TEXT NOT NULL UNIQUE,
    api_key     TEXT NOT NULL UNIQUE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ── Monitors ─────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS monitors (
    id               TEXT PRIMARY KEY,
    tenant_id        TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    name             TEXT NOT NULL,
    monitor_type     TEXT NOT NULL CHECK (monitor_type IN ('http', 'tcp', 'ping', 'heartbeat')),
    target           TEXT NOT NULL,
    interval_seconds INTEGER NOT NULL DEFAULT 60,
    timeout_seconds  INTEGER NOT NULL DEFAULT 10,
    external_id      TEXT,
    config           JSONB NOT NULL DEFAULT '{}',
    status           TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'paused')),
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_id, external_id)
);

CREATE INDEX IF NOT EXISTS idx_monitors_tenant ON monitors(tenant_id);
CREATE INDEX IF NOT EXISTS idx_monitors_status ON monitors(status);

-- ── Alert Channels ───────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS alert_channels (
    id           TEXT PRIMARY KEY,
    tenant_id    TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    name         TEXT NOT NULL,
    channel_type TEXT NOT NULL CHECK (channel_type IN ('webhook', 'slack', 'pagerduty', 'ts_automation')),
    config       JSONB NOT NULL DEFAULT '{}',
    external_id  TEXT,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_id, external_id)
);

-- ── Status Pages ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS status_pages (
    id          TEXT PRIMARY KEY,
    tenant_id   TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    name        TEXT NOT NULL,
    slug        TEXT NOT NULL UNIQUE,
    theme       JSONB NOT NULL DEFAULT '{}',
    monitor_ids JSONB NOT NULL DEFAULT '[]',
    external_id TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_id, external_id)
);

-- ── Check Results (TimescaleDB hypertable) ───────────────────────────────────
CREATE TABLE IF NOT EXISTS check_results (
    id               TEXT NOT NULL,
    monitor_id       TEXT NOT NULL REFERENCES monitors(id) ON DELETE CASCADE,
    checked_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    status           TEXT NOT NULL CHECK (status IN ('up', 'down', 'degraded', 'timeout')),
    response_time_ms DOUBLE PRECISION,
    status_code      INTEGER,
    error            TEXT,
    PRIMARY KEY (id, checked_at)
);

-- Convert to hypertable (TimescaleDB)
SELECT create_hypertable('check_results', 'checked_at', if_not_exists => TRUE);

-- Auto-compression after 7 days
ALTER TABLE check_results SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'monitor_id'
);
SELECT add_compression_policy('check_results', INTERVAL '7 days', if_not_exists => TRUE);

-- Retention policy — drop data older than 90 days
SELECT add_retention_policy('check_results', INTERVAL '90 days', if_not_exists => TRUE);

-- ── Continuous Aggregate for dashboards ──────────────────────────────────────
CREATE MATERIALIZED VIEW IF NOT EXISTS check_results_5m
WITH (timescaledb.continuous) AS
SELECT
    time_bucket('5 minutes', checked_at) AS bucket,
    monitor_id,
    COUNT(*) AS total_checks,
    COUNT(*) FILTER (WHERE status = 'up') AS up_count,
    AVG(response_time_ms) AS avg_response_ms,
    MAX(response_time_ms) AS max_response_ms,
    MIN(response_time_ms) AS min_response_ms
FROM check_results
GROUP BY bucket, monitor_id
WITH NO DATA;

SELECT add_continuous_aggregate_policy('check_results_5m',
    start_offset => INTERVAL '1 hour',
    end_offset => INTERVAL '5 minutes',
    schedule_interval => INTERVAL '5 minutes',
    if_not_exists => TRUE
);
