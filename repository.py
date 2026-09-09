"""Read-only query layer used by the dashboard and assistant."""

from __future__ import annotations

from decimal import Decimal
from typing import Any
from urllib.parse import unquote, urlsplit
from uuid import UUID

from psycopg2.extras import Json

from db import SCHEMA, connection, fetch_all, fetch_one
from treatment_taxonomy import classify_treatment


def treatment_type(name: str | None, mapped: str | None = None) -> str:
    """Return a stable category while retaining the raw offering unchanged."""
    return classify_treatment(name, mapped)


def coverage_status(row: dict) -> str:
    """Expose real campaign states; never manufacture a synthetic collecting state."""
    if row["verified"] >= row["target"]:
        return "covered"
    campaign = str(row.get("campaign_status") or "not_started").strip().casefold().replace(" ", "_")
    if campaign in {"queued", "running", "failed"}:
        return campaign
    if row["candidates"] or row["verified"]:
        return "review_required"
    return "not_started"


def _clean(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


def clean_rows(rows: list[dict]) -> list[dict]:
    return [{k: _clean(v) for k, v in row.items()} for row in rows]


def display_url(value: str | None) -> str:
    """Return a readable URL label without changing the navigable source URL."""
    if not value:
        return "Source"
    try:
        parsed = urlsplit(value)
        host = (parsed.hostname or "").removeprefix("www.")
        path = unquote(parsed.path or "").rstrip("/")
        label = f"{host}{path}"
        return label if label else "Source"
    except (TypeError, ValueError, UnicodeError):
        return "Source"


def overview(country: str | None = None) -> dict:
    params: dict[str, Any] = {"country": country}
    country_filter = "AND country_code=%(country)s" if country else ""
    competitor_count = fetch_one(f"SELECT COUNT(*) AS n FROM {SCHEMA}.competitors WHERE vertical_id='clinics' {country_filter}", params)["n"]
    location_count = fetch_one(f"SELECT COUNT(*) AS n FROM {SCHEMA}.competitor_locations WHERE 1=1 {country_filter}", params)["n"]
    candidates = fetch_one(f"SELECT COUNT(*) AS n FROM {SCHEMA}.candidates WHERE vertical_id='clinics' {country_filter}", params)["n"]
    observation_filter = "AND c.country_code=%(country)s" if country else ""
    observations = fetch_one(f"""SELECT COUNT(*) AS n FROM {SCHEMA}.observations o
        JOIN {SCHEMA}.competitors c ON c.id=o.competitor_id WHERE 1=1 {observation_filter}""", params)["n"]
    priced = fetch_one(f"""SELECT COUNT(*) AS n FROM {SCHEMA}.observations o
        JOIN {SCHEMA}.competitors c ON c.id=o.competitor_id
        WHERE o.price_min IS NOT NULL {observation_filter}""", params)["n"]
    sources = fetch_one(f"SELECT COUNT(*) AS n FROM {SCHEMA}.sources WHERE 1=1 {country_filter}", params)["n"]
    sync = fetch_one(f"SELECT status,last_completed_at,table_counts,error FROM {SCHEMA}.sync_state WHERE source_system='fastclinic'")
    return {
        "competitors": competitor_count, "locations": location_count, "candidates": candidates,
        "observations": observations, "priced_observations": priced, "sources": sources,
        "sync": {k: _clean(v) for k, v in (sync or {"status": "pending"}).items()},
    }


def coverage() -> list[dict]:
    rows = fetch_all(f"""
        WITH competitor_counts AS (
          SELECT country_code,COUNT(*) AS verified FROM {SCHEMA}.competitors
          WHERE vertical_id='clinics' GROUP BY country_code
        ), candidate_counts AS (
          SELECT country_code,COUNT(*) AS candidates,
            COUNT(*) FILTER (WHERE state='discovered') AS discovered,
            COUNT(*) FILTER (WHERE state='watchlisted') AS watchlisted,
            COUNT(*) FILTER (WHERE state='rejected') AS rejected
          FROM {SCHEMA}.candidates WHERE vertical_id='clinics' GROUP BY country_code
        ), location_counts AS (
          SELECT country_code,COUNT(*) AS locations FROM {SCHEMA}.competitor_locations GROUP BY country_code
        ), observation_counts AS (
          SELECT c.country_code,COUNT(*) AS observations,MAX(o.retrieved_at) AS last_observed_at
          FROM {SCHEMA}.observations o JOIN {SCHEMA}.competitors c ON c.id=o.competitor_id
          GROUP BY c.country_code
        )
        SELECT m.country_code,m.country_name,m.target_competitors AS target,
          COALESCE(c.verified,0) AS verified,COALESCE(ca.candidates,0) AS candidates,
          COALESCE(ca.discovered,0) AS discovered,COALESCE(ca.watchlisted,0) AS watchlisted,
          COALESCE(ca.rejected,0) AS rejected,COALESCE(l.locations,0) AS locations,
          COALESCE(o.observations,0) AS observations,
          COALESCE(cc.status,'not_started') AS campaign_status,
          o.last_observed_at
        FROM {SCHEMA}.markets m
        LEFT JOIN competitor_counts c ON c.country_code=m.country_code
        LEFT JOIN candidate_counts ca ON ca.country_code=m.country_code
        LEFT JOIN location_counts l ON l.country_code=m.country_code
        LEFT JOIN observation_counts o ON o.country_code=m.country_code
        LEFT JOIN {SCHEMA}.coverage_campaigns cc ON cc.country_code=m.country_code AND cc.vertical_id='clinics'
        ORDER BY m.priority,m.country_name
    """)
    for row in rows:
        row["coverage_status"] = coverage_status(row)
        row["progress_pct"] = min(100, round(100 * row["verified"] / max(1, row["target"])))
    return clean_rows(rows)


def competitors(country: str | None = None, query: str | None = None, limit: int = 100) -> list[dict]:
    where = ["c.vertical_id='clinics'"]
    params: dict[str, Any] = {"limit": min(max(limit, 1), 250)}
    if country:
        where.append("c.country_code=%(country)s"); params["country"] = country
    if query:
        where.append("(c.name ILIKE %(query)s OR c.domain ILIKE %(query)s)"); params["query"] = f"%{query}%"
    return clean_rows(fetch_all(f"""WITH location_counts AS (
          SELECT competitor_id,COUNT(*) AS locations FROM {SCHEMA}.competitor_locations GROUP BY competitor_id
        ), offering_counts AS (
          SELECT competitor_id,COUNT(*) AS offerings FROM {SCHEMA}.competitor_offerings GROUP BY competitor_id
        ), observation_counts AS (
          SELECT competitor_id,COUNT(*) AS observations,MAX(retrieved_at) AS last_observed_at
          FROM {SCHEMA}.observations GROUP BY competitor_id
        )
        SELECT c.id,c.name,c.country_code,c.domain,c.website_url,c.description,c.status,
          COALESCE(l.locations,0) AS locations,COALESCE(co.offerings,0) AS offerings,
          COALESCE(o.observations,0) AS observations,o.last_observed_at
        FROM {SCHEMA}.competitors c
        LEFT JOIN location_counts l ON l.competitor_id=c.id
        LEFT JOIN offering_counts co ON co.competitor_id=c.id
        LEFT JOIN observation_counts o ON o.competitor_id=c.id
        WHERE {' AND '.join(where)} ORDER BY observations DESC,c.name LIMIT %(limit)s
    """, params))


def observations(country: str | None = None, competitor_id: str | None = None,
                 query: str | None = None, limit: int = 100) -> list[dict]:
    where = ["c.vertical_id='clinics'"]
    params: dict[str, Any] = {"limit": min(max(limit, 1), 300)}
    if country:
        where.append("c.country_code=%(country)s"); params["country"] = country
    if competitor_id:
        where.append("c.id=%(competitor_id)s"); params["competitor_id"] = competitor_id
    if query:
        where.append("(f.name ILIKE %(query)s OR o.original_name ILIKE %(query)s OR c.name ILIKE %(query)s)"); params["query"] = f"%{query}%"
    rows = clean_rows(fetch_all(f"""
        SELECT o.id,c.id AS competitor_id,c.name AS competitor,c.country_code,
          f.name AS offering,o.original_name,
          o.price_min AS original_price_min,o.price_max AS original_price_max,o.currency AS original_currency,
          ROUND(CASE WHEN o.currency='EUR' THEN o.price_min
            WHEN fx.units_per_eur IS NOT NULL THEN o.price_min/fx.units_per_eur END,2) AS price_min,
          ROUND(CASE WHEN o.currency='EUR' THEN o.price_max
            WHEN fx.units_per_eur IS NOT NULL THEN o.price_max/fx.units_per_eur END,2) AS price_max,
          o.price_type,CASE WHEN o.price_min IS NOT NULL AND (o.currency='EUR' OR fx.units_per_eur IS NOT NULL)
            THEN 'EUR' END AS currency,
          fx.effective_date AS fx_effective_date,fx.source_url AS fx_source_url,
          o.evidence,o.source_url,o.provider,o.published_at,o.retrieved_at,
          cat.name AS category
        FROM {SCHEMA}.observations o
        JOIN {SCHEMA}.competitors c ON c.id=o.competitor_id
        JOIN {SCHEMA}.offerings f ON f.id=o.offering_id
        LEFT JOIN {SCHEMA}.categories cat ON cat.id=f.category_id
        LEFT JOIN {SCHEMA}.exchange_rates fx ON fx.currency=o.currency
        WHERE {' AND '.join(where)} ORDER BY o.retrieved_at DESC NULLS LAST,c.name,f.name LIMIT %(limit)s
    """, params))
    for row in rows:
        row["source_label"] = display_url(row.get("source_url"))
    return rows


def locations(country: str | None = None) -> list[dict]:
    params = {"country": country}
    extra = "AND l.country_code=%(country)s" if country else ""
    return clean_rows(fetch_all(f"""SELECT l.id,l.name,c.id AS competitor_id,c.name AS competitor,l.address,l.city,l.country_code,
        l.latitude,l.longitude,l.geocode_status,l.source_url,l.evidence,c.website_url
        FROM {SCHEMA}.competitor_locations l JOIN {SCHEMA}.competitors c ON c.id=l.competitor_id
        WHERE l.latitude IS NOT NULL AND l.longitude IS NOT NULL {extra} ORDER BY c.name,l.city""", params))


def categories(country: str | None = None) -> list[dict]:
    params = {"country": country}
    extra = "AND comp.country_code=%(country)s" if country else ""
    rows = clean_rows(fetch_all(f"""SELECT f.id,f.name,cat.name AS mapped_type,
        ARRAY_REMOVE(ARRAY_AGG(DISTINCT o.competitor_id),NULL) AS competitor_ids,COUNT(o.id) AS observations
        FROM {SCHEMA}.offerings f LEFT JOIN {SCHEMA}.categories cat ON cat.id=f.category_id
        LEFT JOIN {SCHEMA}.observations o ON o.offering_id=f.id
        LEFT JOIN {SCHEMA}.competitors comp ON comp.id=o.competitor_id
        WHERE f.vertical_id='clinics' {extra} GROUP BY f.id,f.name,cat.name""", params))
    grouped: dict[str, dict] = {}
    for row in rows:
        label = treatment_type(row.get("name"), row.get("mapped_type"))
        item = grouped.setdefault(label, {"category": label, "offerings": 0, "competitor_ids": set(), "observations": 0})
        item["offerings"] += 1
        item["competitor_ids"].update(row.get("competitor_ids") or [])
        item["observations"] += row["observations"]
    result = []
    for item in grouped.values():
        competitor_ids = item.pop("competitor_ids")
        result.append({**item, "competitors": len(competitor_ids)})
    return sorted(result, key=lambda item: (-item["observations"], item["category"]))[:30]


def evidence(country: str | None = None, limit: int = 30) -> list[dict]:
    params = {"limit": min(max(limit, 1), 100), "country": country}
    extra = "AND s.country_code=%(country)s" if country else ""
    rows = clean_rows(fetch_all(f"""SELECT s.id,s.country_code,s.provider,s.url,s.status,s.error,s.retrieved_at,
        LEFT(COALESCE(ss.content->>'title',ss.content->>'text',''),240) AS excerpt
        FROM {SCHEMA}.sources s LEFT JOIN LATERAL (
          SELECT content FROM {SCHEMA}.source_snapshots x WHERE x.source_id=s.id ORDER BY x.retrieved_at DESC NULLS LAST LIMIT 1
        ) ss ON TRUE WHERE 1=1 {extra} ORDER BY s.retrieved_at DESC NULLS LAST LIMIT %(limit)s""", params))
    for row in rows:
        row["display_url"] = display_url(row.get("url"))
    return rows


def treatment_treemap(country: str | None = None, limit: int = 700) -> list[dict]:
    params = {"country": country, "limit": min(max(limit, 1), 1200)}
    extra = "AND c.country_code=%(country)s" if country else ""
    rows = clean_rows(fetch_all(f"""
        WITH history_ranked AS (
          SELECT o.*,ROW_NUMBER() OVER (PARTITION BY o.competitor_id,o.offering_id,
            COALESCE(o.original_name,''),o.currency ORDER BY o.retrieved_at DESC NULLS LAST,o.id DESC) AS history_rank
          FROM {SCHEMA}.observations o
        ), converted AS (
          SELECT o.*,ROUND(CASE WHEN o.currency='EUR' THEN o.price_min
            WHEN fx.units_per_eur IS NOT NULL THEN o.price_min/fx.units_per_eur END,2) AS price_eur,
            fx.effective_date AS fx_effective_date
          FROM history_ranked o LEFT JOIN {SCHEMA}.exchange_rates fx ON fx.currency=o.currency
          WHERE o.history_rank=1
        ), leaves AS (
          SELECT c.country_code,cat.name AS mapped_type,
            f.name AS treatment,'EUR'::text AS currency,
            PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY o.price_eur)::numeric AS median_price,
            COUNT(*)::int AS observations,COUNT(DISTINCT o.source_url)::int AS sources,
            MAX(o.fx_effective_date) AS fx_effective_date
          FROM converted o
          JOIN {SCHEMA}.competitors c ON c.id=o.competitor_id
          JOIN {SCHEMA}.offerings f ON f.id=o.offering_id
          LEFT JOIN {SCHEMA}.categories cat ON cat.id=f.category_id
          WHERE c.vertical_id='clinics' AND o.price_eur IS NOT NULL {extra}
          GROUP BY c.country_code,cat.name,f.name
        ), ranked AS (
          SELECT *,CUME_DIST() OVER (
            PARTITION BY country_code ORDER BY median_price
          )::numeric AS price_level
          FROM leaves
        )
        SELECT * FROM ranked
        ORDER BY observations DESC,country_code,mapped_type NULLS LAST,treatment
        LIMIT %(limit)s
    """, params))
    for row in rows:
        row["treatment_type"] = treatment_type(row.get("treatment"), row.pop("mapped_type", None))
    return rows


def competitor_detail(competitor_id: str) -> dict | None:
    competitor = fetch_one(f"""SELECT c.id,c.name,c.country_code,c.domain,c.website_url,c.description,c.status,
        COUNT(DISTINCT l.id) AS locations,COUNT(DISTINCT co.offering_id) AS offerings,
        COUNT(DISTINCT o.id) AS observations,MAX(o.retrieved_at) AS last_observed_at
        FROM {SCHEMA}.competitors c
        LEFT JOIN {SCHEMA}.competitor_locations l ON l.competitor_id=c.id
        LEFT JOIN {SCHEMA}.competitor_offerings co ON co.competitor_id=c.id
        LEFT JOIN {SCHEMA}.observations o ON o.competitor_id=c.id
        WHERE c.id=%s AND c.vertical_id='clinics' GROUP BY c.id""", (competitor_id,))
    if not competitor:
        return None
    location_rows = clean_rows(fetch_all(f"""SELECT id,name,address,city,country_code,postal_code,phone,
        website_url,latitude,longitude,geocode_status,source_url,evidence,retrieved_at
        FROM {SCHEMA}.competitor_locations WHERE competitor_id=%s ORDER BY city,address""", (competitor_id,)))
    prices = clean_rows(fetch_all(f"""WITH history_ranked AS (
          SELECT o.*,ROW_NUMBER() OVER (PARTITION BY o.competitor_id,o.offering_id,
            COALESCE(o.original_name,''),o.currency ORDER BY o.retrieved_at DESC NULLS LAST,o.id DESC) AS history_rank
          FROM {SCHEMA}.observations o
        ), current_prices AS (
          SELECT o.*,ROUND(CASE WHEN o.currency='EUR' THEN o.price_min
            WHEN fx.units_per_eur IS NOT NULL THEN o.price_min/fx.units_per_eur END,2) AS price_min_eur,
            ROUND(CASE WHEN o.currency='EUR' THEN o.price_max
            WHEN fx.units_per_eur IS NOT NULL THEN o.price_max/fx.units_per_eur END,2) AS price_max_eur,
            fx.effective_date AS fx_effective_date,fx.source_url AS fx_source_url
          FROM history_ranked o LEFT JOIN {SCHEMA}.exchange_rates fx ON fx.currency=o.currency
          WHERE o.history_rank=1
        ), market_prices AS (
          SELECT o.id,o.competitor_id,f.name AS offering,o.original_name,
            o.price_min AS original_price_min,o.price_max AS original_price_max,o.currency AS original_currency,
            o.price_min_eur AS price_min,o.price_max_eur AS price_max,
            o.price_type,'EUR'::text AS currency,o.fx_effective_date,o.fx_source_url,
            o.source_url,o.evidence,o.retrieved_at,
            c.country_code,cat.name AS mapped_type,
            CUME_DIST() OVER (
              PARTITION BY c.country_code,COALESCE(cat.name,'') ORDER BY o.price_min_eur
            )::numeric AS price_level
          FROM current_prices o
          JOIN {SCHEMA}.competitors c ON c.id=o.competitor_id
          JOIN {SCHEMA}.offerings f ON f.id=o.offering_id
          LEFT JOIN {SCHEMA}.categories cat ON cat.id=f.category_id
          WHERE c.vertical_id='clinics' AND o.price_min_eur IS NOT NULL
        ) SELECT * FROM market_prices WHERE competitor_id=%s
        ORDER BY offering,price_min,retrieved_at DESC""", (competitor_id,)))
    for row in prices:
        row["treatment_type"] = treatment_type(row.get("offering"), row.pop("mapped_type", None))
        row["source_label"] = display_url(row.get("source_url"))
        level = float(row.get("price_level") or 0.5)
        row["price_level_label"] = "Lower" if level <= .33 else "Higher" if level >= .67 else "Mid-market"
    for row in location_rows:
        row["source_label"] = display_url(row.get("source_url"))
    return {"competitor": {k: _clean(v) for k, v in competitor.items()}, "locations": location_rows, "prices": prices}


def chat_threads(user_key: str, limit: int = 30) -> list[dict]:
    return clean_rows(fetch_all(f"""SELECT id,title,created_at,updated_at
        FROM {SCHEMA}.chat_threads WHERE user_key=%s
        ORDER BY updated_at DESC LIMIT %s""", (user_key, min(max(limit, 1), 50))))


def create_chat_thread(user_key: str, title: str = "New chat") -> str:
    with connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"INSERT INTO {SCHEMA}.chat_threads (user_key,title) VALUES (%s,%s) RETURNING id",
            (user_key, title.strip()[:80] or "New chat"),
        )
        thread_id = str(cur.fetchone()[0])
        conn.commit()
        return thread_id


def chat_messages(user_key: str, thread_id: str) -> list[dict]:
    try:
        UUID(thread_id)
    except (TypeError, ValueError):
        return []
    return clean_rows(fetch_all(f"""SELECT m.role,m.content,m.citations,m.created_at
        FROM {SCHEMA}.chat_messages m
        JOIN {SCHEMA}.chat_threads t ON t.id=m.thread_id
        WHERE t.id=%s AND t.user_key=%s ORDER BY m.id""", (thread_id, user_key)))


def add_chat_message(
    user_key: str,
    thread_id: str,
    role: str,
    content: str,
    citations: list[dict] | None = None,
) -> bool:
    if role not in {"user", "assistant"}:
        return False
    with connection() as conn, conn.cursor() as cur:
        cur.execute(f"SELECT 1 FROM {SCHEMA}.chat_threads WHERE id=%s AND user_key=%s", (thread_id, user_key))
        if not cur.fetchone():
            return False
        cur.execute(
            f"INSERT INTO {SCHEMA}.chat_messages (thread_id,role,content,citations) VALUES (%s,%s,%s,%s)",
            (thread_id, role, content, Json(citations or [])),
        )
        cur.execute(f"UPDATE {SCHEMA}.chat_threads SET updated_at=NOW() WHERE id=%s", (thread_id,))
        conn.commit()
        return True


def candidates(country: str | None = None, state: str | None = None, limit: int = 100) -> list[dict]:
    where = ["c.vertical_id='clinics'"]
    params: dict[str, Any] = {"limit":min(max(limit,1),250)}
    if country:
        where.append("c.country_code=%(country)s"); params["country"] = country
    if state:
        where.append("c.state=%(state)s"); params["state"] = state
    return clean_rows(fetch_all(f"""SELECT c.id,c.name,c.country_code,c.official_domain,c.source_url,c.source_type,
        c.state,c.discovered_at,c.last_seen_at,COUNT(cs.id) AS source_count
        FROM {SCHEMA}.candidates c LEFT JOIN {SCHEMA}.candidate_sources cs ON cs.candidate_id=c.id
        WHERE {' AND '.join(where)} GROUP BY c.id ORDER BY c.last_seen_at DESC NULLS LAST,c.name LIMIT %(limit)s""",params))


def watchlist(country: str | None = None) -> list[dict]:
    params = {"country":country}; extra = "AND t.country_code=%(country)s" if country else ""
    return clean_rows(fetch_all(f"""SELECT t.id,t.name,t.country_code,t.segment,t.cities,t.positioning,t.capabilities,
        t.scope_score,t.focus_score,t.urls,t.active,t.priority,c.id AS competitor_id,
        COUNT(DISTINCT o.id) AS observations,MAX(o.retrieved_at) AS last_observed_at
        FROM {SCHEMA}.watchlist_targets t LEFT JOIN {SCHEMA}.competitors c ON c.id=t.competitor_id
        LEFT JOIN {SCHEMA}.observations o ON o.competitor_id=c.id
        WHERE t.active=TRUE {extra} GROUP BY t.id,c.id ORDER BY t.priority NULLS LAST,t.name""",params))


def runs(limit: int = 30) -> list[dict]:
    return clean_rows(fetch_all(f"""SELECT id,status,trigger_kind,actor,started_at,finished_at,stats,error,source_system
        FROM {SCHEMA}.collection_runs ORDER BY started_at DESC NULLS LAST LIMIT %(limit)s""",
        {"limit":min(max(limit,1),100)}))


def assistant_context(question: str, country: str | None) -> dict:
    return {
        "question": question,
        "country": country or "all EEA",
        "overview": overview(country),
        "coverage": [r for r in coverage() if not country or r["country_code"] == country][:30],
        "competitors": competitors(country, query=question if len(question) < 80 else None, limit=12),
        "observations": observations(country, query=None, limit=20),
    }
