"""FastHTML chat workspace."""

from __future__ import annotations

import json
from urllib.parse import urlsplit

from fasthtml.common import (
    A, Article, Button, Div, Form, H1, Header, Main, NotStr, P, Script,
    Section, Span, Strong, Textarea,
)

from components.shell import app_page, mobile_menu


def _safe_href(value: str) -> str:
    try:
        parsed = urlsplit(value)
        return value if parsed.scheme in {"http", "https"} and parsed.netloc else "#"
    except ValueError:
        return "#"


def message_component(message: dict):
    role = "user" if message.get("role") == "user" else "assistant"
    citations = message.get("citations") or []
    sources = None
    if citations:
        sources = Div(
            Span("Sources"),
            *(
                A(
                    f"↗ {item.get('label') or 'Source'}",
                    href=_safe_href(str(item.get("url") or "")),
                    target="_blank",
                    rel="noopener noreferrer",
                )
                for item in citations[:6]
            ),
            cls="chat-citations",
        )
    return Article(
        Div("You" if role == "user" else "FastComps AI", cls="chat-role"),
        Div(P(message.get("content") or ""), sources, cls="chat-bubble"),
        cls=f"chat-message {role}",
    )


def chat_page(user: dict, threads: list[dict], messages: list[dict], *, thread_id: str = ""):
    welcome = Div(
        Span("✦", cls="assistant-orb"),
        P("FASTCOMPS AI", cls="eyebrow"),
        H1("What do you want to know about the clinic market?"),
        P("Ask about competitors, treatments, published prices, market coverage or retained evidence."),
        Div(
            Button("Compare clinic pricing in Lithuania", type="button"),
            Button("Which EEA markets need attention?", type="button"),
            Button("Where is IV therapy observed?", type="button"),
            A("Explore the Developer API →", href="/developers"),
            cls="chat-suggestions",
        ),
        id="chat-welcome",
        cls=f"chat-welcome{' hidden' if messages else ''}",
    )
    content = Main(
        Header(
            Div(mobile_menu(), Strong("Market intelligence")),
            Span("Clinics · 30 EEA markets"),
            cls="chat-header",
        ),
        Section(welcome, *(message_component(item) for item in messages), id="chat-messages", cls="chat-messages"),
        Form(
            Textarea(
                id="chat-question", rows="1", maxlength="500",
                placeholder="Ask about clinics, treatments, prices or coverage…", required=True,
            ),
            Button("↑", type="submit", aria_label="Send question"),
            P("Governed read-only analytics · Sources stay visible · No SQL exposed"),
            id="chat-form", cls="central-chat-form",
        ),
        Script(NotStr(json.dumps({"thread_id": thread_id})), id="chat-state", type="application/json"),
        cls="shell-main chat-pane",
    )
    return app_page(
        "Chat", content, user=user, threads=threads, active="chat", current_thread=thread_id,
        styles=("/static/chat.css",), scripts=("/static/chat.js",),
    )
