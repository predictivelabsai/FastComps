"""FastComps chat-first clinic competitive-intelligence application."""
from __future__ import annotations

import json
import re
import secrets
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from urllib.parse import quote

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fasthtml.common import to_xml
from pydantic import BaseModel, Field
from starlette.middleware.sessions import SessionMiddleware

from auth import accounts, google_oidc
from assistant import answer, stream_answer
from config import APP_NAME, APP_VERSION, PUBLIC_URL, SESSION_SECRET
from db import SCHEMA, connection, init_db
from pages.access import access_card, access_page, forgot_card, notice_card, reset_card
from pages.chat import chat_page
from pages.dashboard import dashboard_page
from pages.developers import developer_page
from pages.landing import landing_page
import newsletter
import repository


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    yield


app = FastAPI(
    title=APP_NAME,
    description="Source-backed clinic competitive intelligence across all 30 EEA markets.",
    version=APP_VERSION,
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
    servers=[{"url": PUBLIC_URL, "description": "Production"}],
    lifespan=lifespan,
)
app.mount("/static", StaticFiles(directory="static"), name="static")
_requests: dict[str, deque[float]] = defaultdict(deque)

if not SESSION_SECRET:
    raise RuntimeError("SESSION_SECRET is required")


@app.middleware("http")
async def require_sign_in(request: Request, call_next):
    path = request.url.path
    public_paths = {
        "/", "/developers", "/health", "/healthz", "/robots.txt", "/sitemap.xml",
        "/api/docs", "/api/redoc", "/api/openapi.json", "/api/openapi/v1.json", "/swagger.json",
    }
    if path in public_paths or path.startswith(("/static/", "/auth/")):
        return await call_next(request)
    if request.session.get("user"):
        return await call_next(request)
    if path.startswith("/api/") or path == "/openapi.json":
        return JSONResponse({"detail": "Authentication required"}, status_code=401)
    return RedirectResponse(f"/auth/sign-in?next={quote(path, safe='/')}", status_code=303)


app.add_middleware(
    SessionMiddleware,
    secret_key=SESSION_SECRET,
    session_cookie="fastcomps_session",
    max_age=60 * 60 * 24 * 7,
    same_site="lax",
    https_only=PUBLIC_URL.startswith("https://"),
)


def _country(value: str | None) -> str | None:
    if not value:
        return None
    value = value.upper()
    if not re.fullmatch(r"[A-Z]{2}", value):
        raise HTTPException(400, "Invalid country code")
    return value


def _html(component, *, status_code: int = 200, headers: dict[str, str] | None = None) -> HTMLResponse:
    return HTMLResponse(to_xml(component), status_code=status_code, headers=headers)


def _access_response(request: Request, card, *, title: str) -> HTMLResponse:
    if request.headers.get("HX-Request") == "true":
        return _html(card)
    return _html(access_page(card, title=title))


def _redirect(request: Request, path: str) -> HTMLResponse | RedirectResponse:
    if request.headers.get("HX-Request") == "true":
        return HTMLResponse("", headers={"HX-Redirect": path})
    return RedirectResponse(path, status_code=303)


class AssistantRequest(BaseModel):
    question: str = Field(min_length=2, max_length=500)
    country: str | None = Field(default=None, max_length=2)
    workspace: str = Field(default="dashboard", pattern="^(dashboard|chat)$")
    thread_id: str | None = None


@app.get("/healthz")
def healthz():
    try:
        with connection() as conn, conn.cursor() as cur:
            cur.execute("SELECT 1"); cur.fetchone()
        return {"status":"ok","service":APP_NAME,"version":APP_VERSION,"schema":SCHEMA}
    except Exception as exc:
        return JSONResponse({"status":"error","detail":type(exc).__name__},status_code=503)


@app.get("/health", include_in_schema=False)
def health_alias(): return healthz()


@app.get("/robots.txt", include_in_schema=False, response_class=PlainTextResponse)
def robots():
    return "User-agent: *\nAllow: /\nSitemap: https://comps.fastsme.com/sitemap.xml\n"


@app.get("/sitemap.xml", include_in_schema=False)
def sitemap():
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        '<url><loc>https://comps.fastsme.com/</loc></url>'
        '<url><loc>https://comps.fastsme.com/developers</loc></url>'
        '</urlset>'
    )
    return Response(xml, media_type="application/xml")


@app.get("/api/overview")
def api_overview(country: str | None = None): return repository.overview(_country(country))


@app.get("/api/coverage")
def api_coverage(): return repository.coverage()


@app.get("/api/competitors")
def api_competitors(country: str | None = None, q: str | None = Query(default=None,max_length=100), limit: int = 100):
    return repository.competitors(_country(country),q,limit)


@app.get("/api/observations")
def api_observations(country: str | None = None, competitor_id: str | None = None,
                     q: str | None = Query(default=None,max_length=100), limit: int = 100):
    return repository.observations(_country(country),competitor_id,q,limit)


@app.get("/api/locations")
def api_locations(country: str | None = None): return repository.locations(_country(country))


@app.get("/api/categories")
def api_categories(country: str | None = None): return repository.categories(_country(country))


@app.get("/api/treemap", tags=["market intelligence"])
def api_treemap(country: str | None = None, limit: int = 700):
    return repository.treatment_treemap(_country(country), limit)


@app.get("/api/evidence")
def api_evidence(country: str | None = None, limit: int = 30): return repository.evidence(_country(country),limit)


@app.get("/api/candidates")
def api_candidates(country: str | None = None, state: str | None = Query(default=None,max_length=30), limit: int = 100):
    return repository.candidates(_country(country),state,limit)


@app.get("/api/watchlist")
def api_watchlist(country: str | None = None): return repository.watchlist(_country(country))


@app.get("/api/runs")
def api_runs(limit: int = 30): return repository.runs(limit)


@app.get("/api/threads", tags=["conversations"])
def api_threads(request: Request, limit: int = 30):
    return repository.chat_threads(request.session["user"]["id"], limit)


@app.get("/api/threads/{thread_id}", tags=["conversations"])
def api_thread(thread_id: str, request: Request):
    return repository.chat_messages(request.session["user"]["id"], thread_id)


@app.post("/api/assistant")
def api_assistant(payload: AssistantRequest, request: Request):
    _rate_limit(request)
    return answer(payload.question.strip(),_country(payload.country))


def _rate_limit(request: Request) -> None:
    ip = request.client.host if request.client else "unknown"; now = time.monotonic(); bucket = _requests[ip]
    while bucket and bucket[0] < now - 60: bucket.popleft()
    if len(bucket) >= 10: raise HTTPException(429,"Please wait before asking another question")
    bucket.append(now)


@app.post("/api/assistant/stream")
def api_assistant_stream(payload: AssistantRequest, request: Request):
    _rate_limit(request)
    question = payload.question.strip()
    country = _country(payload.country)
    if payload.workspace == "chat":
        user_key = request.session["user"]["id"]
        thread_id = payload.thread_id or repository.create_chat_thread(user_key, question[:80])
        if not repository.add_chat_message(user_key, thread_id, "user", question):
            raise HTTPException(404, "Conversation not found")
        source = _persisted_stream(user_key, thread_id, question, country)
    else:
        source = stream_answer(question, country)
    return StreamingResponse(
        source,
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"},
    )


def _persisted_stream(user_key: str, thread_id: str, question: str, country: str | None):
    yield f"event: thread\ndata: {json.dumps({'thread_id': thread_id})}\n\n"
    answer_text = ""
    citations: list[dict] = []
    for chunk in stream_answer(question, country):
        event_name = "message"
        data: dict = {}
        for line in chunk.splitlines():
            if line.startswith("event:"):
                event_name = line[6:].strip()
            elif line.startswith("data:"):
                try:
                    data = json.loads(line[5:].strip())
                except json.JSONDecodeError:
                    data = {}
        if event_name == "token":
            answer_text += data.get("token", "")
        elif event_name == "citations":
            citations = data.get("items", [])
        yield chunk
    if answer_text.strip():
        repository.add_chat_message(user_key, thread_id, "assistant", answer_text.strip(), citations)


@app.get("/api/openapi/v1.json", include_in_schema=False)
def openapi_v1():
    return JSONResponse(app.openapi())


@app.get("/swagger.json", include_in_schema=False)
def swagger_compatibility():
    return JSONResponse(app.openapi())


def _safe_next(value: str) -> str:
    return value if value.startswith("/") and not value.startswith("//") else "/"


def _sign_in_error(value: str) -> str:
    return {
        "invalid": "Email or password is incorrect.",
        "unverified": "Verify your email before signing in.",
        "state": "Google sign-in expired. Please try again.",
        "account": "Google could not verify this account.",
        "not_configured": "Google sign-in is temporarily unavailable.",
    }.get(value, value)


def _login_session(request: Request, user: dict) -> None:
    request.session.clear()
    request.session["user"] = {
        "id": str(user["id"]),
        "email": user["email"],
        "name": user.get("name") or user["email"],
        "role": user.get("role", "viewer"),
    }


@app.api_route("/auth/sign-in", methods=["GET", "POST"], response_class=HTMLResponse)
async def sign_in(request: Request, next: str = "/", error: str = "", message: str = ""):
    if request.session.get("user"):
        return RedirectResponse(_safe_next(next), status_code=303)
    next_path = _safe_next(next)
    if request.method == "POST":
        form = await request.form()
        user, reason = accounts.authenticate(str(form.get("email") or ""), str(form.get("password") or ""))
        if not user:
            return _access_response(
                request,
                access_card("signin", next_path=next_path, error=_sign_in_error(reason or "invalid")),
                title="Sign in",
            )
        _login_session(request, user)
        return _redirect(request, next_path)
    return _html(access_page(access_card("signin", next_path=next_path, error=_sign_in_error(error), message=message), title="Sign in"))


@app.api_route("/auth/sign-up", methods=["GET", "POST"], response_class=HTMLResponse)
async def sign_up(request: Request, error: str = ""):
    if request.session.get("user"):
        return RedirectResponse("/", status_code=303)
    if request.method == "POST":
        form = await request.form()
        email = accounts.normalize_email(str(form.get("email") or ""))
        password = str(form.get("password") or "")
        name = str(form.get("name") or "")
        if not accounts.valid_email(email):
            return _access_response(request, access_card("signup", error="Enter a valid email address."), title="Create account")
        if len(password) < 8:
            return _access_response(request, access_card("signup", error="Password must be at least 8 characters."), title="Create account")
        user = accounts.create_user(email, password, name)
        if not user:
            return _access_response(request, access_card("signup", error="An account with this email already exists."), title="Create account")
        token = accounts.create_token(str(user["id"]), "verify_email", lifetime_minutes=24 * 60)
        accounts.send_account_email(email, purpose="verify_email", token=token)
        return _access_response(
            request,
            notice_card(
                "Check your email",
                "We sent a verification link to finish creating your FastComps account.",
                action="/auth/sign-in", action_label="Back to sign in",
            ),
            title="Check your email",
        )
    return _html(access_page(access_card("signup", error=error), title="Create account"))


@app.api_route("/auth/forgot", methods=["GET", "POST"], response_class=HTMLResponse)
async def forgot_password(request: Request):
    if request.method == "POST":
        form = await request.form()
        email = accounts.normalize_email(str(form.get("email") or ""))
        user = accounts.user_for_email(email) if accounts.valid_email(email) else None
        if user:
            token = accounts.create_token(str(user["id"]), "reset_password", lifetime_minutes=60)
            accounts.send_account_email(email, purpose="reset_password", token=token)
        return _access_response(
            request,
            forgot_card(message="If that email is registered, a reset link is on its way."),
            title="Forgot password",
        )
    return _html(access_page(forgot_card(), title="Forgot password"))


@app.get("/auth/verify", response_class=HTMLResponse)
def verify_email(token: str = ""):
    user = accounts.verify_email_token(token) if token else None
    if not user:
        return _html(access_page(
            notice_card(
                "Link expired",
                "This verification link is invalid or has expired. Create the account again to receive a new one.",
                action="/auth/sign-up", action_label="Create account",
            ),
            title="Link expired",
        ))
    return RedirectResponse("/auth/sign-in?message=Email+verified.+You+can+sign+in+now.", status_code=303)


@app.api_route("/auth/reset", methods=["GET", "POST"], response_class=HTMLResponse)
async def reset_password(request: Request, token: str = ""):
    if request.method == "POST":
        form = await request.form()
        token = str(form.get("token") or "")
        password = str(form.get("password") or "")
        confirmation = str(form.get("confirm_password") or "")
        if len(password) < 8:
            return _access_response(request, reset_card(token=token, error="Password must be at least 8 characters."), title="Reset password")
        if password != confirmation:
            return _access_response(request, reset_card(token=token, error="Passwords do not match."), title="Reset password")
        if not accounts.reset_password(token, password):
            return _access_response(request, reset_card(token=token, error="This reset link is invalid or has expired."), title="Reset password")
        return _redirect(request, "/auth/sign-in?message=Password+reset+successful.")
    if not token:
        return RedirectResponse("/auth/forgot", status_code=303)
    return _html(access_page(reset_card(token=token), title="Reset password"))


@app.get("/auth/google")
def google_start(request: Request, next: str = "/"):
    if not google_oidc.enabled():
        return RedirectResponse("/auth/sign-in?error=not_configured", status_code=303)
    safe_next = _safe_next(next)
    request.session.clear()
    state = google_oidc.new_state()
    request.session["google_oauth_state"] = state
    request.session["post_auth_path"] = safe_next
    return RedirectResponse(google_oidc.authorization_url(state), status_code=302)


@app.get("/auth/google/callback",include_in_schema=False)
def google_callback(request: Request, code: str = "", state: str = "", error: str = ""):
    expected_state = request.session.pop("google_oauth_state", None)
    if error or not code or not expected_state or not secrets.compare_digest(state, expected_state):
        request.session.clear()
        return RedirectResponse("/auth/sign-in?error=state", status_code=303)
    identity = google_oidc.exchange_google_code(code)
    if not identity:
        request.session.clear()
        return RedirectResponse("/auth/sign-in?error=account", status_code=303)
    next_path = request.session.pop("post_auth_path", "/")
    user_id = google_oidc.save_user(identity)
    _login_session(request, {"id": user_id, "email": identity["email"], "name": identity["name"]})
    return RedirectResponse(next_path, status_code=303)


@app.get("/auth/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/auth/sign-in", status_code=303)


@app.get("/auth/unsubscribe", response_class=HTMLResponse)
def unsubscribe_daily_scan(token: str = ""):
    email = newsletter.unsubscribe(token) if token else None
    if email:
        card = notice_card(
            "Daily scan paused",
            "You will no longer receive the FastComps Daily Clinic Market Scan.",
            action="/auth/sign-in", action_label="Open FastComps",
        )
        return _html(access_page(card, title="Daily scan paused"))
    card = notice_card(
        "Link unavailable",
        "This unsubscribe link is invalid. Sign in and contact us if you still need help.",
        action="/auth/sign-in", action_label="Open FastComps",
    )
    return _html(access_page(card, title="Unsubscribe"))


def _threads_for(user_id: str) -> list[dict]:
    try:
        return repository.chat_threads(user_id)
    except Exception:
        return []


@app.get("/", response_class=HTMLResponse)
def index(request: Request, thread: str = ""):
    user = request.session.get("user")
    if not user:
        return _html(landing_page())
    threads = _threads_for(user["id"])
    messages = repository.chat_messages(user["id"], thread) if thread else []
    return _html(chat_page(user, threads, messages, thread_id=thread))


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request):
    user = request.session["user"]
    return _html(dashboard_page(user, _threads_for(user["id"])))


@app.get("/developers", response_class=HTMLResponse)
def developers(request: Request):
    user = request.session.get("user")
    return _html(developer_page(user, _threads_for(user["id"]) if user else []))
