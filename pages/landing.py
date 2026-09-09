"""Public FastComps product landing page."""

from __future__ import annotations

import json
from urllib.parse import quote

from fasthtml.common import (
    A,
    Article,
    Body,
    Div,
    Footer,
    H1,
    H2,
    H3,
    Head,
    Html,
    Img,
    Link,
    Main,
    Meta,
    Nav,
    NotStr,
    P,
    Script,
    Section,
    Span,
    Strong,
    Title,
)

from components.shell import language_switcher
from i18n import t


ACCENT = "#177357"
TINT = "#f3f7f5"
CANONICAL_URL = "https://comps.fastsme.com"
DESCRIPTION = (
    "Track clinic competitors, treatments and published prices across all 30 EEA markets, "
    "with every claim linked to retained source evidence."
)
FAVICON = "data:image/svg+xml," + quote(
    """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32"><rect width="32" height="32" rx="8" fill="#177357"/><path fill="white" d="M16 4 28 16 16 28 4 16Z"/><path fill="#177357" d="M10 10h12v4h-7v3h6v4h-6v5h-5Z"/></svg>""",
    safe="",
)


def public_head(title: str, description: str = DESCRIPTION, *, styles: tuple[str, ...] = (), lang: str = "en"):
    canonical = CANONICAL_URL + ("/developers" if title.startswith("Developers") else "")
    localized_title = t(title, lang)
    localized_description = t(description, lang)
    return Head(
        Meta(charset="utf-8"),
        Meta(name="viewport", content="width=device-width,initial-scale=1"),
        Meta(name="description", content=localized_description),
        Meta(name="theme-color", content=ACCENT),
        Meta(property="og:type", content="website"),
        Meta(property="og:site_name", content="FastComps"),
        Meta(property="og:title", content=localized_title),
        Meta(property="og:description", content=localized_description),
        Meta(property="og:url", content=canonical),
        Meta(name="twitter:card", content="summary_large_image"),
        Meta(name="twitter:title", content=localized_title),
        Meta(name="twitter:description", content=localized_description),
        Link(rel="canonical", href=canonical),
        Link(rel="icon", type="image/svg+xml", href=FAVICON),
        Link(rel="preconnect", href="https://fonts.googleapis.com"),
        Link(
            rel="stylesheet",
            href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=Newsreader:opsz,wght@6..72,500;6..72,600&display=swap",
        ),
        Link(rel="stylesheet", href="/static/landing.css"),
        *(Link(rel="stylesheet", href=style) for style in styles),
        Title(localized_title),
    )


def public_nav(lang: str = "en"):
    return Nav(
        A(Span("F", cls="lp-mark"), Span("FastComps"), href="/", cls="lp-brand"),
        Div(
            A("Product", href="/#product", cls="lp-nav-link"),
            A("Coverage", href="/#coverage", cls="lp-nav-link"),
            A("Developers", href="/developers", cls="lp-nav-link"),
            language_switcher(lang),
            A("Sign in", href="/auth/sign-in", cls="lp-signin"),
            A("Get started", href="/auth/sign-up", cls="lp-primary lp-nav-cta"),
            cls="lp-nav-actions",
        ),
        cls="lp-nav",
    )


def public_footer(lang: str = "en"):
    return Footer(
        Div(
            A(Span("F", cls="lp-mark small"), Strong("FastComps"), href="/", cls="lp-brand"),
            P("Clinic competitive intelligence with evidence attached."),
        ),
        Div(
            A("Developers", href="/developers"),
            A("Sign in", href="/auth/sign-in"),
            A("Create account", href="/auth/sign-up"),
            A("FastSME products", href="https://fastsme.com/products"),
            cls="lp-footer-links",
        ),
        cls="lp-footer",
    )


def landing_page(lang: str = "en"):
    structured_data = json.dumps(
        {
            "@context": "https://schema.org",
            "@type": "SoftwareApplication",
            "name": "FastComps",
            "applicationCategory": "BusinessApplication",
            "operatingSystem": "Web",
            "url": CANONICAL_URL,
            "description": t(DESCRIPTION, lang),
        },
        separators=(",", ":"),
    )
    return Html(
        public_head("FastComps · Source-backed clinic competitive intelligence", lang=lang),
        Body(
            public_nav(lang),
            Main(
                Section(
                    Div(
                        P(Span(cls="lp-live-dot"), "COMPETITIVE INTELLIGENCE · 30 EEA MARKETS", cls="lp-kicker"),
                        H1("See the clinic market as evidence, not noise."),
                        P(DESCRIPTION, cls="lp-lede"),
                        Div(
                            A("Start researching", href="/auth/sign-up", cls="lp-primary lp-hero-cta"),
                            A("Sign in with Google →", href="/auth/google?next=/", cls="lp-secondary"),
                            cls="lp-actions",
                        ),
                        Div(
                            Div(Strong("30"), Span("EEA markets")),
                            Div(Strong("EUR"), Span("normalised prices")),
                            Div(Strong("100%"), Span("evidence-linked")),
                            cls="lp-proof",
                        ),
                        cls="lp-hero-copy",
                    ),
                    Div(
                        Div(Span("●"), Span("●"), Span("●"), P("comps.fastsme.com"), cls="lp-window-bar"),
                        Img(
                            src="/static/product-demo.gif",
                            alt="Animated FastComps product tour showing conversational research and the clinic market dashboard",
                            width="1200",
                            height="750",
                            loading="eager",
                        ),
                        P("Live product tour · chat, market map and retained evidence", cls="lp-demo-caption"),
                        cls="lp-demo-frame",
                    ),
                    cls="lp-hero",
                ),
                Section(
                    Div(
                        P("ONE WORKSPACE, TRACEABLE ANSWERS", cls="lp-kicker"),
                        H2("Move from a market question to the source behind it."),
                        P(
                            "FastComps combines streamed conversational analysis with a structured competitor and pricing evidence base. "
                            "It gives operators the answer, its market context and the trail needed to verify it.",
                            cls="lp-section-lede",
                        ),
                        cls="lp-section-head",
                    ),
                    Div(
                        Article(Span("01"), H3("Ask in plain language"), P("Compare treatments, price levels, competitors and coverage without writing a query.")),
                        Article(Span("02"), H3("Explore the market"), P("Use a Plotly treemap to move from country to treatment type and individual treatment.")),
                        Article(Span("03"), H3("Verify every claim"), P("Open readable clinic pages from observations, evidence registers and answer citations.")),
                        cls="lp-feature-grid",
                    ),
                    id="product",
                    cls="lp-section",
                ),
                Section(
                    Div(
                        P("BUILT FOR COVERAGE", cls="lp-kicker"),
                        H2("A living map of the European clinic market."),
                        P(
                            "Start with clinics today. The model already separates verticals, competitors, locations, categories, "
                            "services and products so additional markets can join without rebuilding the platform.",
                            cls="lp-section-lede",
                        ),
                        Div(
                            Span("Clinics"), Span("Competitors"), Span("Treatments"), Span("Products"), Span("Published prices"), Span("Evidence"),
                            cls="lp-tags",
                        ),
                        A("Explore the workspace", href="/auth/sign-up", cls="lp-primary"),
                    ),
                    Div(
                        P("COVERAGE MODEL", cls="lp-mini-label"),
                        Div(
                            Div(Strong("Country"), Span("30 EEA markets")),
                            Div(Strong("Treatment type"), Span("Comparable categories")),
                            Div(Strong("Treatment"), Span("Published clinic offering")),
                            Div(Strong("Price level"), Span("Normalised within market")),
                            cls="lp-model",
                        ),
                    ),
                    id="coverage",
                    cls="lp-coverage",
                ),
                Section(
                    Div(
                        P("DEVELOPER PLATFORM · API V1", cls="lp-kicker"),
                        H2("Build on governed clinic intelligence."),
                        P(
                            "Review the resource catalogue, OpenAPI contracts and streaming event model. "
                            "SQL and database infrastructure stay private.",
                            cls="lp-section-lede",
                        ),
                    ),
                    A("Read the developer documentation →", href="/developers", cls="lp-primary"),
                    cls="lp-developer-band",
                ),
                Section(
                    P("START WITH A QUESTION", cls="lp-kicker"),
                    H2("Know what changed—and why it matters."),
                    P("Create your workspace and turn public clinic-market evidence into decisions."),
                    Div(
                        A("Create an account", href="/auth/sign-up", cls="lp-primary lp-hero-cta"),
                        A("Sign in", href="/auth/sign-in", cls="lp-signin"),
                        cls="lp-actions centered",
                    ),
                    cls="lp-final-cta",
                ),
            ),
            public_footer(lang),
            Script(NotStr(structured_data), type="application/ld+json"),
            cls="landing-body",
        ),
        lang=lang,
    )
