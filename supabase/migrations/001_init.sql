-- trend-bot schema. Observability + idempotency safety net.
-- The database is NOT authoritative state: the exchange is the source of truth.
-- Every natural key has a UNIQUE constraint so a replayed cycle cannot duplicate.

create schema if not exists trendbot;

-- Strategy configuration, keyed by its deterministic hash.
create table if not exists trendbot.config (
    config_hash text primary key,
    universe    jsonb       not null,
    params      jsonb       not null,
    git_commit  text,
    created_at  timestamptz not null default now()
);

-- Per-bar, per-symbol target weights.
create table if not exists trendbot.signals (
    bar_close_at  timestamptz not null,
    symbol        text        not null,
    config_hash   text        not null,
    target_weight double precision not null,
    realized_vol  double precision,
    created_at    timestamptz not null default now(),
    unique (bar_close_at, symbol, config_hash)
);
create index if not exists signals_bar_close_idx on trendbot.signals (bar_close_at desc);

-- Orders. The UNIQUE order_link_id is the last-line defence against duplicates,
-- independent of application-level idempotency (PRD ST-2 / EE-2).
create table if not exists trendbot.orders (
    order_link_id     text primary key,
    symbol            text        not null,
    side              text        not null,
    qty               numeric     not null,
    price             numeric,
    status            text        not null,
    config_hash       text        not null,
    bar_close_at      timestamptz,
    is_dry_run        boolean     not null default true,
    exchange_order_id text,
    created_at        timestamptz not null default now()
);

-- Latest known position per symbol (mirror of the exchange after reconciliation).
create table if not exists trendbot.positions (
    symbol     text primary key,
    qty        numeric     not null,
    avg_price  numeric     not null default 0,
    updated_at timestamptz not null default now()
);

-- Equity snapshots for the daily report / PnL.
create table if not exists trendbot.equity (
    at           timestamptz primary key,
    total_equity numeric     not null,
    positions    jsonb       not null default '{}'::jsonb
);

-- Append-only audit trail of every state transition / decision.
create table if not exists trendbot.decision_log (
    id             bigint generated always as identity primary key,
    decision_type  text        not null,
    symbol         text,
    observed_state jsonb       not null default '{}'::jsonb,
    outcome        text,
    created_at     timestamptz not null default now()
);
create index if not exists decision_log_created_idx on trendbot.decision_log (created_at desc);

-- Operational alerts (info / warning / error / critical).
create table if not exists trendbot.alerts (
    id         bigint generated always as identity primary key,
    severity   text        not null,
    message    text        not null,
    created_at timestamptz not null default now()
);
