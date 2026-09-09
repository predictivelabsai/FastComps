"""Container health probe for the non-HTTP FastComps worker."""

from __future__ import annotations

from db import SCHEMA, connection


def main() -> int:
    try:
        with connection() as conn, conn.cursor() as cur:
            cur.execute(
                f"""SELECT EXISTS (
                    SELECT 1 FROM {SCHEMA}.worker_leases
                    WHERE name = 'main' AND expires_at > NOW()
                )"""
            )
            return 0 if cur.fetchone()[0] else 1
    except Exception:
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
