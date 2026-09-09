"""FastHTML developer portal."""

from __future__ import annotations

from fasthtml.common import A, Article, Aside, Body, Code, Div, H1, H2, H3, Header, Html, Main, Nav, P, Pre, Section, Strong

from components.shell import app_page, mobile_menu
from pages.landing import public_footer, public_head, public_nav


RESOURCES = (
    ("Market overview", "Read verified competitors, locations, observations and retained sources.", "GET", "/api/overview"),
    ("Treatment treemap", "Country → treatment type → treatment, sized by observations and coloured by relative price level.", "GET", "/api/treemap"),
    ("Competitors", "Search verified clinic competitors and their attributable footprint.", "GET", "/api/competitors"),
    ("Competitor detail", "Drill into a provider’s locations, treatment prices and relative price levels.", "GET", "/api/competitors/{competitor_id}"),
    ("Clinic locations", "Read geocoded, source-backed provider locations used by the market map.", "GET", "/api/locations"),
    ("Price observations", "Read captured treatments, prices, currencies and readable market links.", "GET", "/api/observations"),
    ("Coverage", "Inspect collection status and market depth across all 30 EEA markets.", "GET", "/api/coverage"),
    ("Market register", "Review retained public sources and freshness metadata.", "GET", "/api/market"),
    ("Conversation stream", "Stream governed analysis as progress, plan, visual, token, citation and completion events.", "POST", "/api/assistant/stream"),
    ("Conversations", "List the signed-in user’s persisted chat history.", "GET", "/api/threads"),
)


def developer_page(user: dict | None = None, threads: list[dict] | None = None, *, lang: str = "en"):
    cards = Section(
        *(
            Article(H3(title), P(copy), Code(Strong(method), f" {path}"), cls="dev-card")
            for title, copy, method, path in RESOURCES
        ),
        cls="dev-grid",
    )
    header = Header(mobile_menu(), Strong("Developers"), cls="mobile-header") if user else None
    content = Main(
        header,
        Div(
            P("DEVELOPER PLATFORM · API V1", cls="eyebrow"),
            H1("Build with source-backed clinic intelligence."),
            P(
                "Use the same governed, read-only data surface that powers FastComps. "
                "Every observation retains its public source URL; raw SQL and internal database infrastructure are never exposed.",
                cls="dev-lede",
            ),
            Nav(
                A("Guide", href="#resources", cls="primary"),
                A("Swagger UI", href="/api/docs"), A("ReDoc", href="/api/redoc"),
                A("Runtime OpenAPI", href="/api/openapi.json"),
                A("OpenAPI v1", href="/api/openapi/v1.json"),
                A("Compatibility schema", href="/swagger.json"), cls="dev-tabs",
            ),
            Aside(
                Strong("Authentication. "),
                "The documentation and OpenAPI contract are public. Data and conversation requests use the secure FastComps session cookie and return ",
                Code("401"),
                " outside an authenticated session. Dedicated scoped API keys can be added later without exposing the database.",
                cls="dev-note",
            ),
            H2("API resources", id="resources"), cards,
            H2("Quick start"),
            Pre(Code(
                "curl 'https://comps.fastsme.com/api/overview?country=EE' \\\n"
                "  --cookie 'fastcomps_session=<signed-session>'\n\n"
                "# Streamed conversational analysis\n"
                "curl 'https://comps.fastsme.com/api/assistant/stream' \\\n"
                "  --header 'Content-Type: application/json' \\\n"
                "  --cookie 'fastcomps_session=<signed-session>' \\\n"
                "  --data '{\"question\":\"Compare clinic pricing in Estonia\",\"country\":\"EE\",\"workspace\":\"chat\"}'"
            )),
            H2("Streaming event contract"),
            P(
                "The SSE response emits progress, plan, visual, token, citations, and done events. "
                "Plans are constrained to allowlisted metrics and dimensions; the server compiles and executes bounded read-only queries internally.",
                cls="dev-copy",
            ),
            cls="dev-wrap",
        ),
        cls="shell-main dev-main" if user else "dev-main dev-public",
    )
    if not user:
        return Html(
            public_head(
                "Developers · FastComps",
                "FastComps API resources, OpenAPI contracts and streamed conversational-analysis event documentation.",
                styles=("/static/developers.css",),
                lang=lang,
            ),
            Body(public_nav(lang), content, public_footer(lang), cls="landing-body"),
            lang=lang,
        )
    return app_page(
        "Developers", content, user=user, threads=threads or [], active="developers",
        styles=("/static/developers.css",), lang=lang,
    )
