"""PostgreSQL storage for FastComps.

FastComps shares a database server with FastClinic but owns the ``fast_comps``
schema. The source schema is read-only from this application's point of view.
"""

from __future__ import annotations

import os
import re
import threading
from contextlib import contextmanager

import psycopg2
from psycopg2.extras import RealDictCursor
from psycopg2.pool import ThreadedConnectionPool


def _schema_env(name: str, default: str) -> str:
    value = os.getenv(name, default)
    if not re.fullmatch(r"[a-z_][a-z0-9_]*", value):
        raise RuntimeError(f"Invalid PostgreSQL schema name in {name}")
    return value


DB_URL = os.getenv("DB_URL") or os.getenv("DATABASE_URL_PROD")
SCHEMA = _schema_env("DB_SCHEMA", "fast_comps")
SOURCE_SCHEMA = _schema_env("SOURCE_DB_SCHEMA", "fast_clinic")
_pool: ThreadedConnectionPool | None = None
_pool_max = max(1, int(os.getenv("DB_POOL_MAX", "16")))
_pool_slots = threading.BoundedSemaphore(_pool_max)
_pool_init_lock = threading.Lock()


def database_url() -> str:
    if not DB_URL:
        raise RuntimeError("DB_URL or DATABASE_URL_PROD is required")
    return DB_URL


def pool() -> ThreadedConnectionPool:
    global _pool
    if _pool is None:
        with _pool_init_lock:
            if _pool is None:
                _pool = ThreadedConnectionPool(1, _pool_max, database_url())
    return _pool


@contextmanager
def connection(*, dict_rows: bool = False, read_only: bool = False):
    if not _pool_slots.acquire(timeout=float(os.getenv("DB_POOL_WAIT_SECONDS", "30"))):
        raise RuntimeError("Database connection pool wait timed out")
    conn = None
    try:
        conn = pool().getconn()
        conn.set_session(readonly=read_only, autocommit=False)
        with conn.cursor(cursor_factory=RealDictCursor if dict_rows else None) as cur:
            cur.execute(f'SET search_path TO "{SCHEMA}", public')
        yield conn
    except Exception:
        if conn is not None:
            conn.rollback()
        raise
    finally:
        try:
            if conn is not None:
                try:
                    conn.rollback()
                    conn.set_session(readonly=False, autocommit=False)
                except Exception:
                    pool().putconn(conn, close=True)
                    raise
                else:
                    pool().putconn(conn)
        finally:
            _pool_slots.release()


DDL = r"""
CREATE SCHEMA IF NOT EXISTS fast_comps;
CREATE TABLE IF NOT EXISTS fast_comps.verticals (
 id TEXT PRIMARY KEY, name TEXT NOT NULL, description TEXT, active BOOLEAN NOT NULL DEFAULT TRUE,
 created_at TIMESTAMPTZ NOT NULL DEFAULT NOW());
CREATE TABLE IF NOT EXISTS fast_comps.markets (
 country_code CHAR(2) PRIMARY KEY, country_name TEXT NOT NULL, eea BOOLEAN NOT NULL DEFAULT TRUE,
 priority INTEGER NOT NULL DEFAULT 100, target_competitors INTEGER NOT NULL DEFAULT 10,
 created_at TIMESTAMPTZ NOT NULL DEFAULT NOW());
CREATE TABLE IF NOT EXISTS fast_comps.vertical_settings (
 vertical_id TEXT PRIMARY KEY REFERENCES fast_comps.verticals(id), config JSONB NOT NULL DEFAULT '{}'::jsonb,
 source_system TEXT NOT NULL, legacy_id TEXT, updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW());
CREATE TABLE IF NOT EXISTS fast_comps.competitors (
 id TEXT PRIMARY KEY, vertical_id TEXT NOT NULL REFERENCES fast_comps.verticals(id), name TEXT NOT NULL,
 country_code CHAR(2), domain TEXT, website_url TEXT, description TEXT, status TEXT NOT NULL DEFAULT 'verified',
 source_system TEXT NOT NULL, legacy_table TEXT, legacy_id TEXT, first_seen_at TIMESTAMPTZ,
 updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW());
CREATE INDEX IF NOT EXISTS competitors_country_idx ON fast_comps.competitors(country_code);
CREATE INDEX IF NOT EXISTS competitors_domain_idx ON fast_comps.competitors(domain);
CREATE TABLE IF NOT EXISTS fast_comps.competitor_locations (
 id TEXT PRIMARY KEY, competitor_id TEXT NOT NULL REFERENCES fast_comps.competitors(id) ON DELETE CASCADE,
 name TEXT, address TEXT, city TEXT, country_code CHAR(2), postal_code TEXT, phone TEXT, website_url TEXT,
 latitude NUMERIC(10,7), longitude NUMERIC(10,7), geocode_status TEXT, geocode_source TEXT,
 evidence TEXT, source_url TEXT, retrieved_at TIMESTAMPTZ, source_system TEXT NOT NULL,
 legacy_table TEXT, legacy_id TEXT);
CREATE INDEX IF NOT EXISTS locations_country_idx ON fast_comps.competitor_locations(country_code);
CREATE TABLE IF NOT EXISTS fast_comps.categories (
 id TEXT PRIMARY KEY, vertical_id TEXT NOT NULL REFERENCES fast_comps.verticals(id),
 parent_id TEXT REFERENCES fast_comps.categories(id), level TEXT NOT NULL DEFAULT 'category', name TEXT NOT NULL,
 source TEXT, version TEXT, source_system TEXT NOT NULL, legacy_id TEXT);
CREATE TABLE IF NOT EXISTS fast_comps.offerings (
 id TEXT PRIMARY KEY, vertical_id TEXT NOT NULL REFERENCES fast_comps.verticals(id),
 offering_type TEXT NOT NULL DEFAULT 'service' CHECK (offering_type IN ('service','product')),
 name TEXT NOT NULL, original_name TEXT, category_id TEXT REFERENCES fast_comps.categories(id),
 taxonomy_method TEXT, taxonomy_confidence TEXT, taxonomy_version TEXT,
 source_system TEXT NOT NULL, legacy_table TEXT, legacy_id TEXT);
CREATE INDEX IF NOT EXISTS offerings_category_idx ON fast_comps.offerings(category_id);
CREATE TABLE IF NOT EXISTS fast_comps.competitor_offerings (
 competitor_id TEXT NOT NULL REFERENCES fast_comps.competitors(id) ON DELETE CASCADE,
 offering_id TEXT NOT NULL REFERENCES fast_comps.offerings(id) ON DELETE CASCADE,
 first_seen_at TIMESTAMPTZ, last_seen_at TIMESTAMPTZ, active BOOLEAN NOT NULL DEFAULT TRUE,
 PRIMARY KEY (competitor_id, offering_id));
CREATE TABLE IF NOT EXISTS fast_comps.collection_runs (
 id TEXT PRIMARY KEY, vertical_id TEXT NOT NULL REFERENCES fast_comps.verticals(id), country_code CHAR(2),
 trigger_kind TEXT, actor TEXT, status TEXT NOT NULL, scheduled_week TEXT,
 config JSONB NOT NULL DEFAULT '{}'::jsonb, stats JSONB NOT NULL DEFAULT '{}'::jsonb, error TEXT,
 started_at TIMESTAMPTZ, finished_at TIMESTAMPTZ, source_system TEXT NOT NULL, legacy_id TEXT);
CREATE TABLE IF NOT EXISTS fast_comps.sources (
 id TEXT PRIMARY KEY, run_id TEXT REFERENCES fast_comps.collection_runs(id), country_code CHAR(2), provider TEXT,
 url TEXT NOT NULL, status TEXT, error TEXT, retrieved_at TIMESTAMPTZ, source_system TEXT NOT NULL,
 legacy_table TEXT, legacy_id TEXT);
CREATE INDEX IF NOT EXISTS sources_url_idx ON fast_comps.sources(url);
CREATE TABLE IF NOT EXISTS fast_comps.source_snapshots (
 id BIGSERIAL PRIMARY KEY, source_id TEXT NOT NULL REFERENCES fast_comps.sources(id) ON DELETE CASCADE,
 content JSONB NOT NULL DEFAULT '{}'::jsonb, content_hash TEXT, retrieved_at TIMESTAMPTZ,
 UNIQUE(source_id, content_hash));
CREATE TABLE IF NOT EXISTS fast_comps.observations (
 id TEXT PRIMARY KEY, run_id TEXT REFERENCES fast_comps.collection_runs(id),
 competitor_id TEXT NOT NULL REFERENCES fast_comps.competitors(id),
 offering_id TEXT NOT NULL REFERENCES fast_comps.offerings(id), original_name TEXT,
 price_min NUMERIC(14,2), price_max NUMERIC(14,2), price_type TEXT NOT NULL, currency CHAR(3),
 source_url TEXT NOT NULL, provider TEXT, evidence TEXT, ownership_evidence TEXT,
 published_at TIMESTAMPTZ, retrieved_at TIMESTAMPTZ, source_system TEXT NOT NULL,
 legacy_table TEXT, legacy_id TEXT);
CREATE INDEX IF NOT EXISTS observations_competitor_idx ON fast_comps.observations(competitor_id);
CREATE INDEX IF NOT EXISTS observations_offering_idx ON fast_comps.observations(offering_id);
CREATE INDEX IF NOT EXISTS observations_retrieved_idx ON fast_comps.observations(retrieved_at DESC);
CREATE TABLE IF NOT EXISTS fast_comps.exchange_rates (
 currency CHAR(3) PRIMARY KEY, units_per_eur NUMERIC(20,8) NOT NULL CHECK (units_per_eur > 0),
 effective_date DATE NOT NULL, source_url TEXT NOT NULL,
 updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW());
CREATE TABLE IF NOT EXISTS fast_comps.candidates (
 id TEXT PRIMARY KEY, vertical_id TEXT NOT NULL REFERENCES fast_comps.verticals(id), country_code CHAR(2),
 candidate_key TEXT, name TEXT, official_domain TEXT, source_url TEXT, source_type TEXT,
 state TEXT NOT NULL DEFAULT 'discovered', discovered_at TIMESTAMPTZ, last_seen_at TIMESTAMPTZ,
 reviewed_by TEXT, reviewed_at TIMESTAMPTZ, rejection_reason TEXT,
 competitor_id TEXT REFERENCES fast_comps.competitors(id), source_system TEXT NOT NULL, legacy_id TEXT);
CREATE INDEX IF NOT EXISTS candidates_country_state_idx ON fast_comps.candidates(country_code,state);
CREATE TABLE IF NOT EXISTS fast_comps.candidate_sources (
 id TEXT PRIMARY KEY, candidate_id TEXT NOT NULL REFERENCES fast_comps.candidates(id) ON DELETE CASCADE,
 source_url TEXT, source_type TEXT, discovery_query TEXT, title TEXT, evidence TEXT,
 retrieved_at TIMESTAMPTZ, source_system TEXT NOT NULL, legacy_id TEXT);
CREATE TABLE IF NOT EXISTS fast_comps.coverage_campaigns (
 vertical_id TEXT NOT NULL REFERENCES fast_comps.verticals(id),
 country_code CHAR(2) NOT NULL REFERENCES fast_comps.markets(country_code),
 priority INTEGER NOT NULL DEFAULT 100, target INTEGER NOT NULL DEFAULT 10,
 status TEXT NOT NULL DEFAULT 'not_started', requested_by TEXT, queued_at TIMESTAMPTZ,
 started_at TIMESTAMPTZ, finished_at TIMESTAMPTZ, last_run_id TEXT, error TEXT,
 source_system TEXT NOT NULL DEFAULT 'fastcomps', updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
 PRIMARY KEY (vertical_id,country_code));
CREATE TABLE IF NOT EXISTS fast_comps.watchlists (
 id TEXT PRIMARY KEY, vertical_id TEXT NOT NULL REFERENCES fast_comps.verticals(id), name TEXT NOT NULL,
 description TEXT, active BOOLEAN NOT NULL DEFAULT TRUE, source_system TEXT NOT NULL, legacy_id TEXT,
 created_at TIMESTAMPTZ, updated_at TIMESTAMPTZ);
CREATE TABLE IF NOT EXISTS fast_comps.watchlist_targets (
 id TEXT PRIMARY KEY, watchlist_id TEXT NOT NULL REFERENCES fast_comps.watchlists(id) ON DELETE CASCADE,
 competitor_id TEXT REFERENCES fast_comps.competitors(id), name TEXT NOT NULL, country_code CHAR(2),
 segment TEXT, cities JSONB NOT NULL DEFAULT '[]'::jsonb, positioning TEXT,
 capabilities JSONB NOT NULL DEFAULT '[]'::jsonb, scope_score INTEGER, focus_score INTEGER,
 urls JSONB NOT NULL DEFAULT '[]'::jsonb, active BOOLEAN NOT NULL DEFAULT TRUE, priority INTEGER,
 origin TEXT, source_system TEXT NOT NULL, legacy_id TEXT);
CREATE TABLE IF NOT EXISTS fast_comps.collection_jobs (
 id UUID PRIMARY KEY DEFAULT gen_random_uuid(), vertical_id TEXT NOT NULL REFERENCES fast_comps.verticals(id),
 country_code CHAR(2), job_type TEXT NOT NULL, payload JSONB NOT NULL DEFAULT '{}'::jsonb,
 status TEXT NOT NULL DEFAULT 'queued', attempts INTEGER NOT NULL DEFAULT 0,
 available_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), started_at TIMESTAMPTZ, finished_at TIMESTAMPTZ,
 error TEXT, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW());
CREATE INDEX IF NOT EXISTS collection_jobs_queue_idx ON fast_comps.collection_jobs(status,available_at);
CREATE TABLE IF NOT EXISTS fast_comps.worker_leases (
 name TEXT PRIMARY KEY, owner TEXT NOT NULL, expires_at TIMESTAMPTZ NOT NULL,
 updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW());
CREATE TABLE IF NOT EXISTS fast_comps.address_attempts (
 competitor_id TEXT PRIMARY KEY REFERENCES fast_comps.competitors(id) ON DELETE CASCADE,
 status TEXT, attempted_at TIMESTAMPTZ, error TEXT, source_system TEXT NOT NULL, legacy_id TEXT);
CREATE TABLE IF NOT EXISTS fast_comps.geocode_cache (
 id TEXT PRIMARY KEY, vertical_id TEXT NOT NULL REFERENCES fast_comps.verticals(id), payload JSONB NOT NULL DEFAULT '{}'::jsonb,
 checked_at TIMESTAMPTZ, source_system TEXT NOT NULL, legacy_id TEXT);
CREATE TABLE IF NOT EXISTS fast_comps.geocode_gates (
 name TEXT PRIMARY KEY, next_at TIMESTAMPTZ, source_system TEXT NOT NULL, legacy_id TEXT);
CREATE TABLE IF NOT EXISTS fast_comps.provider_credentials (
 owner_key TEXT NOT NULL, provider TEXT NOT NULL, encrypted_key TEXT NOT NULL, updated_at TIMESTAMPTZ,
 source_system TEXT NOT NULL, legacy_id TEXT, PRIMARY KEY(owner_key,provider));
CREATE TABLE IF NOT EXISTS fast_comps.sync_state (
 source_system TEXT PRIMARY KEY, last_started_at TIMESTAMPTZ, last_completed_at TIMESTAMPTZ,
 status TEXT NOT NULL DEFAULT 'never', table_counts JSONB NOT NULL DEFAULT '{}'::jsonb, error TEXT);
CREATE TABLE IF NOT EXISTS fast_comps.chat_threads (
 id UUID PRIMARY KEY DEFAULT gen_random_uuid(), user_key TEXT NOT NULL,
 title TEXT NOT NULL DEFAULT 'Market question', created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
 updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW());
CREATE TABLE IF NOT EXISTS fast_comps.chat_messages (
 id BIGSERIAL PRIMARY KEY, thread_id UUID NOT NULL REFERENCES fast_comps.chat_threads(id) ON DELETE CASCADE,
 role TEXT NOT NULL CHECK (role IN ('user','assistant')), content TEXT NOT NULL,
 citations JSONB NOT NULL DEFAULT '[]'::jsonb, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW());
CREATE TABLE IF NOT EXISTS fast_comps.users (
 id UUID PRIMARY KEY DEFAULT gen_random_uuid(), email TEXT UNIQUE NOT NULL, name TEXT,
 role TEXT NOT NULL DEFAULT 'viewer', password_hash TEXT, google_sub TEXT UNIQUE,
 email_verified BOOLEAN NOT NULL DEFAULT FALSE, daily_scan_enabled BOOLEAN NOT NULL DEFAULT TRUE,
 updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
 created_at TIMESTAMPTZ NOT NULL DEFAULT NOW());
ALTER TABLE fast_comps.users ADD COLUMN IF NOT EXISTS password_hash TEXT;
ALTER TABLE fast_comps.users ADD COLUMN IF NOT EXISTS google_sub TEXT;
ALTER TABLE fast_comps.users ADD COLUMN IF NOT EXISTS email_verified BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE fast_comps.users ADD COLUMN IF NOT EXISTS daily_scan_enabled BOOLEAN NOT NULL DEFAULT TRUE;
ALTER TABLE fast_comps.users ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW();
CREATE UNIQUE INDEX IF NOT EXISTS users_google_sub_idx ON fast_comps.users(google_sub) WHERE google_sub IS NOT NULL;
CREATE TABLE IF NOT EXISTS fast_comps.account_tokens (
 id UUID PRIMARY KEY DEFAULT gen_random_uuid(), user_id UUID NOT NULL REFERENCES fast_comps.users(id) ON DELETE CASCADE,
 purpose TEXT NOT NULL CHECK (purpose IN ('verify_email','reset_password')),
 token_hash TEXT UNIQUE NOT NULL, expires_at TIMESTAMPTZ NOT NULL, used_at TIMESTAMPTZ,
 created_at TIMESTAMPTZ NOT NULL DEFAULT NOW());
CREATE INDEX IF NOT EXISTS account_tokens_lookup_idx ON fast_comps.account_tokens(token_hash,purpose);
CREATE TABLE IF NOT EXISTS fast_comps.newsletter_deliveries (
 id UUID PRIMARY KEY DEFAULT gen_random_uuid(), scan_date DATE NOT NULL, email TEXT NOT NULL,
 status TEXT NOT NULL CHECK (status IN ('sent','failed')), message_id TEXT, error TEXT,
 created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), UNIQUE(scan_date,email));
CREATE TABLE IF NOT EXISTS fast_comps.user_sessions (
 id UUID PRIMARY KEY DEFAULT gen_random_uuid(), user_id UUID NOT NULL REFERENCES fast_comps.users(id) ON DELETE CASCADE,
 token_hash TEXT UNIQUE NOT NULL, expires_at TIMESTAMPTZ NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW());
CREATE TABLE IF NOT EXISTS fast_comps.api_keys (
 id UUID PRIMARY KEY DEFAULT gen_random_uuid(), user_id UUID REFERENCES fast_comps.users(id) ON DELETE CASCADE,
 name TEXT NOT NULL, key_hash TEXT UNIQUE NOT NULL, last_used_at TIMESTAMPTZ, revoked_at TIMESTAMPTZ,
 created_at TIMESTAMPTZ NOT NULL DEFAULT NOW());
"""


EEA_MARKETS = (
 ("AT","Austria"),("BE","Belgium"),("BG","Bulgaria"),("HR","Croatia"),("CY","Cyprus"),
 ("CZ","Czechia"),("DK","Denmark"),("EE","Estonia"),("FI","Finland"),("FR","France"),
 ("DE","Germany"),("GR","Greece"),("HU","Hungary"),("IS","Iceland"),("IE","Ireland"),
 ("IT","Italy"),("LV","Latvia"),("LI","Liechtenstein"),("LT","Lithuania"),("LU","Luxembourg"),
 ("MT","Malta"),("NL","Netherlands"),("NO","Norway"),("PL","Poland"),("PT","Portugal"),
 ("RO","Romania"),("SK","Slovakia"),("SI","Slovenia"),("ES","Spain"),("SE","Sweden"),
)


def init_db() -> None:
    """Create the owned schema and seed vertical/market dimensions."""
    ddl = DDL.replace("fast_comps", SCHEMA)
    with connection() as conn, conn.cursor() as cur:
        cur.execute(ddl)
        cur.execute(f"""INSERT INTO {SCHEMA}.verticals (id,name,description)
            VALUES ('clinics','Clinics','Private clinic, hospital and wellness intelligence')
            ON CONFLICT (id) DO UPDATE SET name=EXCLUDED.name,description=EXCLUDED.description""")
        cur.executemany(f"""INSERT INTO {SCHEMA}.markets
            (country_code,country_name,priority,target_competitors) VALUES (%s,%s,%s,10)
            ON CONFLICT (country_code) DO UPDATE SET country_name=EXCLUDED.country_name""",
            [(code,name,i+1) for i,(code,name) in enumerate(EEA_MARKETS)])
        cur.execute(f"""INSERT INTO {SCHEMA}.coverage_campaigns
            (vertical_id,country_code,priority,target,status,source_system)
            SELECT 'clinics',country_code,priority,target_competitors,'not_started','fastcomps'
            FROM {SCHEMA}.markets ON CONFLICT (vertical_id,country_code) DO NOTHING""")
        cur.execute(f"""INSERT INTO {SCHEMA}.exchange_rates
            (currency,units_per_eur,effective_date,source_url)
            VALUES ('EUR',1,CURRENT_DATE,'https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml')
            ON CONFLICT (currency) DO UPDATE SET units_per_eur=1,
              effective_date=EXCLUDED.effective_date,source_url=EXCLUDED.source_url,updated_at=NOW()""")
        conn.commit()


def fetch_all(query: str, params: tuple | dict = ()) -> list[dict]:
    with connection(dict_rows=True) as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(query, params)
        return [dict(row) for row in cur.fetchall()]


def fetch_one(query: str, params: tuple | dict = ()) -> dict | None:
    rows = fetch_all(query, params)
    return rows[0] if rows else None
