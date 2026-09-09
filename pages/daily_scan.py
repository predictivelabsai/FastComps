"""Authenticated Daily Clinic Market Scan page."""

from __future__ import annotations

import base64
from datetime import date
from urllib.parse import urlsplit

from fasthtml.common import (
    A, Article, Div, H1, H2, Header, Img, Main, P, Section, Small, Span,
    Strong,
)

from components.shell import app_page, mobile_menu
from i18n import t
from market_map import render_market_map_png


def _safe_url(value: str | None) -> str | None:
    try:
        parsed = urlsplit(value or "")
        return value if parsed.scheme in {"http", "https"} and parsed.netloc else None
    except ValueError:
        return None


def _flag(code: str | None) -> str:
    code = (code or "").upper()
    return "".join(chr(127397 + ord(char)) for char in code) if len(code) == 2 else "🌍"


def _money(value) -> str:
    if value is None:
        return "—"
    return f"€{float(value):,.2f}".rstrip("0").rstrip(".")


def _endpoint(label: str, clinic: str | None, price, source_url: str | None):
    clinic_name = clinic or "Clinic"
    href = _safe_url(source_url)
    clinic_node = (
        A(f"{clinic_name} ↗", href=href, target="_blank", rel="noopener noreferrer")
        if href else Span(clinic_name)
    )
    return Div(
        Span(label, cls="scan-endpoint-label"),
        Div(clinic_node, Strong(_money(price)), cls="scan-endpoint-value"),
        cls="scan-endpoint",
    )


def daily_scan_page(user: dict, threads: list[dict], scan: dict, *, lang: str = "en"):
    signals = scan.get("signals") or []
    png = base64.b64encode(render_market_map_png(scan)).decode("ascii")
    stats = scan.get("stats") or {}
    scan_date = date.fromisoformat(scan["date"]).strftime("%d %b %Y")

    cards = tuple(
        Article(
            Div(
                Span(f"{_flag(row.get('country_code'))} {row.get('country_code') or 'EEA'}", cls="scan-market"),
                Span(row.get("treatment_type") or "General medicine & other treatments", cls="scan-type"),
                cls="scan-card-meta",
            ),
            H2(row.get("treatment") or "Treatment"),
            P(
                t("Comparable published prices across {count} clinics", lang, count=int(row.get("clinic_count") or 0)),
                cls="scan-card-note",
            ),
            _endpoint("LOWEST", row.get("lowest_clinic"), row.get("lowest_price"), row.get("lowest_source_url")),
            _endpoint("HIGHEST", row.get("highest_clinic"), row.get("highest_price"), row.get("highest_source_url")),
            cls="scan-card",
        )
        for row in signals
    )
    metrics = tuple(
        Div(Strong(f"{int(value or 0):,}"), Small(label), cls="scan-metric")
        for label, value in (
            ("Observations", stats.get("observations")),
            ("Competitors", stats.get("competitors")),
            ("Markets", stats.get("markets")),
            ("Sources", stats.get("sources")),
        )
    )
    content = Div(
        Header(
            mobile_menu(),
            Div(Span("DAILY CLINIC MARKET SCAN", cls="eyebrow"), Strong(scan_date)),
            Span(user["email"], cls="signed-in"),
            cls="topbar scan-topbar",
        ),
        Main(
            Section(
                P("INTELLIGENCE · CROSS-CLINIC BENCHMARKS", cls="eyebrow"),
                H1("Daily evidence scan"),
                P(
                    "A country-first view of comparable published treatment prices. "
                    "Every lowest and highest endpoint comes from a different clinic and links to its source."
                ),
                cls="scan-hero",
            ),
            Section(*metrics, cls="scan-metrics"),
            Section(
                Div(
                    Div(P("PRICE LANDSCAPE", cls="eyebrow"), H2("Country → treatment type → treatment")),
                    Span("All displayed prices are converted to EUR", cls="scan-panel-note"),
                    cls="scan-panel-head",
                ),
                Img(
                    src=f"data:image/png;base64,{png}",
                    alt="Daily country, treatment type and treatment price map",
                    cls="scan-map",
                ),
                cls="scan-panel",
            ),
            Section(
                Div(
                    Div(P("VERIFIABLE SIGNALS", cls="eyebrow"), H2(t("{count} cross-clinic comparisons", lang, count=len(signals)))),
                    Span("LOWEST and HIGHEST always use different clinics", cls="scan-panel-note"),
                    cls="scan-panel-head",
                ),
                Div(*cards, cls="scan-grid") if cards else P("No comparable cross-clinic price signals are available yet.", cls="scan-empty"),
                cls="scan-panel",
            ),
            cls="scan-content",
        ),
        cls="shell-main daily-scan-shell",
    )
    return app_page(
        "Daily Scan", content, user=user, threads=threads, active="daily-scan",
        styles=("/static/daily_scan.css",), lang=lang,
    )
