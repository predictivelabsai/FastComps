"""Independent FastComps worker.

The worker owns only the ``fast_comps`` lease and schema. FastClinic's worker is
never disabled or modified. Its first responsibility is an ongoing, idempotent
Market sync; the durable job queue is ready for FastComps-native collectors.
"""

from __future__ import annotations

import logging
import os
import socket
import time
import uuid
from datetime import date, datetime, time as clock_time, timedelta, timezone
from zoneinfo import ZoneInfo

from psycopg2.extras import RealDictCursor

from config import (
    DAILY_SCAN_ENABLED, DAILY_SCAN_HOUR_LOCAL, DAILY_SCAN_TIMEZONE,
    SYNC_INTERVAL_SECONDS, WORKER_POLL_SECONDS,
)
from db import SCHEMA, connection, init_db
from migration import sync_fastclinic
from fx import sync_exchange_rates

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
log = logging.getLogger("fastcomps.worker")
OWNER = f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:8]}"


def next_daily_scan(now_utc: datetime) -> datetime:
    """Return the next 08:00 Europe/Vilnius send, including DST changes."""
    zone = ZoneInfo(DAILY_SCAN_TIMEZONE)
    local_now = now_utc.astimezone(zone)
    local_day: date = local_now.date()
    candidate = datetime.combine(local_day, clock_time(DAILY_SCAN_HOUR_LOCAL), tzinfo=zone)
    if candidate <= local_now:
        candidate = datetime.combine(local_day + timedelta(days=1), clock_time(DAILY_SCAN_HOUR_LOCAL), tzinfo=zone)
    return candidate.astimezone(timezone.utc)


def acquire_lease(seconds: int = 90) -> bool:
    with connection() as conn, conn.cursor() as cur:
        cur.execute(f"""INSERT INTO {SCHEMA}.worker_leases (name,owner,expires_at)
            VALUES ('main',%s,NOW()+(%s || ' seconds')::interval)
            ON CONFLICT (name) DO UPDATE SET owner=EXCLUDED.owner,expires_at=EXCLUDED.expires_at,updated_at=NOW()
            WHERE {SCHEMA}.worker_leases.expires_at < NOW() OR {SCHEMA}.worker_leases.owner=EXCLUDED.owner
            RETURNING owner""", (OWNER, seconds))
        acquired = cur.fetchone() is not None
        conn.commit()
        return acquired


def process_one_job() -> bool:
    with connection(dict_rows=True) as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(f"""SELECT id,job_type,payload FROM {SCHEMA}.collection_jobs
            WHERE status='queued' AND available_at<=NOW() ORDER BY created_at
            FOR UPDATE SKIP LOCKED LIMIT 1""")
        job = cur.fetchone()
        if not job:
            conn.rollback(); return False
        cur.execute(f"UPDATE {SCHEMA}.collection_jobs SET status='running',started_at=NOW(),attempts=attempts+1 WHERE id=%s", (job["id"],))
        conn.commit()
    try:
        if job["job_type"] == "sync_fastclinic":
            sync_fastclinic()
        elif job["job_type"] == "daily_scan":
            from newsletter import send_daily_scan_to_all
            send_daily_scan_to_all()
        else:
            raise ValueError(f"Unsupported job type: {job['job_type']}")
        with connection() as conn, conn.cursor() as cur:
            cur.execute(f"UPDATE {SCHEMA}.collection_jobs SET status='completed',finished_at=NOW(),error=NULL WHERE id=%s", (job["id"],)); conn.commit()
    except Exception as exc:
        log.exception("Job %s failed", job["id"])
        with connection() as conn, conn.cursor() as cur:
            cur.execute(f"UPDATE {SCHEMA}.collection_jobs SET status='failed',finished_at=NOW(),error=%s WHERE id=%s", (str(exc)[:2000],job["id"])); conn.commit()
    return True


def run_forever() -> None:
    init_db()
    next_sync = 0.0
    next_fx_sync = 0.0
    next_scan = next_daily_scan(datetime.now(timezone.utc))
    while True:
        if not acquire_lease():
            time.sleep(WORKER_POLL_SECONDS); continue
        now = time.monotonic()
        if now >= next_fx_sync:
            try:
                result = sync_exchange_rates()
                log.info("ECB FX rates synced: %s currencies effective %s", result["currencies"], result["effective_date"])
            except Exception:
                log.exception("Scheduled ECB FX sync failed")
            next_fx_sync = time.monotonic() + 6 * 60 * 60
        if now >= next_sync:
            try:
                sync_fastclinic()
            except Exception:
                log.exception("Scheduled FastClinic sync failed")
            next_sync = time.monotonic() + SYNC_INTERVAL_SECONDS
        if DAILY_SCAN_ENABLED and datetime.now(timezone.utc) >= next_scan:
            try:
                from newsletter import send_daily_scan_to_all
                result = send_daily_scan_to_all()
                log.info("Daily scan sent=%s/%s", result.get("sent"), result.get("total"))
            except Exception:
                log.exception("Scheduled daily scan failed")
            next_scan = next_daily_scan(datetime.now(timezone.utc) + timedelta(seconds=1))
        if not process_one_job():
            time.sleep(WORKER_POLL_SECONDS)


if __name__ == "__main__":
    run_forever()
