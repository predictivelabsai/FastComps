"""Source-backed competitor detail and price drill-down."""

from __future__ import annotations

import json
from urllib.parse import urlparse

from fasthtml.common import (
    A, Article, Div, H1, H2, Header, Main, P, Script, Section, Small, Span,
    Strong, Table, Tbody, Td, Th, Thead, Tr,
)

from components.shell import app_page, mobile_menu


def _safe_url(value: str | None) -> str | None:
    if not value:
        return None
    parsed = urlparse(value)
    return value if parsed.scheme in {"http", "https"} and parsed.netloc else None


def _flag(code: str | None) -> str:
    return "".join(chr(127397 + ord(char)) for char in (code or "")) if code and len(code) == 2 else "🌍"


def _price(row: dict) -> str:
    if row.get("price_min") is None:
        return "Unavailable"
    low = f"{row['price_min']:,.2f}".rstrip("0").rstrip(".")
    high = row.get("price_max")
    spread = f"–{high:,.2f}".rstrip("0").rstrip(".") if high is not None else ""
    return f"{low}{spread} {row.get('currency') or ''}".strip()


def competitor_page(user: dict, threads: list[dict], data: dict, *, lang: str = "en"):
    competitor = data["competitor"]
    country = competitor.get("country_code") or ""
    website = _safe_url(competitor.get("website_url"))
    mapped_locations = [row for row in data["locations"] if row.get("latitude") is not None and row.get("longitude") is not None]
    map_data = json.dumps(mapped_locations, ensure_ascii=False).replace("</", "<\\/")

    header = Header(
        mobile_menu(),
        A("← Competitors", href=f"/dashboard?country={country}#competitors", cls="detail-back"),
        Span(f"{_flag(country)} {country}", cls="detail-country"),
        cls="topbar detail-topbar",
    )
    hero = Section(
        Div(
            P("CLINIC COMPETITOR", cls="eyebrow"),
            H1(competitor["name"]),
            P(competitor.get("description") or "Verified clinic competitor with retained market data.", cls="detail-lede"),
            A("Visit official website ↗", href=website, target="_blank", rel="noopener noreferrer", cls="detail-site") if website else None,
        ),
        Div(
            Article(Strong(str(competitor.get("locations") or 0)), Small("Locations")),
            Article(Strong(str(competitor.get("offerings") or 0)), Small("Treatments")),
            Article(Strong(str(competitor.get("observations") or 0)), Small("Price observations")),
            cls="detail-metrics",
        ),
        cls="detail-hero",
    )
    map_panel = Section(
        Div(P("MARKET FOOTPRINT", cls="eyebrow"), H2("Clinic locations"), cls="panel-head"),
        Div(id="competitor-map", cls="competitor-map", role="region", aria_label=f"Locations for {competitor['name']}"),
        P("Map tiles © OpenStreetMap contributors.", cls="map-attribution-note"),
        Script(map_data, type="application/json", id="competitor-map-data"),
        cls="panel detail-panel",
    ) if mapped_locations else None

    location_rows = tuple(
        Tr(
            Td(Strong(row.get("name") or competitor["name"])),
            Td(row.get("address") or "—", Div(row.get("city") or "", cls="subtext")),
            Td(row.get("phone") or "—"),
            Td(A("Source ↗", href=_safe_url(row.get("source_url")), target="_blank", rel="noopener noreferrer", cls="source-link") if _safe_url(row.get("source_url")) else "—"),
        )
        for row in data["locations"]
    )
    locations = Section(
        Div(P("ADDRESS MARKET", cls="eyebrow"), H2("Location register"), cls="panel-head"),
        Div(Table(Thead(Tr(Th("Location"), Th("Address"), Th("Phone"), Th("Market source"))), Tbody(*location_rows)), cls="table-wrap") if location_rows else P("No location records yet.", cls="empty"),
        cls="panel detail-panel",
    )
    price_rows = tuple(
        Tr(
            Td(Strong(row.get("offering") or row.get("original_name") or "Treatment"), Div(row.get("original_name") or "", cls="subtext")),
            Td(Span(row["treatment_type"], cls="badge")),
            Td(_price(row), cls="price"),
            Td(Span(row["price_level_label"], cls=f"price-level {row['price_level_label'].lower().replace('-', '')}")),
            Td(A(f"{row.get('source_label') or 'Source'} ↗", href=_safe_url(row.get("source_url")), target="_blank", rel="noopener noreferrer", cls="source-link") if _safe_url(row.get("source_url")) else "—"),
        )
        for row in data["prices"]
    )
    prices = Section(
        Div(
            Div(P("PUBLISHED PRICE MARKET", cls="eyebrow"), H2("Treatment price drill-down")),
            Span("Level is relative to published prices in the same country and currency", cls="panel-note"),
            cls="panel-head",
        ),
        Div(Table(Thead(Tr(Th("Treatment"), Th("Type"), Th("Published price"), Th("Price level"), Th("Market source"))), Tbody(*price_rows)), cls="table-wrap") if price_rows else P("No published prices retained for this provider yet.", cls="empty"),
        cls="panel detail-panel",
    )
    content = Div(
        header,
        Main(hero, map_panel, locations, prices, cls="content detail-content"),
        cls="shell-main dashboard-shell",
    )
    return app_page(
        competitor["name"], content, user=user, threads=threads, active="dashboard",
        styles=("https://unpkg.com/leaflet@1.9.4/dist/leaflet.css", "/static/market.css"),
        scripts=("https://unpkg.com/leaflet@1.9.4/dist/leaflet.js", "/static/competitor.js"),
        lang=lang,
    )
