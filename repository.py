"""Read-only query layer used by the dashboard and assistant."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from db import SCHEMA, fetch_all, fetch_one


def _clean(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


def clean_rows(rows: list[dict]) -> list[dict]:
    return [{k: _clean(v) for k, v in row.items()} for row in rows]


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
        if row["verified"] >= row["target"]:
            row["coverage_status"] = "covered"
        elif row["campaign_status"] in {"queued", "running"}:
            row["coverage_status"] = "collecting"
        elif row["candidates"] or row["verified"]:
            row["coverage_status"] = "review_required"
        else:
            row["coverage_status"] = "not_started"
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
    return clean_rows(fetch_all(f"""
        SELECT o.id,c.id AS competitor_id,c.name AS competitor,c.country_code,
          f.name AS offering,o.original_name,o.price_min,o.price_max,o.price_type,o.currency,
          o.evidence,o.source_url,o.provider,o.published_at,o.retrieved_at,
          cat.name AS category
        FROM {SCHEMA}.observations o
        JOIN {SCHEMA}.competitors c ON c.id=o.competitor_id
        JOIN {SCHEMA}.offerings f ON f.id=o.offering_id
        LEFT JOIN {SCHEMA}.categories cat ON cat.id=f.category_id
        WHERE {' AND '.join(where)} ORDER BY o.retrieved_at DESC NULLS LAST,c.name,f.name LIMIT %(limit)s
    """, params))


def locations(country: str | None = None) -> list[dict]:
    params = {"country": country}
    extra = "AND l.country_code=%(country)s" if country else ""
    return clean_rows(fetch_all(f"""SELECT l.id,l.name,c.name AS competitor,l.address,l.city,l.country_code,
        l.latitude,l.longitude,l.geocode_status,l.source_url,l.evidence
        FROM {SCHEMA}.competitor_locations l JOIN {SCHEMA}.competitors c ON c.id=l.competitor_id
        WHERE l.latitude IS NOT NULL AND l.longitude IS NOT NULL {extra} ORDER BY c.name,l.city""", params))


def categories(country: str | None = None) -> list[dict]:
    params = {"country": country}
    extra = "AND comp.country_code=%(country)s" if country else ""
    return clean_rows(fetch_all(f"""SELECT COALESCE(cat.name,'Unmapped') AS category,
        COUNT(DISTINCT f.id) AS offerings,COUNT(DISTINCT o.competitor_id) AS competitors,
        COUNT(o.id) AS observations
        FROM {SCHEMA}.offerings f LEFT JOIN {SCHEMA}.categories cat ON cat.id=f.category_id
        LEFT JOIN {SCHEMA}.observations o ON o.offering_id=f.id
        LEFT JOIN {SCHEMA}.competitors comp ON comp.id=o.competitor_id
        WHERE f.vertical_id='clinics' {extra} GROUP BY COALESCE(cat.name,'Unmapped')
        ORDER BY observations DESC,category LIMIT 30""", params))


def evidence(country: str | None = None, limit: int = 30) -> list[dict]:
    params = {"limit": min(max(limit, 1), 100), "country": country}
    extra = "AND s.country_code=%(country)s" if country else ""
    return clean_rows(fetch_all(f"""SELECT s.id,s.country_code,s.provider,s.url,s.status,s.error,s.retrieved_at,
        LEFT(COALESCE(ss.content->>'title',ss.content->>'text',''),240) AS excerpt
        FROM {SCHEMA}.sources s LEFT JOIN LATERAL (
          SELECT content FROM {SCHEMA}.source_snapshots x WHERE x.source_id=s.id ORDER BY x.retrieved_at DESC NULLS LAST LIMIT 1
        ) ss ON TRUE WHERE 1=1 {extra} ORDER BY s.retrieved_at DESC NULLS LAST LIMIT %(limit)s""", params))


def assistant_context(question: str, country: str | None) -> dict:
    return {
        "question": question,
        "country": country or "all EEA",
        "overview": overview(country),
        "coverage": [r for r in coverage() if not country or r["country_code"] == country][:30],
        "competitors": competitors(country, query=question if len(question) < 80 else None, limit=12),
        "observations": observations(country, query=None, limit=20),
    }
