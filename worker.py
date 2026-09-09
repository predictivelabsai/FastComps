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
from datetime import datetime, timedelta, timezone

from psycopg2.extras import RealDictCursor

from config import DAILY_SCAN_ENABLED, DAILY_SCAN_HOUR_UTC, SYNC_INTERVAL_SECONDS, WORKER_POLL_SECONDS
from db import SCHEMA, connection, init_db
from migration import sync_fastclinic

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
log = logging.getLogger("fastcomps.worker")
OWNER = f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:8]}"


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
    now_utc = datetime.now(timezone.utc)
    next_scan = now_utc.replace(hour=DAILY_SCAN_HOUR_UTC, minute=0, second=0, microsecond=0)
    if next_scan <= now_utc:
        next_scan += timedelta(days=1)
    while True:
        if not acquire_lease():
            time.sleep(WORKER_POLL_SECONDS); continue
        now = time.monotonic()
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
            next_scan += timedelta(days=1)
        if not process_one_job():
            time.sleep(WORKER_POLL_SECONDS)


if __name__ == "__main__":
    run_forever()
