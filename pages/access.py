"""FastHTML account access components with HTMX form handling."""

from __future__ import annotations

from fasthtml.common import (
    A, Body, Button, Div, Form, H1, Head, Html, Input, Label, Link, Main,
    Meta, NotStr, P, Small, Span, Title,
)

from components.shell import HTMX_URL
from fasthtml.common import Script


GOOGLE_SVG = """<svg width="18" height="18" viewBox="0 0 18 18" aria-hidden="true"><path d="M17.64 9.2c0-.637-.057-1.251-.164-1.84H9v3.481h4.844c-.209 1.125-.843 2.078-1.796 2.717v2.258h2.908c1.702-1.567 2.684-3.874 2.684-6.615z" fill="#4285F4"/><path d="M9 18c2.43 0 4.467-.806 5.956-2.18l-2.908-2.259c-.806.54-1.837.86-3.048.86-2.344 0-4.328-1.584-5.036-3.711H.957v2.332A8.997 8.997 0 009 18z" fill="#34A853"/><path d="M3.964 10.71A5.41 5.41 0 013.682 9c0-.593.102-1.17.282-1.71V4.958H.957A8.996 8.996 0 000 9s.38 1.572.957 3.042l3.007-2.332z" fill="#FBBC05"/><path d="M9 3.58c1.321 0 2.508.454 3.44 1.345l2.582-2.58C13.463.891 11.426 0 9 0A8.997 8.997 0 00.957 4.958L3.964 7.29C4.672 5.163 6.656 3.58 9 3.58z" fill="#EA4335"/></svg>"""


def _message(text: str, kind: str):
    return P(text, cls=f"auth-{kind}", role="status") if text else None


def access_card(mode: str, *, next_path: str = "/", error: str = "", message: str = ""):
    signup = mode == "signup"
    title = "Create an account" if signup else "Sign in to FastComps"
    copy = "Sign up with Google or use your work email." if signup else "Access your clinic intelligence workspace and saved conversations."
    action = "/auth/sign-up" if signup else f"/auth/sign-in?next={next_path}"
    fields = []
    if signup:
        fields.append(Label("Name", Input(name="name", autocomplete="name", maxlength="100")))
    fields.extend((
        Label("Email", Input(name="email", type="email", autocomplete="email" if signup else "username", required=True)),
        Label(
            "Password",
            Input(name="password", type="password", autocomplete="new-password" if signup else "current-password", minlength="8" if signup else None, required=True),
            Small("At least 8 characters.") if signup else None,
        ),
    ))
    if not signup:
        fields.append(Div(A("Forgot password?", href="/auth/forgot"), cls="auth-row"))
    return Main(
        A(Span("F"), "FastComps", href="/", cls="brand"),
        P("CREATE YOUR WORKSPACE" if signup else "SECURE ACCOUNT ACCESS", cls="eyebrow"),
        H1(title), P(copy), _message(message, "success"), _message(error, "error"),
        Div(
            A("Sign in", href=f"/auth/sign-in?next={next_path}", cls="active" if not signup else ""),
            A("Create account", href="/auth/sign-up", cls="active" if signup else ""),
            cls="auth-tabs",
        ),
        A(NotStr(GOOGLE_SVG), Span("Sign up with Google" if signup else "Continue with Google"), href=f"/auth/google?next={next_path}", cls="google-button"),
        Div(Span("or"), cls="auth-divider"),
        Form(
            *fields,
            Button("Create account" if signup else "Sign in", type="submit"),
            method="post", action=action, hx_post=action, hx_target="#auth-card", hx_swap="outerHTML",
            cls="auth-form",
        ),
        P(
            "Already registered? " if signup else "New to FastComps? ",
            A("Sign in" if signup else "Create an account", href="/auth/sign-in" if signup else "/auth/sign-up"),
            cls="auth-switch",
        ),
        id="auth-card", cls="signin-card",
    )


def forgot_card(*, error: str = "", message: str = ""):
    return Main(
        A(Span("F"), "FastComps", href="/", cls="brand"), P("ACCOUNT RECOVERY", cls="eyebrow"),
        H1("Forgot password?"), P("Enter your email and we’ll send a one-time reset link."),
        _message(message, "success"), _message(error, "error"),
        Form(
            Label("Email", Input(name="email", type="email", autocomplete="email", required=True, autofocus=True)),
            Button("Send reset link", type="submit"),
            method="post", action="/auth/forgot", hx_post="/auth/forgot", hx_target="#auth-card", hx_swap="outerHTML", cls="auth-form",
        ),
        P(A("Back to sign in", href="/auth/sign-in"), cls="auth-switch"), id="auth-card", cls="signin-card",
    )


def reset_card(*, token: str, error: str = ""):
    return Main(
        A(Span("F"), "FastComps", href="/", cls="brand"), P("ACCOUNT RECOVERY", cls="eyebrow"),
        H1("Set a new password"), P("This one-time link expires after one hour."), _message(error, "error"),
        Form(
            Input(name="token", type="hidden", value=token),
            Label("New password", Input(name="password", type="password", autocomplete="new-password", minlength="8", required=True)),
            Label("Confirm password", Input(name="confirm_password", type="password", autocomplete="new-password", minlength="8", required=True)),
            Button("Reset password", type="submit"),
            method="post", action="/auth/reset", hx_post="/auth/reset", hx_target="#auth-card", hx_swap="outerHTML", cls="auth-form",
        ), id="auth-card", cls="signin-card",
    )


def notice_card(title: str, copy: str, *, action: str, action_label: str):
    return Main(
        A(Span("F"), "FastComps", href="/", cls="brand"), P("FASTCOMPS ACCOUNT", cls="eyebrow"),
        H1(title), P(copy), A(action_label, href=action, cls="primary-button"), id="auth-card", cls="signin-card",
    )


def access_page(card, *, title: str):
    return Html(
        Head(
            Meta(charset="utf-8"), Meta(name="viewport", content="width=device-width,initial-scale=1"),
            Meta(name="robots", content="noindex"), Title(f"{title} · FastComps"),
            Link(rel="icon", href="/static/favicon.svg"), Link(rel="stylesheet", href="/static/app.css"),
            Link(rel="stylesheet", href="/static/shell.css"), Link(rel="stylesheet", href="/static/auth.css"), Script(src=HTMX_URL, defer=True),
        ),
        Body(card, cls="signin-body"),
    )
