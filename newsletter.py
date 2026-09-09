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
from repository import coverage, display_url


def _flag(country_code: str) -> str:
    code = (country_code or "").upper()
    return "".join(chr(127397 + ord(char)) for char in code) if len(code) == 2 else ""


def _source_href(value: str | None) -> str:
    try:
        parsed = urlsplit(value or "")
        return value if parsed.scheme in {"http", "https"} and parsed.netloc else PUBLIC_URL
    except ValueError:
        return PUBLIC_URL


def _signal_rows(hours: int, limit: int, *, fresh_only: bool) -> list[dict]:
    freshness = "AND o.retrieved_at >= NOW()-(%(hours)s || ' hours')::interval" if fresh_only else ""
    return fetch_all(f"""
        WITH ranked AS (
          SELECT c.name AS competitor,c.country_code,f.name AS treatment,
            COALESCE(cat.name,'Unmapped') AS treatment_type,o.price_min,o.price_max,
            o.currency,o.price_type,o.source_url,o.retrieved_at,
            ROW_NUMBER() OVER (PARTITION BY c.id ORDER BY o.retrieved_at DESC NULLS LAST,o.id) AS competitor_rank
          FROM {SCHEMA}.observations o
          JOIN {SCHEMA}.competitors c ON c.id=o.competitor_id
          JOIN {SCHEMA}.offerings f ON f.id=o.offering_id
          LEFT JOIN {SCHEMA}.categories cat ON cat.id=f.category_id
          WHERE c.vertical_id='clinics' {freshness}
        )
        SELECT * FROM ranked WHERE competitor_rank<=2
        ORDER BY retrieved_at DESC NULLS LAST,competitor,treatment LIMIT %(limit)s
    """, {"hours": hours, "limit": limit})


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
        WHERE c.vertical_id='clinics'
    """, {"hours": hours}) or {}
    signals = _signal_rows(hours, signal_limit, fresh_only=True)
    fallback = not signals
    if fallback:
        signals = _signal_rows(hours, signal_limit, fresh_only=False)
    gaps = [row for row in coverage() if row["verified"] < row["target"]]
    gaps.sort(key=lambda row: (row["progress_pct"], -row["observations"], row["country_name"]))
    return {
        "date": date.today().isoformat(),
        "hours": hours,
        "stats": stats,
        "signals": signals,
        "coverage_watch": gaps[:6],
        "fallback": fallback,
    }


def _price(signal: dict) -> str:
    if signal.get("price_min") is None:
        return "Published price unavailable"
    low = f"{float(signal['price_min']):,.2f}".rstrip("0").rstrip(".")
    high = signal.get("price_max")
    value = f"{low}–{float(high):,.2f}".rstrip("0").rstrip(".") if high is not None else low
    return f"{value} {signal.get('currency') or ''}".strip()


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
        url = html.escape(_source_href(item.get("source_url")), quote=True)
        label = html.escape(display_url(item.get("source_url")))
        signals += f"""
        <div style="border:1px solid #dce7e2;border-radius:9px;padding:12px;margin-bottom:8px;background:#fff">
          <div style="font-size:10px;color:#177357;font-weight:800;letter-spacing:.6px">{_flag(item.get('country_code') or '')} {html.escape(item.get('country_code') or 'EEA')} · {html.escape(item.get('treatment_type') or 'Unmapped')}</div>
          <div style="font-size:15px;color:#12241f;font-weight:700;margin-top:4px">{html.escape(item.get('treatment') or 'Treatment')}</div>
          <div style="font-size:11px;color:#65756f;margin-top:3px">{html.escape(item.get('competitor') or 'Clinic')} · <strong style="color:#12241f">{html.escape(_price(item))}</strong></div>
          <div style="margin-top:8px"><a href="{url}" style="color:#177357;font-size:10px;font-weight:700;text-decoration:none">{label} ↗</a></div>
        </div>"""
    gaps = ""
    for item in scan["coverage_watch"]:
        gaps += f"""<tr><td style="padding:8px 4px;border-bottom:1px solid #e8eeeb;font-size:12px;color:#12241f">{_flag(item['country_code'])} {html.escape(item['country_name'])}</td><td style="padding:8px 4px;border-bottom:1px solid #e8eeeb;font-size:12px;color:#65756f;text-align:center">{item['verified']}/{item['target']}</td><td style="padding:8px 4px;border-bottom:1px solid #e8eeeb;font-size:12px;color:#65756f;text-align:right">{item['observations']:,}</td></tr>"""
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
  <div style="padding:17px 4px 8px"><p style="font-size:13px;color:#445650;line-height:1.6;margin:0">{intro} Every signal below links to its public source.</p></div>
  <table role="presentation" style="border-collapse:collapse;width:100%;table-layout:fixed;margin:5px -5px 14px"><tr>{cards}</tr></table>
  <div style="background:#177357;border-radius:8px;padding:10px 12px;margin-bottom:9px"><div style="font-size:11px;font-weight:800;color:#fff;text-transform:uppercase;letter-spacing:.7px">Daily evidence scan · {len(scan['signals'])} signals</div></div>
  {signals or '<p style="color:#65756f;font-size:12px">No retained signals are available yet.</p>'}
  <div style="margin-top:22px;border-top:2px solid #dce7e2;padding-top:14px">
    <div style="font-size:11px;font-weight:800;color:#177357;text-transform:uppercase;letter-spacing:.7px">Coverage watch</div>
    <div style="font-size:17px;font-weight:750;color:#12241f;margin:4px 0 7px">Markets needing the next pass</div>
    <table style="border-collapse:collapse;width:100%"><tr><th style="text-align:left;font-size:9px;color:#87958f">MARKET</th><th style="text-align:center;font-size:9px;color:#87958f">VERIFIED</th><th style="text-align:right;font-size:9px;color:#87958f">OBSERVATIONS</th></tr>{gaps}</table>
  </div>
  <div style="text-align:center;margin-top:20px;padding:17px 0;border-top:1px solid #dce7e2">
    <a href="{PUBLIC_URL}/dashboard" style="background:#177357;border-radius:8px;color:#fff;display:inline-block;font-size:12px;font-weight:750;padding:11px 17px;text-decoration:none">Open FastComps dashboard →</a>
    <div style="font-size:10px;color:#94a29d;margin-top:13px">Source-backed market intelligence · Predictive Labs Ltd</div>
    <div style="font-size:9px;color:#aeb9b5;margin-top:7px">You receive this scan as a registered FastComps user. <a href="{html.escape(unsubscribe_url, quote=True)}" style="color:#7c8e87;text-decoration:underline">Unsubscribe</a></div>
  </div>
</div></body></html>"""


def render_daily_scan_text(scan: dict) -> str:
    lines = [f"FastComps Daily Clinic Market Scan — {scan['date']}", ""]
    for item in scan["signals"]:
        lines.extend((
            f"{item.get('country_code')} · {item.get('treatment_type')} · {item.get('treatment')}",
            f"{item.get('competitor')} · {_price(item)}",
            _source_href(item.get("source_url")), "",
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
