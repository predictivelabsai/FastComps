"""Lossless FastClinic Market mirror and generic-model projection."""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from psycopg2 import sql
from psycopg2.extras import RealDictCursor, execute_values, Json

from db import SCHEMA, SOURCE_SCHEMA, connection, init_db

log = logging.getLogger("fastcomps.migration")

SOURCE_TABLES = (
    "market_address_attempt", "market_candidate", "market_candidate_source",
    "market_clinic", "market_config", "market_country_campaign",
    "market_geocode_cache", "market_geocode_gate", "market_hospital",
    "market_lock", "market_observation", "market_run", "market_service",
    "market_service_taxonomy", "market_source", "market_taxonomy_node",
    "market_watchlist", "search_provider_credentials",
)


def _id(value: Any) -> str | None:
    return f"fc:{value}" if value not in (None, "") else None


def _json(value: Any, default: Any) -> Any:
    if value in (None, ""):
        return default
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default


def _ts(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _decimal(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value).replace(",", "."))
    except InvalidOperation:
        return None


def _rows(cur, table: str) -> list[dict]:
    cur.execute(sql.SQL("SELECT * FROM {}.{}").format(sql.Identifier(SOURCE_SCHEMA), sql.Identifier(table)))
    return [dict(row) for row in cur.fetchall()]


def _upsert(cur, table: str, columns: tuple[str, ...], rows: list[tuple], conflict: str, updates: tuple[str, ...]) -> None:
    if not rows:
        return
    query = sql.SQL("INSERT INTO {}.{} ({}) VALUES %s ON CONFLICT ({}) DO UPDATE SET {}").format(
        sql.Identifier(SCHEMA), sql.Identifier(table),
        sql.SQL(",").join(map(sql.Identifier, columns)),
        sql.SQL(",").join(map(sql.Identifier, conflict.split(","))),
        sql.SQL(",").join(sql.SQL("{}=EXCLUDED.{}").format(sql.Identifier(c), sql.Identifier(c)) for c in updates),
    )
    execute_values(cur, query.as_string(cur), rows, page_size=500)


def mirror_source_tables(cur) -> dict[str, int]:
    """Rebuild exact read-only snapshots of all 18 source tables atomically."""
    counts: dict[str, int] = {}
    for table in SOURCE_TABLES:
        mirror = f"legacy_{table}"
        cur.execute(sql.SQL("DROP TABLE IF EXISTS {}.{} CASCADE").format(sql.Identifier(SCHEMA), sql.Identifier(mirror)))
        cur.execute(sql.SQL("CREATE TABLE {}.{} (LIKE {}.{} INCLUDING ALL)").format(
            sql.Identifier(SCHEMA), sql.Identifier(mirror),
            sql.Identifier(SOURCE_SCHEMA), sql.Identifier(table),
        ))
        cur.execute(sql.SQL("INSERT INTO {}.{} SELECT * FROM {}.{}").format(
            sql.Identifier(SCHEMA), sql.Identifier(mirror),
            sql.Identifier(SOURCE_SCHEMA), sql.Identifier(table),
        ))
        counts[table] = cur.rowcount
    return counts


def project_generic_model(cur) -> None:
    configs = _rows(cur, "market_config")
    if configs:
        latest = configs[-1]
        cur.execute(f"""INSERT INTO {SCHEMA}.vertical_settings
            (vertical_id,config,source_system,legacy_id,updated_at) VALUES ('clinics',%s,'fastclinic',%s,NOW())
            ON CONFLICT (vertical_id) DO UPDATE SET config=EXCLUDED.config,legacy_id=EXCLUDED.legacy_id,updated_at=NOW()""",
            (Json(_json(latest["payload"],{"raw":latest["payload"]})),str(latest["id"])))

    hospitals = _rows(cur, "market_hospital")
    _upsert(cur, "competitors",
        ("id","vertical_id","name","country_code","domain","website_url","description","status","source_system","legacy_table","legacy_id","first_seen_at"),
        [(_id(r["id"]),"clinics",r["name"],r["country"],r["domain"],r["source_url"],r["evidence"],"verified","fastclinic","market_hospital",r["id"],_ts(r["first_seen"])) for r in hospitals],
        "id", ("name","country_code","domain","website_url","description","status","first_seen_at"))

    runs = _rows(cur, "market_run")
    _upsert(cur, "collection_runs",
        ("id","vertical_id","trigger_kind","actor","status","scheduled_week","config","stats","error","started_at","finished_at","source_system","legacy_id"),
        [(_id(r["id"]),"clinics",r["trigger_kind"],r["actor"],r["status"],r["scheduled_week"],Json(_json(r["config"],{})),Json(_json(r["stats"],{})),r["error"],_ts(r["created_at"]),_ts(r["finished_at"]),"fastclinic",r["id"]) for r in runs],
        "id", ("status","config","stats","error","finished_at"))

    taxonomy = _rows(cur, "market_taxonomy_node")
    _upsert(cur, "categories", ("id","vertical_id","parent_id","level","name","source","version","source_system","legacy_id"),
        [(_id(r["id"]),"clinics",None,r["level"] or "category",r["label"],r["source"],r["version"],"fastclinic",r["id"]) for r in taxonomy],
        "id", ("level","name","source","version"))
    for r in taxonomy:
        if r["parent_id"]:
            cur.execute(f"UPDATE {SCHEMA}.categories SET parent_id=%s WHERE id=%s", (_id(r["parent_id"]),_id(r["id"])))

    mapping = {r["service_id"]: r for r in _rows(cur, "market_service_taxonomy")}
    services = _rows(cur, "market_service")
    _upsert(cur, "offerings",
        ("id","vertical_id","offering_type","name","category_id","taxonomy_method","taxonomy_confidence","taxonomy_version","source_system","legacy_table","legacy_id"),
        [(_id(r["id"]),"clinics","service",r["name"],_id(mapping[r["id"]]["taxonomy_id"]) if r["id"] in mapping else None,
          mapping.get(r["id"],{}).get("method"),mapping.get(r["id"],{}).get("confidence"),mapping.get(r["id"],{}).get("version"),
          "fastclinic","market_service",r["id"]) for r in services],
        "id", ("name","category_id","taxonomy_method","taxonomy_confidence","taxonomy_version"))

    clinics = _rows(cur, "market_clinic")
    _upsert(cur, "competitor_locations",
        ("id","competitor_id","name","address","city","country_code","postal_code","phone","website_url","latitude","longitude","geocode_status","geocode_source","evidence","source_url","retrieved_at","source_system","legacy_table","legacy_id"),
        [(_id(r["id"]),_id(r["hospital_id"]),r["name"],r["address"],r["city"],r["country"],r["postal_code"],r["phone"],r["website"],_decimal(r["latitude"]),_decimal(r["longitude"]),r["geocode_status"],r["geocode_source"],r["evidence"],r["source_url"],_ts(r["retrieved_at"]),"fastclinic","market_clinic",r["id"]) for r in clinics if _id(r["hospital_id"])],
        "id", ("name","address","city","country_code","postal_code","phone","website_url","latitude","longitude","geocode_status","geocode_source","evidence","source_url","retrieved_at"))

    address_attempts = _rows(cur, "market_address_attempt")
    _upsert(cur,"address_attempts",("competitor_id","status","attempted_at","error","source_system","legacy_id"),
        [(_id(r["hospital_id"]),r["status"],_ts(r["attempted_at"]),r["error"],"fastclinic",r["hospital_id"])
         for r in address_attempts if _id(r["hospital_id"]) in {_id(h["id"]) for h in hospitals}],
        "competitor_id",("status","attempted_at","error"))

    geocode_cache = _rows(cur,"market_geocode_cache")
    _upsert(cur,"geocode_cache",("id","vertical_id","payload","checked_at","source_system","legacy_id"),
        [(_id(r["id"]),"clinics",Json(_json(r["payload"],{"raw":r["payload"]})),_ts(r["checked_at"]),"fastclinic",r["id"])
         for r in geocode_cache],"id",("payload","checked_at"))
    geocode_gates = _rows(cur,"market_geocode_gate")
    _upsert(cur,"geocode_gates",("name","next_at","source_system","legacy_id"),
        [(f"fastclinic:{r['id']}",_ts(r["next_at"]),"fastclinic",str(r["id"])) for r in geocode_gates],
        "name",("next_at",))

    sources = _rows(cur, "market_source")
    _upsert(cur, "sources",
        ("id","run_id","country_code","provider","url","status","error","retrieved_at","source_system","legacy_table","legacy_id"),
        [(_id(r["id"]),_id(r["run_id"]),r["country"],r["provider"],r["url"],r["status"],r["error"],_ts(r["retrieved_at"]),"fastclinic","market_source",r["id"]) for r in sources],
        "id", ("status","error","retrieved_at"))
    for r in sources:
        payload = _json(r["payload"], {"raw": r["payload"]})
        digest = hashlib.sha256(str(r["payload"] or "").encode()).hexdigest()
        cur.execute(f"""INSERT INTO {SCHEMA}.source_snapshots (source_id,content,content_hash,retrieved_at)
            VALUES (%s,%s,%s,%s) ON CONFLICT (source_id,content_hash) DO NOTHING""",
            (_id(r["id"]),Json(payload),digest,_ts(r["retrieved_at"])))

    observations = _rows(cur, "market_observation")
    _upsert(cur, "observations",
        ("id","run_id","competitor_id","offering_id","original_name","price_min","price_max","price_type","currency","source_url","provider","evidence","ownership_evidence","published_at","retrieved_at","source_system","legacy_table","legacy_id"),
        [(_id(r["id"]),_id(r["run_id"]),_id(r["hospital_id"]),_id(r["service_id"]),r["original_name"],_decimal(r["price"]),_decimal(r["price_max"]),r["price_type"] or "unavailable",r["currency"],r["source_url"],r["provider"],r["evidence"],r["ownership_evidence"],_ts(r["published_at"]),_ts(r["retrieved_at"]),"fastclinic","market_observation",r["id"]) for r in observations],
        "id", ("price_min","price_max","price_type","currency","source_url","provider","evidence","ownership_evidence","published_at","retrieved_at"))
    cur.execute(f"""INSERT INTO {SCHEMA}.competitor_offerings
        (competitor_id,offering_id,first_seen_at,last_seen_at)
        SELECT competitor_id,offering_id,MIN(retrieved_at),MAX(retrieved_at) FROM {SCHEMA}.observations
        WHERE source_system='fastclinic' GROUP BY competitor_id,offering_id
        ON CONFLICT (competitor_id,offering_id) DO UPDATE SET
        first_seen_at=LEAST({SCHEMA}.competitor_offerings.first_seen_at,EXCLUDED.first_seen_at),
        last_seen_at=GREATEST({SCHEMA}.competitor_offerings.last_seen_at,EXCLUDED.last_seen_at)""")

    candidates = _rows(cur, "market_candidate")
    hospital_domains = {r["domain"]: _id(r["id"]) for r in hospitals if r["domain"]}
    _upsert(cur, "candidates",
        ("id","vertical_id","country_code","candidate_key","name","official_domain","source_url","source_type","state","discovered_at","last_seen_at","reviewed_by","reviewed_at","rejection_reason","competitor_id","source_system","legacy_id"),
        [(_id(r["id"]),"clinics",r["country"],r["candidate_key"],r["name"],r["official_domain"],r["source_url"],r["source_type"],r["state"],_ts(r["discovered_at"]),_ts(r["last_seen_at"]),r["reviewed_by"],_ts(r["reviewed_at"]),r["rejection_reason"],hospital_domains.get(r["official_domain"]),"fastclinic",r["id"]) for r in candidates],
        "id", ("name","official_domain","source_url","state","last_seen_at","reviewed_by","reviewed_at","rejection_reason","competitor_id"))
    candidate_sources = _rows(cur, "market_candidate_source")
    _upsert(cur, "candidate_sources",
        ("id","candidate_id","source_url","source_type","discovery_query","title","evidence","retrieved_at","source_system","legacy_id"),
        [(_id(r["id"]),_id(r["candidate_id"]),r["source_url"],r["source_type"],r["discovery_query"],r["title"],r["evidence"],_ts(r["retrieved_at"]),"fastclinic",r["id"]) for r in candidate_sources],
        "id", ("source_url","source_type","discovery_query","title","evidence","retrieved_at"))

    campaigns = _rows(cur, "market_country_campaign")
    _upsert(cur, "coverage_campaigns",
        ("vertical_id","country_code","priority","target","status","requested_by","queued_at","started_at","finished_at","last_run_id","error","source_system","updated_at"),
        [("clinics",r["country"],r["priority"] or 100,r["target"] or 10,r["status"] or "not_started",r["requested_by"],_ts(r["queued_at"]),_ts(r["started_at"]),_ts(r["finished_at"]),_id(r["last_run_id"]),r["error"],"fastclinic",datetime.now().astimezone()) for r in campaigns],
        "vertical_id,country_code", ("priority","target","status","requested_by","queued_at","started_at","finished_at","last_run_id","error","source_system","updated_at"))

    cur.execute(f"""INSERT INTO {SCHEMA}.watchlists (id,vertical_id,name,description,source_system,legacy_id)
        VALUES ('fc:priority-clinics','clinics','Priority clinics','Curated FastClinic competitor watchlist','fastclinic','priority-clinics')
        ON CONFLICT (id) DO UPDATE SET description=EXCLUDED.description""")
    watchlist = _rows(cur, "market_watchlist")
    for r in watchlist:
        urls = _json(r["urls"], [])
        domain = next((h for h in hospital_domains if any(h in u for u in urls)), None)
        cur.execute(f"""INSERT INTO {SCHEMA}.watchlist_targets
            (id,watchlist_id,competitor_id,name,country_code,segment,cities,positioning,capabilities,scope_score,focus_score,urls,active,priority,origin,source_system,legacy_id)
            VALUES (%s,'fc:priority-clinics',%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'fastclinic',%s)
            ON CONFLICT (id) DO UPDATE SET competitor_id=EXCLUDED.competitor_id,name=EXCLUDED.name,
            country_code=EXCLUDED.country_code,segment=EXCLUDED.segment,cities=EXCLUDED.cities,
            positioning=EXCLUDED.positioning,capabilities=EXCLUDED.capabilities,scope_score=EXCLUDED.scope_score,
            focus_score=EXCLUDED.focus_score,urls=EXCLUDED.urls,active=EXCLUDED.active,priority=EXCLUDED.priority""",
            (_id(r["id"]),hospital_domains.get(domain),r["name"],r["country"],r["segment"],Json(_json(r["cities"],[])),r["positioning"],Json(_json(r["capabilities"],[])),r["scope"],r["iv_focus"],Json(urls),bool(r["active"]),r["priority"],r["origin"],r["id"]))

    credentials = _rows(cur,"search_provider_credentials")
    _upsert(cur,"provider_credentials",("owner_key","provider","encrypted_key","updated_at","source_system","legacy_id"),
        [(r["owner"],r["provider"],r["encrypted_key"],_ts(r["updated_at"]),"fastclinic",f"{r['owner']}:{r['provider']}") for r in credentials],
        "owner_key,provider",("encrypted_key","updated_at"))


def sync_fastclinic() -> dict[str, int]:
    """Run an idempotent snapshot + projection in one transaction."""
    init_db()
    with connection(dict_rows=True) as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(f"""INSERT INTO {SCHEMA}.sync_state (source_system,last_started_at,status)
            VALUES ('fastclinic',NOW(),'running') ON CONFLICT (source_system) DO UPDATE
            SET last_started_at=NOW(),status='running',error=NULL""")
        try:
            counts = mirror_source_tables(cur)
            project_generic_model(cur)
            cur.execute(f"""UPDATE {SCHEMA}.sync_state SET last_completed_at=NOW(),status='complete',
                table_counts=%s,error=NULL WHERE source_system='fastclinic'""", (Json(counts),))
            conn.commit()
            log.info("FastClinic sync complete: %s", counts)
            return counts
        except Exception as exc:
            conn.rollback()
            with conn.cursor() as error_cur:
                error_cur.execute(f"""INSERT INTO {SCHEMA}.sync_state (source_system,last_started_at,status,error)
                    VALUES ('fastclinic',NOW(),'failed',%s) ON CONFLICT (source_system) DO UPDATE
                    SET status='failed',error=EXCLUDED.error""", (str(exc)[:2000],))
                conn.commit()
            raise


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print(json.dumps(sync_fastclinic(), indent=2))
