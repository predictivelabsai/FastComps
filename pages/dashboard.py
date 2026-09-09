"""FastHTML market dashboard."""

from __future__ import annotations

from fasthtml.common import (
    Aside, Button, Div, Form, H1, H2, Header, Input, Label, Main, Nav,
    Option, P, Section, Select, Span, Table, Tbody, Td, Textarea, Th,
    Thead, Tr,
)

from components.shell import app_page, mobile_menu


def _table(columns: tuple[str, ...], body_id: str):
    return Div(
        Table(Thead(Tr(*(Th(column) for column in columns))), Tbody(id=body_id)),
        cls="table-wrap",
    )


def _heading(eyebrow: str, title: str):
    return Div(P(eyebrow, cls="eyebrow"), H2(title))


def dashboard_page(user: dict, threads: list[dict], *, lang: str = "en"):
    topbar = Header(
        mobile_menu(),
        Nav(
            Button("Overview", data_view="overview", cls="nav-button active"),
            Button("Competitors", data_view="competitors", cls="nav-button"),
            Button("Market map", data_view="map", cls="nav-button"),
            Button("Coverage", data_view="coverage", cls="nav-button"),
            Button("Market", data_view="market", cls="nav-button"),
        ),
        Div(
            Label(Span("Market"), Select(Option("All EEA", value=""), id="country"), cls="market-picker"),
            Span(user["email"], cls="signed-in"), cls="header-actions",
        ),
        cls="topbar",
    )
    overview = (
        Section(
            Div(
                _heading("TREATMENT PRICE LANDSCAPE", "Country → treatment type → treatment"),
                Span("Size = observations · Colour = relative published price level", cls="panel-note"),
                cls="panel-head",
            ),
            Div(P("Loading treatment treemap…", cls="empty"), id="treatment-treemap", cls="treatment-treemap"),
            P("Select a treatment tile to drill into its matching market prices.", id="treemap-drilldown", cls="treemap-drilldown"),
            Div(Span("Lower price level"), Span(cls="gradient"), Span("Higher price level"), P("Compared within each country and currency"), cls="treemap-legend"),
            cls="panel view-panel", data_panel="overview",
        ),
        Section(
            Div(
                _heading("LATEST MARKET", "Observed services & prices"),
                Input(id="price-search", cls="compact-input", placeholder="Filter service or clinic"),
                cls="panel-head",
            ),
            _table(("Competitor", "Offering", "Price", "Type", "Country", "Market"), "prices"),
            cls="panel view-panel", data_panel="overview",
        ),
    )
    competitors = Section(
        Div(
            _heading("LANDSCAPE", "Competitors"),
            Input(id="competitor-search", cls="compact-input", placeholder="Search competitors"),
            cls="panel-head",
        ),
        Div(id="country-filter-bar", cls="country-filter-bar", aria_label="Filter competitors by country"),
        _table(("Competitor", "Country", "Locations", "Offerings", "Market", "Last observed"), "competitors"),
        cls="panel view-panel hidden", data_panel="competitors",
    )
    market_map = Section(
        Div(
            _heading("CLINIC LOCATIONS", "Market map"),
            Span("OpenStreetMap · select a marker for provider market data", cls="panel-note"),
            cls="panel-head",
        ),
        Div(id="market-map-summary", cls="market-map-summary"),
        Div(id="market-map", cls="market-map", role="region", aria_label="Interactive competitor clinic map"),
        P("Location records retain their original source URL. Map tiles © OpenStreetMap contributors.", cls="map-attribution-note"),
        cls="panel view-panel hidden", data_panel="map",
    )
    coverage = Section(
        Div(_heading("30 EEA MARKETS", "Coverage status"), Span("Target: 10 verified competitors / market", cls="panel-note"), cls="panel-head"),
        Div(id="coverage-grid", cls="coverage-grid"),
        Div(_heading("CURATED MONITORING", "Priority watchlist"), cls="subpanel-head"),
        Div(id="watchlist-grid", cls="watchlist-grid"),
        Div(_heading("DISCOVERY PIPELINE", "Candidate queue"), Span("Every lead retained for review", cls="panel-note"), cls="subpanel-head"),
        _table(("Candidate", "Market", "State", "Sources", "Last seen"), "candidates"),
        cls="panel view-panel hidden", data_panel="coverage",
    )
    market = Section(
        Div(_heading("SOURCE REGISTER", "Recent market data"), Span("Retained snapshots", cls="panel-note"), cls="panel-head"),
        Div(id="market-list", cls="market-list"),
        Div(_heading("COLLECTION HISTORY", "Recent runs"), cls="subpanel-head"),
        _table(("Run", "Trigger", "Status", "Started", "Result"), "runs"),
        cls="panel view-panel hidden", data_panel="market",
    )
    analyst = Aside(
        Div(Span("✦", cls="assistant-mark"), _heading("FASTCOMPS AI", "Market analyst"), Span("LIVE", cls="live-dot"), cls="assistant-head"),
        Div(
            Div(P("Ask about this dashboard’s competitors, coverage, treatments or prices. I’ll keep the market context visible."), cls="assistant-message"),
            Div(
                Button("Which markets need attention?", type="button"),
                Button("Compare clinic pricing in Lithuania", type="button"),
                Button("Where is IV therapy observed?", type="button"), cls="suggestions",
            ),
            id="assistant-feed", cls="assistant-feed", aria_live="polite",
        ),
        Form(
            Textarea(id="question", rows="2", maxlength="500", placeholder="Ask about this dashboard…", required=True),
            Button("↑", type="submit", aria_label="Send question"), id="assistant-form", cls="assistant-form",
        ),
        P("Read-only governed analytics · No SQL exposed", cls="assistant-foot"),
        cls="assistant",
    )
    content = Div(
        topbar,
        Main(
            Section(
                Div(
                    Div(P("CLINICS · COMPETITIVE INTELLIGENCE", cls="eyebrow"), H1("See the market, not the noise."), P("Track competitors, service portfolios and published prices across 30 EEA markets—each claim linked back to its source.")),
                    Div(Span(cls="status-dot"), Span("Connecting to market data…", id="sync-status"), cls="sync-pill"),
                    cls="intro",
                ),
                Section(*(Div(cls="skeleton") for _ in range(4)), id="metrics", cls="metrics"),
                *overview, competitors, market_map, coverage, market,
                cls="content",
            ),
            analyst,
            cls="workspace",
        ),
        cls="shell-main dashboard-shell",
    )
    return app_page(
        "Dashboard", content, user=user, threads=threads, active="dashboard",
        styles=("https://unpkg.com/leaflet@1.9.4/dist/leaflet.css", "/static/market.css"),
        scripts=("https://unpkg.com/leaflet@1.9.4/dist/leaflet.js", "https://cdn.plot.ly/plotly-2.35.2.min.js", "/static/app.js"),
        lang=lang,
    )
