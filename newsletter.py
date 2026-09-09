"""Source-backed FastComps Daily Scan generation and Postmark delivery."""

from __future__ import annotations

import html
import os
from datetime import date
from urllib.parse import urlsplit

import httpx
from itsdangerous import BadSignature, URLSafeSerializer
from psycopg2.extras import RealDictCursor

from config import PUBLIC_URL, SESSION_SECRET
from db import SCHEMA, connection, fetch_all, fetch_one
from repository import treatment_type


def _flag(country_code: str) -> str:
    code = (country_code or "").upper()
    return "".join(chr(127397 + ord(char)) for char in code) if len(code) == 2 else ""


def _source_href(value: str | None) -> str:
    try:
        parsed = urlsplit(value or "")
        return value if parsed.scheme in {"http", "https"} and parsed.netloc else PUBLIC_URL
    except ValueError:
        return PUBLIC_URL


def _signal_rows(hours: int, limit: int, *, fresh_only: bool, country: str | None = None) -> list[dict]:
    freshness = "AND o.retrieved_at >= NOW()-(%(hours)s || ' hours')::interval" if fresh_only else ""
    country_filter = "AND c.country_code=%(country)s" if country else ""
    rows = fetch_all(f"""
        WITH history_ranked AS (
          SELECT c.id AS competitor_id,c.name AS competitor,c.country_code,f.name AS treatment,
            COALESCE(cat.name,'') AS mapped_type,
            ROUND(o.price_min/fx.units_per_eur,2) AS price_min,
            ROUND(COALESCE(o.price_max,o.price_min)/fx.units_per_eur,2) AS high_price,
            o.source_url,o.retrieved_at,fx.effective_date AS fx_effective_date,
            ROW_NUMBER() OVER (PARTITION BY c.id,f.id,COALESCE(o.original_name,''),o.currency
              ORDER BY o.retrieved_at DESC NULLS LAST,o.id DESC) AS history_rank
          FROM {SCHEMA}.observations o
          JOIN {SCHEMA}.competitors c ON c.id=o.competitor_id
          JOIN {SCHEMA}.offerings f ON f.id=o.offering_id
          LEFT JOIN {SCHEMA}.categories cat ON cat.id=f.category_id
          JOIN {SCHEMA}.exchange_rates fx ON fx.currency=o.currency
          WHERE c.vertical_id='clinics' AND o.price_min IS NOT NULL
            AND COALESCE(o.currency,'')<>'' {freshness} {country_filter}
        ), clinic_ranked AS (
          SELECT *,
            ROW_NUMBER() OVER (PARTITION BY country_code,competitor_id,treatment
              ORDER BY price_min,retrieved_at DESC NULLS LAST,competitor) AS low_rank,
            ROW_NUMBER() OVER (PARTITION BY country_code,competitor_id,treatment
              ORDER BY high_price DESC,retrieved_at DESC NULLS LAST,competitor) AS high_rank
          FROM history_ranked WHERE history_rank=1
        ), clinic_benchmarks AS (
          SELECT country_code,competitor_id,competitor,treatment,MAX(mapped_type) AS mapped_type,
            MIN(price_min) AS lowest_price,MAX(high_price) AS highest_price,
            MAX(source_url) FILTER (WHERE low_rank=1) AS lowest_source_url,
            MAX(source_url) FILTER (WHERE high_rank=1) AS highest_source_url,
            MAX(retrieved_at) AS retrieved_at,MAX(fx_effective_date) AS fx_effective_date,
            COUNT(DISTINCT source_url)::int AS source_count
          FROM clinic_ranked
          GROUP BY country_code,competitor_id,competitor,treatment
        ), ranked AS (
          SELECT *,
            ROW_NUMBER() OVER (PARTITION BY country_code,treatment
              ORDER BY lowest_price,retrieved_at DESC NULLS LAST,competitor) AS low_rank,
            ROW_NUMBER() OVER (PARTITION BY country_code,treatment
              ORDER BY highest_price DESC,retrieved_at DESC NULLS LAST,competitor) AS high_rank
          FROM clinic_benchmarks
        ), benchmarks AS (
          SELECT country_code,treatment,MAX(mapped_type) AS mapped_type,'EUR'::text AS currency,
            MIN(lowest_price) AS lowest_price,MAX(highest_price) AS highest_price,
            MAX(retrieved_at) AS retrieved_at,MAX(fx_effective_date) AS fx_effective_date,
            COUNT(DISTINCT competitor_id)::int AS clinic_count,SUM(source_count)::int AS source_count,
            MAX(competitor) FILTER (WHERE low_rank=1) AS lowest_clinic,
            MAX(lowest_source_url) FILTER (WHERE low_rank=1) AS lowest_source_url,
            MAX(competitor) FILTER (WHERE high_rank=1) AS highest_clinic,
            MAX(highest_source_url) FILTER (WHERE high_rank=1) AS highest_source_url
          FROM ranked GROUP BY country_code,treatment
        )
        SELECT * FROM benchmarks
        ORDER BY retrieved_at DESC NULLS LAST,clinic_count DESC,treatment
        LIMIT %(limit)s
    """, {"hours": hours, "limit": limit, "country": country})
    for row in rows:
        row["treatment_type"] = treatment_type(row.get("treatment"), row.pop("mapped_type", None))
    return rows


def build_daily_scan(*, hours: int = 36, signal_limit: int = 10) -> dict:
    hours = min(168, max(1, hours))
    signal_limit = min(20, max(1, signal_limit))
    stats = fetch_one(f"""
        SELECT COUNT(*) FILTER (WHERE o.retrieved_at>=NOW()-(%(hours)s || ' hours')::interval) AS observations,
          COUNT(DISTINCT o.competitor_id) FILTER (WHERE o.retrieved_at>=NOW()-(%(hours)s || ' hours')::interval) AS competitors,
          COUNT(DISTINCT c.country_code) FILTER (WHERE o.retrieved_at>=NOW()-(%(hours)s || ' hours')::interval) AS markets,
          COUNT(DISTINCT o.source_url) FILTER (WHERE o.retrieved_at>=NOW()-(%(hours)s || ' hours')::interval) AS sources,
          MAX(o.retrieved_at) AS latest_at
        FROM {SCHEMA}.observations o JOIN {SCHEMA}.competitors c ON c.id=o.competitor_id
        JOIN {SCHEMA}.exchange_rates fx ON fx.currency=o.currency
        WHERE c.vertical_id='clinics' AND o.price_min IS NOT NULL AND COALESCE(o.currency,'')<>''
    """, {"hours": hours}) or {}
    candidate_limit = min(120, max(signal_limit * 6, signal_limit))
    candidates = _signal_rows(hours, candidate_limit, fresh_only=True)
    fallback = not candidates
    if fallback:
        candidates = _signal_rows(hours, candidate_limit, fresh_only=False)
    # Keep Lithuania as the lead market even on a day when its last retained
    # benchmark falls just outside the freshness window.
    preferred_fallback = False
    lithuania = [row for row in candidates if row.get("country_code") == "LT"][:min(3, signal_limit)]
    if not lithuania:
        lithuania = _signal_rows(hours, min(3, signal_limit), fresh_only=False, country="LT")
        if lithuania:
            preferred_fallback = True
    preferred_keys = {(row.get("country_code"), row.get("treatment"), row.get("currency")) for row in lithuania}
    other_markets = [row for row in candidates if row.get("country_code") != "LT"]
    remaining_lt = [
        row for row in candidates
        if row.get("country_code") == "LT"
        and (row.get("country_code"), row.get("treatment"), row.get("currency")) not in preferred_keys
    ]
    signals = (lithuania + other_markets + remaining_lt)[:signal_limit]
    fx_dates = [str(row["fx_effective_date"]) for row in signals if row.get("fx_effective_date")]
    return {
        "date": date.today().isoformat(),
        "hours": hours,
        "stats": stats,
        "signals": signals,
        "fallback": fallback,
        "preferred_fallback": preferred_fallback,
        "fx_effective_date": max(fx_dates, default=None),
    }


def _money(value, currency: str = "") -> str:
    if value is None:
        return "—"
    amount = f"{float(value):,.2f}".rstrip("0").rstrip(".")
    return f"{amount} {currency}".strip()


def _unsubscribe_serializer() -> URLSafeSerializer:
    return URLSafeSerializer(SESSION_SECRET, salt="fastcomps-daily-scan")


def unsubscribe_token(email: str) -> str:
    return _unsubscribe_serializer().dumps(email.strip().lower())


def unsubscribe(token: str) -> str | None:
    try:
        email = str(_unsubscribe_serializer().loads(token)).strip().lower()
    except BadSignature:
        return None
    with connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"UPDATE {SCHEMA}.users SET daily_scan_enabled=FALSE,updated_at=NOW() WHERE lower(email)=%s RETURNING email",
            (email,),
        )
        row = cur.fetchone()
        conn.commit()
    return str(row[0]) if row else None


def render_daily_scan_html(scan: dict, *, recipient_email: str) -> str:
    stats = scan["stats"]
    cards = "".join(
        f"""<td style="width:25%;padding:5px;vertical-align:top"><div style="background:#fff;border:1px solid #dce7e2;border-radius:8px;padding:11px 8px;text-align:center"><div style="font:600 21px Georgia,serif;color:#12241f">{int(value or 0):,}</div><div style="font-size:9px;color:#65756f;text-transform:uppercase;letter-spacing:.5px;margin-top:3px">{label}</div></div></td>"""
        for label, value in (
            ("observations", stats.get("observations")), ("competitors", stats.get("competitors")),
            ("markets", stats.get("markets")), ("sources", stats.get("sources")),
        )
    )
    signals = ""
    for item in scan["signals"]:
        low_url = html.escape(_source_href(item.get("lowest_source_url")), quote=True)
        high_url = html.escape(_source_href(item.get("highest_source_url")), quote=True)
        low_clinic = html.escape(item.get("lowest_clinic") or "Clinic")
        high_clinic = html.escape(item.get("highest_clinic") or "Clinic")
        currency = item.get("currency") or ""
        signals += f"""
        <div style="border:1px solid #dce7e2;border-radius:9px;padding:12px;margin-bottom:8px;background:#fff">
          <div style="font-size:10px;color:#177357;font-weight:800;letter-spacing:.6px">{_flag(item.get('country_code') or '')} {html.escape(item.get('country_code') or 'EEA')} · {html.escape(item.get('treatment_type') or 'General medicine & other treatments')}</div>
          <div style="font-size:15px;color:#12241f;font-weight:700;margin-top:4px">{html.escape(item.get('treatment') or 'Treatment')}</div>
          <div style="font-size:10px;color:#65756f;margin:3px 0 8px">Published benchmark across {int(item.get('clinic_count') or 0)} clinic{'s' if int(item.get('clinic_count') or 0) != 1 else ''}</div>
          <table role="presentation" style="border-collapse:collapse;width:100%">
            <tr><td style="padding:6px 0;border-top:1px solid #edf2ef;font-size:10px;color:#65756f">LOWEST</td><td style="padding:6px 8px;border-top:1px solid #edf2ef;font-size:11px"><a href="{low_url}" style="color:#177357;font-weight:700;text-decoration:none">{low_clinic} ↗</a></td><td style="padding:6px 0;border-top:1px solid #edf2ef;text-align:right;font-size:12px;color:#12241f;font-weight:800">{html.escape(_money(item.get('lowest_price'), currency))}</td></tr>
            <tr><td style="padding:6px 0;border-top:1px solid #edf2ef;font-size:10px;color:#65756f">HIGHEST</td><td style="padding:6px 8px;border-top:1px solid #edf2ef;font-size:11px"><a href="{high_url}" style="color:#177357;font-weight:700;text-decoration:none">{high_clinic} ↗</a></td><td style="padding:6px 0;border-top:1px solid #edf2ef;text-align:right;font-size:12px;color:#12241f;font-weight:800">{html.escape(_money(item.get('highest_price'), currency))}</td></tr>
          </table>
        </div>"""
    scan_date = date.fromisoformat(scan["date"]).strftime("%d %b %Y")
    intro = (
        f"Fresh evidence retained during the last {scan['hours']} hours."
        if not scan["fallback"] else "No new evidence landed in the freshness window, so today’s scan shows the latest retained signals."
    )
    unsubscribe_url = f"{PUBLIC_URL}/auth/unsubscribe?token={unsubscribe_token(recipient_email)}"
    return f"""<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#f3f7f5;font-family:-apple-system,'Segoe UI',Arial,sans-serif;-webkit-text-size-adjust:100%">
<div style="max-width:640px;margin:0 auto;padding:0 12px">
  <div style="background:#12241f;padding:22px 16px;text-align:center;border-radius:0 0 10px 10px">
    <div style="font-size:23px;font-weight:800;color:#fff;letter-spacing:-.5px">Fast<span style="color:#63c39c">Comps</span></div>
    <div style="font-size:13px;color:#b7c9c1;margin-top:4px">Daily Clinic Market Scan · 30 EEA markets</div>
    <div style="font-size:11px;color:#7f978d;margin-top:3px">{scan_date}</div>
  </div>
  <div style="padding:17px 4px 8px"><p style="font-size:13px;color:#445650;line-height:1.6;margin:0">{intro} Every signal below links to its public source. Prices are converted to EUR using <a href="https://www.ecb.europa.eu/stats/policy_and_exchange_rates/euro_reference_exchange_rates/html/index.en.html" style="color:#177357">ECB reference rates</a>{f' effective {html.escape(str(scan["fx_effective_date"]))}' if scan.get('fx_effective_date') else ''}; original prices remain retained as evidence.</p></div>
  <table role="presentation" style="border-collapse:collapse;width:100%;table-layout:fixed;margin:5px -5px 14px"><tr>{cards}</tr></table>
  <div style="background:#177357;border-radius:8px;padding:10px 12px;margin-bottom:9px"><div style="font-size:11px;font-weight:800;color:#fff;text-transform:uppercase;letter-spacing:.7px">Daily evidence scan · {len(scan['signals'])} signals</div></div>
  {signals or '<p style="color:#65756f;font-size:12px">No retained signals are available yet.</p>'}
  <div style="text-align:center;margin-top:20px;padding:17px 0;border-top:1px solid #dce7e2">
    <a href="{PUBLIC_URL}/dashboard" style="background:#177357;border-radius:8px;color:#fff;display:inline-block;font-size:12px;font-weight:750;padding:11px 17px;text-decoration:none">Open FastComps dashboard →</a>
    <div style="font-size:10px;color:#94a29d;margin-top:13px">Source-backed market intelligence · Predictive Labs Ltd</div>
    <div style="font-size:9px;color:#aeb9b5;margin-top:7px">You receive this scan as a registered FastComps user. <a href="{html.escape(unsubscribe_url, quote=True)}" style="color:#7c8e87;text-decoration:underline">Unsubscribe</a></div>
  </div>
</div></body></html>"""


def render_daily_scan_text(scan: dict) -> str:
    fx_note = f" (effective {scan['fx_effective_date']})" if scan.get("fx_effective_date") else ""
    lines = [f"FastComps Daily Clinic Market Scan — {scan['date']}",
             f"All prices converted to EUR using ECB reference rates{fx_note}; original prices are retained.", ""]
    for item in scan["signals"]:
        lines.extend((
            f"{item.get('country_code')} · {item.get('treatment_type')} · {item.get('treatment')}",
            f"Lowest: {item.get('lowest_clinic')} · {_money(item.get('lowest_price'), item.get('currency') or '')}",
            _source_href(item.get("lowest_source_url")),
            f"Highest: {item.get('highest_clinic')} · {_money(item.get('highest_price'), item.get('currency') or '')}",
            _source_href(item.get("highest_source_url")), "",
        ))
    lines.extend(("Open FastComps:", f"{PUBLIC_URL}/dashboard"))
    return "\n".join(lines)


def registered_recipients() -> list[str]:
    with connection(read_only=True) as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(f"""SELECT DISTINCT lower(email) AS email FROM {SCHEMA}.users
            WHERE email IS NOT NULL AND email<>'' AND daily_scan_enabled=TRUE
              AND (email_verified=TRUE OR google_sub IS NOT NULL OR password_hash IS NULL)
            ORDER BY email""")
        return [str(row["email"]) for row in cur.fetchall()]


def _record_delivery(email: str, status: str, *, message_id: str = "", error: str = "") -> None:
    with connection() as conn, conn.cursor() as cur:
        cur.execute(f"""INSERT INTO {SCHEMA}.newsletter_deliveries (scan_date,email,status,message_id,error)
            VALUES (CURRENT_DATE,%s,%s,%s,%s)
            ON CONFLICT (scan_date,email) DO UPDATE SET status=EXCLUDED.status,
              message_id=EXCLUDED.message_id,error=EXCLUDED.error,created_at=NOW()""",
            (email.lower(), status, message_id or None, error[:500] or None),
        )
        conn.commit()


def _delivered_today() -> set[str]:
    with connection(read_only=True) as conn, conn.cursor() as cur:
        cur.execute(f"SELECT lower(email) FROM {SCHEMA}.newsletter_deliveries WHERE scan_date=CURRENT_DATE AND status='sent'")
        return {str(row[0]) for row in cur.fetchall()}


def send_daily_scan(to_email: str, *, scan: dict | None = None, record: bool = False) -> dict:
    token = os.getenv("POSTMARK_API_TOKEN", "")
    if not token:
        return {"ok": False, "error": "POSTMARK_API_TOKEN is not configured"}
    scan = scan or build_daily_scan()
    subject = f"Daily Clinic Market Scan · FastComps — {date.today().strftime('%d %b %Y')}"
    try:
        response = httpx.post(
            "https://api.postmarkapp.com/email",
            headers={"X-Postmark-Server-Token": token, "Accept": "application/json"},
            json={
                "From": f"FastComps <{os.getenv('FROM_EMAIL', 'info@fastsme.com')}>",
                "To": to_email, "Subject": subject,
                "HtmlBody": render_daily_scan_html(scan, recipient_email=to_email),
                "TextBody": render_daily_scan_text(scan), "Tag": "fastcomps-daily-scan",
                "MessageStream": "outbound",
            },
            timeout=20,
        )
        response.raise_for_status()
        payload = response.json()
        if payload.get("ErrorCode", 0) != 0:
            raise RuntimeError(str(payload.get("Message") or "Postmark rejected the message"))
        result = {"ok": True, "to": to_email, "message_id": payload.get("MessageID", "")}
        if record:
            _record_delivery(to_email, "sent", message_id=result["message_id"])
        return result
    except (httpx.HTTPError, RuntimeError, ValueError) as exc:
        if record:
            _record_delivery(to_email, "failed", error=type(exc).__name__)
        return {"ok": False, "to": to_email, "error": type(exc).__name__}


def send_daily_scan_to_all() -> dict:
    recipients = registered_recipients()
    delivered = _delivered_today()
    pending = [email for email in recipients if email not in delivered]
    scan = build_daily_scan()
    results = [send_daily_scan(email, scan=scan, record=True) for email in pending]
    return {
        "ok": all(item["ok"] for item in results),
        "sent": sum(1 for item in results if item["ok"]),
        "total": len(recipients),
        "skipped": len(recipients) - len(pending),
        "results": results,
    }
