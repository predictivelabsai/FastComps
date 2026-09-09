"""FastHTML shell shared by chat, dashboard and developer pages."""

from __future__ import annotations

import json

from fasthtml.common import (
    A, Aside, Body, Button, Details, Div, Footer, Head, Html, Link, Meta, Nav,
    NotStr, P, Script, Small, Span, Strong, Summary, Title,
)

from i18n import LANGUAGES, js_catalog, t


HTMX_URL = "https://unpkg.com/htmx.org@2.0.4"


def language_switcher(lang: str = "en"):
    current = LANGUAGES.get(lang, LANGUAGES["en"])
    return Details(
        Summary(Span(current["flag"]), Span(current["native"], cls="language-name"), aria_label=t("Choose language", lang)),
        Div(*(
            A(
                Span(info["flag"]), Span(info["native"]),
                href=f"/set-lang/{code}", lang=code,
                onclick=f"this.href='/set-lang/{code}?next='+encodeURIComponent(location.pathname+location.search+location.hash)",
                aria_current="true" if code == lang else None,
                cls=f"language-option{' active' if code == lang else ''}",
            )
            for code, info in LANGUAGES.items()
        ), cls="language-menu"),
        cls="language-switcher",
    )


def page_head(title: str, *, lang: str = "en", styles: tuple[str, ...] = (), scripts: tuple[str, ...] = ()):
    return Head(
        Meta(charset="utf-8"),
        Meta(name="viewport", content="width=device-width,initial-scale=1"),
        Title(f"{t(title, lang)} · FastComps"),
        Link(rel="icon", href="/static/favicon.svg"),
        Link(rel="stylesheet", href="/static/app.css"),
        Link(rel="stylesheet", href="/static/shell.css"),
        *(Link(rel="stylesheet", href=path) for path in styles),
        Script(src=HTMX_URL, defer=True),
        *(Script(src=path, defer=True) for path in scripts),
    )


def sidebar(user: dict, threads: list[dict], *, active: str, current_thread: str = "", lang: str = "en"):
    def item(key: str, label: str, href: str, icon: str):
        return A(
            Span(icon), label, href=href,
            cls=f"side-link{' active' if key == active else ''}",
        )

    history = [
        A(
            Span("◌"), row.get("title") or "New chat",
            href=f"/?thread={row['id']}",
            cls=f"history-link{' active' if str(row['id']) == current_thread else ''}",
        )
        for row in threads
    ]
    return Aside(
        Div(
            A(Span("F"), "FastComps", href="/", cls="brand"),
            language_switcher(lang),
            Button("×", cls="side-close", onclick="toggleSidebar()", aria_label="Close navigation"),
            A(Span("＋"), "New Chat", href="/", cls="new-chat-btn"),
            cls="side-head",
        ),
        Nav(
            P("Workspace", cls="side-label"),
            item("chat", "Chat", "/", "◇"),
            item("dashboard", "Dashboard", "/dashboard", "▦"),
            item("developers", "Developers", "/developers", "⌘"),
            P("Intelligence", cls="side-label"),
            A(Span("◎"), "Competitors", href="/dashboard#competitors", cls="side-link"),
            A(Span("◫"), "Coverage", href="/dashboard#coverage", cls="side-link"),
            A(Span("↗"), "Evidence", href="/dashboard#evidence", cls="side-link"),
            P("Recent chats", cls="side-label"),
            Div(*history, cls="history-list") if history else Div(P("No conversations yet", cls="history-empty"), cls="history-list"),
            cls="side-scroll",
        ),
        Footer(
            Span(user["email"][:1].upper(), cls="avatar"),
            Span(
                Strong(user.get("name") or user["email"]),
                Small(user["email"]),
                cls="side-user-copy",
            ),
            A("↪", href="/auth/logout", title="Sign out"),
            cls="side-user",
        ),
        cls="side-nav",
    )


def mobile_menu():
    return Button("☰", cls="mobile-menu-btn", onclick="toggleSidebar()", aria_label="Open navigation")


def app_page(
    title: str,
    content,
    *,
    user: dict,
    threads: list[dict],
    active: str,
    current_thread: str = "",
    styles: tuple[str, ...] = (),
    scripts: tuple[str, ...] = (),
    body_cls: str = "",
    lang: str = "en",
):
    return Html(
        page_head(title, lang=lang, styles=styles, scripts=scripts),
        Body(
            Div(
                sidebar(user, threads, active=active, current_thread=current_thread, lang=lang),
                content,
                cls="app-shell",
            ),
            Div(id="left-overlay", cls="left-overlay", onclick="toggleSidebar()"),
            Script(NotStr(json.dumps({"lang": lang, "translations": js_catalog(lang)}, ensure_ascii=False).replace("</", "<\\/")), id="i18n-data", type="application/json"),
            Script("""function toggleSidebar(){document.querySelector('.side-nav').classList.toggle('open');document.getElementById('left-overlay').classList.toggle('open')}"""),
            cls=body_cls,
        ),
        lang=lang,
    )
