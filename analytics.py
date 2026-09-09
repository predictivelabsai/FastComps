"""Governed conversational analytics for FastComps.

The model may select an allowlisted metric, dimension and filters, but it never
writes or executes SQL. SQL is compiled only from the templates in this module,
executed in a read-only transaction, bounded by a statement timeout and capped
result count, and never returned to the browser.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from decimal import Decimal
from typing import Any

import httpx
from psycopg2.extras import RealDictCursor

from config import XAI_API_KEY, XAI_BASE_URL, XAI_MODEL
from db import EEA_MARKETS, SCHEMA, connection
from i18n import t


METRICS = {
    "coverage_gap": "Competitors needed to reach target",
    "competitor_count": "Verified competitors",
    "location_count": "Clinic locations",
    "observation_count": "Source-backed observations",
    "priced_observation_count": "Published price observations",
    "median_price": "Median published price",
    "candidate_count": "Discovery candidates",
    "source_count": "Retained sources",
}

DIMENSIONS = {
    "market": "Market",
    "competitor": "Competitor",
    "category": "Category",
    "offering": "Offering",
    "price_type": "Price type",
    "provider": "Source provider",
    "state": "Candidate state",
    "observation_month": "Observation month",
}

COMPATIBLE_DIMENSIONS = {
    "coverage_gap": ("market",),
    "competitor_count": ("market", "category", "offering"),
    "location_count": ("market", "competitor"),
    "observation_count": ("market", "competitor", "category", "offering", "price_type", "provider", "observation_month"),
    "priced_observation_count": ("market", "competitor", "category", "offering", "price_type", "provider", "observation_month"),
    "median_price": ("market", "competitor", "category", "offering", "price_type", "observation_month"),
    "candidate_count": ("market", "state"),
    "source_count": ("market", "provider"),
}

DEFAULT_DIMENSION = {
    "coverage_gap": "market",
    "competitor_count": "market",
    "location_count": "competitor",
    "observation_count": "category",
    "priced_observation_count": "category",
    "median_price": "offering",
    "candidate_count": "market",
    "source_count": "market",
}

COUNTRY_BY_NAME = {name.casefold(): code for code, name in EEA_MARKETS}
COUNTRY_CODES = {code for code, _ in EEA_MARKETS}


@dataclass(frozen=True)
class AnalysisPlan:
    metric: str
    dimension: str
    country: str | None = None
    search: str | None = None
    limit: int = 12

    def public(self, lang: str = "en") -> dict[str, Any]:
        data = asdict(self)
        data.update(metric_label=t(METRICS[self.metric], lang), dimension_label=t(DIMENSIONS[self.dimension], lang))
        return data


def _country_in(question: str) -> str | None:
    text = question.casefold()
    for name, code in sorted(COUNTRY_BY_NAME.items(), key=lambda item: len(item[0]), reverse=True):
        if re.search(rf"\b{re.escape(name)}\b", text):
            return code
    # Only accept explicitly upper-case country codes. Upper-casing the entire
    # question would misread ordinary words such as "is" and "in" as markets.
    return next((code for code in COUNTRY_CODES if re.search(rf"\b{code}\b", question)), None)


def _deterministic_plan(question: str, country: str | None) -> AnalysisPlan | None:
    text = question.casefold()
    inferred_country = country or _country_in(question)
    if any(term in text for term in ("coverage", "need attention", "gap", "target", "katvus", "tähelepanu", "aprėpt", "dėmesio")):
        return AnalysisPlan("coverage_gap", "market", inferred_country)
    if any(term in text for term in ("candidate", "discovery", "pipeline", "kandidaat", "kandidat")):
        return AnalysisPlan("candidate_count", "market", inferred_country)
    if any(term in text for term in ("source", "evidence", "freshness", "allikas", "tõend", "šaltin", "įrod")):
        return AnalysisPlan("source_count", "provider" if inferred_country else "market", inferred_country)
    if any(term in text for term in ("location", "footprint", "branch", "asukoht", "vieta", "filiaal")):
        return AnalysisPlan("location_count", "competitor", inferred_country)
    if any(term in text for term in ("price", "pricing", "cost", "median", "hind", "hinnad", "kaina", "kainos")):
        dimension = "market" if any(term in text for term in ("market", "country", "countries", "compare")) else "offering"
        return AnalysisPlan("median_price", dimension, inferred_country)
    if any(term in text for term in ("competitor", "clinic", "provider", "konkurent", "kliinik", "klinika")):
        return AnalysisPlan("competitor_count", "market", inferred_country)
    if any(term in text for term in ("observed", "observation", "service", "offering", "category", "raviteenus", "protseduur", "procedūr")):
        match = re.search(r"(?:where is|show|find)\s+(.+?)\s+(?:observed|available|offered)", question, re.IGNORECASE)
        search = match.group(1).strip()[:80] if match else None
        return AnalysisPlan("observation_count", "market", inferred_country, search)
    return None


def _json_object(raw: str) -> dict[str, Any]:
    text = (raw or "").strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.IGNORECASE | re.DOTALL)
    if fenced:
        text = fenced.group(1).strip()
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return {}
    try:
        value = json.loads(text[start : end + 1])
        return value if isinstance(value, dict) else {}
    except json.JSONDecodeError:
        return {}


def _normalise_plan(value: dict[str, Any], selected_country: str | None) -> AnalysisPlan | None:
    if value.get("mode") == "evidence":
        return None
    metric = str(value.get("metric") or "")
    if metric not in METRICS:
        return None
    dimension = str(value.get("dimension") or DEFAULT_DIMENSION[metric])
    if dimension not in COMPATIBLE_DIMENSIONS[metric]:
        dimension = DEFAULT_DIMENSION[metric]
    candidate_country = selected_country or str(value.get("country") or "").upper() or None
    country = candidate_country if candidate_country in COUNTRY_CODES else None
    search = re.sub(r"[\x00-\x1f]+", " ", str(value.get("search") or "")).strip()[:80] or None
    try:
        limit = max(1, min(int(value.get("limit") or 12), 20))
    except (TypeError, ValueError):
        limit = 12
    return AnalysisPlan(metric, dimension, country, search, limit)


def _model_plan(question: str, country: str | None) -> AnalysisPlan | None:
    if not XAI_API_KEY:
        return _deterministic_plan(question, country)
    system = f"""You route a clinic competitive-intelligence question to governed analytics.
Return only one JSON object. Never return SQL.
Use mode "analytics" with one metric and compatible dimension, or mode "evidence" when an
aggregate would not answer the question.
Metrics: {json.dumps(METRICS, ensure_ascii=False)}
Compatible dimensions: {json.dumps(COMPATIBLE_DIMENSIONS)}
EEA country codes: {', '.join(sorted(COUNTRY_CODES))}
Fields: mode, metric, dimension, country, search, limit. Search is only a concise clinic,
service, offering or category phrase explicitly present in the question. Limit is 1-20.
The selected country is {country or 'none'} and takes precedence over inferred geography."""
    response = httpx.post(
        f"{XAI_BASE_URL}/chat/completions",
        headers={"Authorization": f"Bearer {XAI_API_KEY}", "Content-Type": "application/json"},
        json={
            "model": XAI_MODEL,
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": question}],
        },
        timeout=25,
    )
    response.raise_for_status()
    return _normalise_plan(_json_object(response.json()["choices"][0]["message"]["content"]), country)


def plan_question(question: str, country: str | None = None, *, use_model: bool = True) -> AnalysisPlan | None:
    # Stable high-confidence intents take precedence over model routing. This
    # keeps common dashboard questions fast and prevents a model from sending a
    # clearly aggregate question down the narrative-evidence path.
    deterministic = _deterministic_plan(question, country)
    if deterministic is not None or not use_model:
        return deterministic
    try:
        return _model_plan(question, country)
    except Exception:
        return None


OBSERVATION_DIMENSIONS = {
    "market": "c.country_code",
    "competitor": "c.name",
    "category": "COALESCE(cat.name,'Unmapped')",
    "offering": "f.name",
    "price_type": "o.price_type",
    "provider": "COALESCE(o.provider,'Unknown')",
    "observation_month": "TO_CHAR(DATE_TRUNC('month',o.retrieved_at),'YYYY-MM')",
}


def _observation_query(plan: AnalysisPlan) -> tuple[str, dict[str, Any]]:
    expression = OBSERVATION_DIMENSIONS[plan.dimension]
    where = ["c.vertical_id='clinics'"]
    params: dict[str, Any] = {"limit": plan.limit}
    if plan.country:
        where.append("c.country_code=%(country)s")
        params["country"] = plan.country
    if plan.search:
        where.append("(f.name ILIKE %(search)s OR o.original_name ILIKE %(search)s OR cat.name ILIKE %(search)s OR c.name ILIKE %(search)s)")
        params["search"] = f"%{plan.search}%"
    if plan.metric in {"priced_observation_count", "median_price"}:
        where.append("o.price_min IS NOT NULL")
    if plan.metric == "observation_count":
        value = "COUNT(*)::numeric"
    elif plan.metric == "priced_observation_count":
        value = "COUNT(*)::numeric"
    elif plan.metric == "competitor_count":
        value = "COUNT(DISTINCT c.id)::numeric"
    else:
        value = "PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY o.price_min)::numeric"
    currency_select = ", o.currency" if plan.metric == "median_price" else ""
    currency_group = ", o.currency" if plan.metric == "median_price" else ""
    return f"""SELECT {expression} AS label, {value} AS value{currency_select},
        COUNT(*)::int AS evidence_count,COUNT(DISTINCT o.source_url)::int AS source_count,
        MAX(o.retrieved_at) AS latest_at
      FROM {SCHEMA}.observations o
      JOIN {SCHEMA}.competitors c ON c.id=o.competitor_id
      JOIN {SCHEMA}.offerings f ON f.id=o.offering_id
      LEFT JOIN {SCHEMA}.categories cat ON cat.id=f.category_id
      WHERE {' AND '.join(where)}
      GROUP BY {expression}{currency_group}
      ORDER BY value DESC NULLS LAST,label
      LIMIT %(limit)s""", params


def build_query(plan: AnalysisPlan) -> tuple[str, dict[str, Any]]:
    if plan.metric in {"observation_count", "priced_observation_count", "median_price"} or (
        plan.metric == "competitor_count" and plan.dimension in {"category", "offering"}
    ):
        return _observation_query(plan)
    params: dict[str, Any] = {"limit": plan.limit}
    country_where = "AND c.country_code=%(country)s" if plan.country else ""
    if plan.country:
        params["country"] = plan.country
    if plan.metric == "coverage_gap":
        country_where = "WHERE m.country_code=%(country)s" if plan.country else ""
        return f"""WITH counts AS (
            SELECT country_code,COUNT(*)::int AS verified FROM {SCHEMA}.competitors
            WHERE vertical_id='clinics' GROUP BY country_code
          ), candidates AS (
            SELECT country_code,COUNT(*)::int AS candidates FROM {SCHEMA}.candidates
            WHERE vertical_id='clinics' GROUP BY country_code
          )
          SELECT m.country_code AS label,GREATEST(m.target_competitors-COALESCE(c.verified,0),0)::numeric AS value,
            COALESCE(c.verified,0) AS verified,m.target_competitors AS target,
            COALESCE(ca.candidates,0) AS candidates,
            (COALESCE(c.verified,0)+COALESCE(ca.candidates,0))::int AS evidence_count,
            0 AS source_count,NULL::timestamptz AS latest_at
          FROM {SCHEMA}.markets m LEFT JOIN counts c USING(country_code)
          LEFT JOIN candidates ca USING(country_code) {country_where}
          ORDER BY value DESC,label LIMIT %(limit)s""", params
    if plan.metric == "competitor_count":
        search_where = ""
        if plan.search:
            search_where = "AND (c.name ILIKE %(search)s OR c.domain ILIKE %(search)s)"
            params["search"] = f"%{plan.search}%"
        return f"""SELECT c.country_code AS label,COUNT(DISTINCT c.id)::numeric AS value,
            COUNT(DISTINCT c.id)::int AS evidence_count,COUNT(DISTINCT o.source_url)::int AS source_count,
            MAX(o.retrieved_at) AS latest_at
          FROM {SCHEMA}.competitors c LEFT JOIN {SCHEMA}.observations o ON o.competitor_id=c.id
          WHERE c.vertical_id='clinics' {country_where} {search_where}
          GROUP BY c.country_code ORDER BY value DESC,label LIMIT %(limit)s""", params
    if plan.metric == "location_count":
        expression = "c.country_code" if plan.dimension == "market" else "c.name"
        search_where = ""
        if plan.search:
            search_where = "AND (c.name ILIKE %(search)s OR l.city ILIKE %(search)s)"
            params["search"] = f"%{plan.search}%"
        return f"""SELECT {expression} AS label,COUNT(*)::numeric AS value,
            COUNT(*)::int AS evidence_count,COUNT(DISTINCT l.source_url)::int AS source_count,
            MAX(l.retrieved_at) AS latest_at
          FROM {SCHEMA}.competitor_locations l JOIN {SCHEMA}.competitors c ON c.id=l.competitor_id
          WHERE c.vertical_id='clinics' {country_where} {search_where}
          GROUP BY {expression} ORDER BY value DESC,label LIMIT %(limit)s""", params
    if plan.metric == "candidate_count":
        expression = "c.country_code" if plan.dimension == "market" else "c.state"
        search_where = ""
        if plan.search:
            search_where = "AND (c.name ILIKE %(search)s OR c.official_domain ILIKE %(search)s)"
            params["search"] = f"%{plan.search}%"
        return f"""SELECT {expression} AS label,COUNT(DISTINCT c.id)::numeric AS value,
            COUNT(DISTINCT c.id)::int AS evidence_count,COUNT(DISTINCT cs.source_url)::int AS source_count,
            MAX(c.last_seen_at) AS latest_at
          FROM {SCHEMA}.candidates c LEFT JOIN {SCHEMA}.candidate_sources cs ON cs.candidate_id=c.id
          WHERE c.vertical_id='clinics' {country_where} {search_where}
          GROUP BY {expression} ORDER BY value DESC,label LIMIT %(limit)s""", params
    expression = "s.country_code" if plan.dimension == "market" else "COALESCE(s.provider,'Unknown')"
    source_country = "AND s.country_code=%(country)s" if plan.country else ""
    return f"""SELECT {expression} AS label,COUNT(*)::numeric AS value,
        COUNT(*)::int AS evidence_count,COUNT(DISTINCT s.url)::int AS source_count,
        MAX(s.retrieved_at) AS latest_at
      FROM {SCHEMA}.sources s WHERE 1=1 {source_country}
      GROUP BY {expression} ORDER BY value DESC,label LIMIT %(limit)s""", params


def _clean(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


def _execute(sql: str, params: dict[str, Any]) -> list[dict[str, Any]]:
    with connection(dict_rows=True, read_only=True) as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SET LOCAL statement_timeout = '5000ms'")
        cur.execute(sql, params)
        rows = [{key: _clean(value) for key, value in dict(row).items()} for row in cur.fetchall()]
        conn.rollback()
        return rows


def _citations(plan: AnalysisPlan) -> list[dict[str, str]]:
    params: dict[str, Any] = {}
    where = ["c.vertical_id='clinics'", "o.source_url IS NOT NULL"]
    if plan.country:
        where.append("c.country_code=%(country)s")
        params["country"] = plan.country
    if plan.search:
        where.append("(f.name ILIKE %(search)s OR o.original_name ILIKE %(search)s OR c.name ILIKE %(search)s)")
        params["search"] = f"%{plan.search}%"
    sql = f"""SELECT DISTINCT ON (o.source_url) o.source_url,c.name AS competitor,f.name AS offering
      FROM {SCHEMA}.observations o JOIN {SCHEMA}.competitors c ON c.id=o.competitor_id
      JOIN {SCHEMA}.offerings f ON f.id=o.offering_id
      WHERE {' AND '.join(where)} ORDER BY o.source_url,o.retrieved_at DESC NULLS LAST LIMIT 6"""
    return [
        {"label": f"{row['competitor']} — {row['offering']}", "url": row["source_url"]}
        for row in _execute(sql, params)
    ]


def execute_plan(plan: AnalysisPlan, lang: str = "en") -> dict[str, Any]:
    sql, params = build_query(plan)
    rows = _execute(sql, params)
    evidence_count = sum(int(row.get("evidence_count") or 0) for row in rows)
    source_count = sum(int(row.get("source_count") or 0) for row in rows)
    latest = max((row.get("latest_at") for row in rows if row.get("latest_at")), default=None)
    public_rows = [
        {
            "label": str(row.get("label") or "Unknown") + (f" · {row.get('currency')}" if row.get("currency") else ""),
            "value": float(row.get("value") or 0),
            "evidence_count": int(row.get("evidence_count") or 0),
            "source_count": int(row.get("source_count") or 0),
        }
        for row in rows
    ]
    top = public_rows[:3]
    leaders = ", ".join(f"{row['label']} ({row['value']:,.2f})" for row in top) or t("no matching records", lang)
    scope = plan.country or t("the 30 EEA markets", lang)
    from repository import coverage

    coverage_rows = [row for row in coverage() if not plan.country or row["country_code"] == plan.country]
    coverage_counts = {
        status: sum(row["coverage_status"] == status for row in coverage_rows)
        for status in ("covered", "running", "queued", "review_required", "not_started", "failed")
    }
    summary = t(
        "For {scope}, {metric} by {dimension} is led by {leaders}. This governed analysis uses {records} underlying records across {sources} retained source references.",
        lang, scope=scope, metric=t(METRICS[plan.metric], lang).lower(), dimension=t(DIMENSIONS[plan.dimension], lang).lower(),
        leaders=leaders, records=f"{evidence_count:,}", sources=f"{source_count:,}",
    )
    if plan.metric == "median_price":
        summary += " " + t("Currency is kept separate so unlike prices are never combined.", lang)
    summary += " " + t(
        "Coverage: {covered} covered, {running} running, {queued} queued, {review} requiring review, {not_started} not started and {failed} failed.",
        lang, covered=coverage_counts["covered"], running=coverage_counts["running"], queued=coverage_counts["queued"],
        review=coverage_counts["review_required"], not_started=coverage_counts["not_started"], failed=coverage_counts["failed"],
    )
    return {
        "plan": plan.public(lang),
        "summary": summary,
        "rows": public_rows,
        "visual": {
            "kind": "bar",
            "title": t("{metric} by {dimension}", lang, metric=t(METRICS[plan.metric], lang), dimension=t(DIMENSIONS[plan.dimension], lang)),
            "rows": public_rows[:10],
        },
        "citations": _citations(plan),
        "evidence": {
            "records": evidence_count, "sources": source_count, "latest_at": latest,
            "coverage": coverage_counts, "markets": len(coverage_rows),
        },
    }
