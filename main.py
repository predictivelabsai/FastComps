"""FastComps public dashboard and read-only API."""
from __future__ import annotations

import re
import secrets
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from html import escape
from urllib.parse import quote

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.middleware.sessions import SessionMiddleware

from auth import google_oidc
from assistant import answer, stream_answer
from config import APP_NAME, APP_VERSION, PUBLIC_URL, SESSION_SECRET
from db import SCHEMA, connection, init_db
import repository


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    yield


app = FastAPI(title=APP_NAME, version=APP_VERSION, docs_url="/api/docs", lifespan=lifespan)
app.mount("/static", StaticFiles(directory="static"), name="static")
_requests: dict[str, deque[float]] = defaultdict(deque)

if not SESSION_SECRET:
    raise RuntimeError("SESSION_SECRET is required")


@app.middleware("http")
async def require_sign_in(request: Request, call_next):
    path = request.url.path
    public = path in {"/health", "/healthz", "/auth/sign-in", "/auth/google", "/auth/google/callback"}
    if public or path.startswith("/static/"):
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


class AssistantRequest(BaseModel):
    question: str = Field(min_length=2, max_length=500)
    country: str | None = Field(default=None, max_length=2)


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


@app.get("/api/evidence")
def api_evidence(country: str | None = None, limit: int = 30): return repository.evidence(_country(country),limit)


@app.get("/api/candidates")
def api_candidates(country: str | None = None, state: str | None = Query(default=None,max_length=30), limit: int = 100):
    return repository.candidates(_country(country),state,limit)


@app.get("/api/watchlist")
def api_watchlist(country: str | None = None): return repository.watchlist(_country(country))


@app.get("/api/runs")
def api_runs(limit: int = 30): return repository.runs(limit)


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
    return StreamingResponse(
        stream_answer(payload.question.strip(), _country(payload.country)),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"},
    )


@app.get("/auth/sign-in",response_class=HTMLResponse)
def sign_in(request: Request, next: str = "/", error: str = ""):
    if request.session.get("user"):
        return RedirectResponse("/", status_code=303)
    safe_next = next if next.startswith("/") and not next.startswith("//") else "/"
    message = "<p class='auth-error'>Google sign-in failed. Please try again.</p>" if error else ""
    return f"""<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width'><meta name='robots' content='noindex'><title>Sign in · FastComps</title><link rel='icon' href='/static/favicon.svg'><link rel='stylesheet' href='/static/app.css'><link rel='stylesheet' href='/static/auth.css'></head><body class='signin-body'><main class='signin-card'><a class='brand' href='/'><span>F</span>FastComps</a><p class='eyebrow'>SECURE WORKSPACE</p><h1>Sign in to FastComps</h1><p>Continue with your Google account to access clinic competitive intelligence and source-backed analysis.</p>{message}<a class='google-button' href='/auth/google?next={escape(safe_next, quote=True)}'><span class='google-g'>G</span>Continue with Google</a><p class='signin-note'>FastComps requests only your basic profile and verified email.</p></main></body></html>"""


@app.get("/auth/google")
def google_start(request: Request, next: str = "/"):
    if not google_oidc.enabled():
        return RedirectResponse("/auth/sign-in?error=not_configured", status_code=303)
    safe_next = next if next.startswith("/") and not next.startswith("//") else "/"
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
    request.session.clear()
    request.session["user"] = {"id": user_id, "email": identity["email"], "name": identity["name"]}
    return RedirectResponse(next_path, status_code=303)


@app.get("/auth/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/auth/sign-in", status_code=303)


@app.get("/",response_class=HTMLResponse)
def index(request: Request):
    user = request.session["user"]
    return DASHBOARD_HTML.replace("{{USER_EMAIL}}", escape(user["email"]))


DASHBOARD_HTML = """<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="description" content="Source-backed competitive intelligence for clinics across the EEA."><title>FastComps · Clinic market intelligence</title><link rel="icon" href="/static/favicon.svg"><link rel="stylesheet" href="/static/app.css"><link rel="stylesheet" href="/static/market.css"><link rel="stylesheet" href="/static/auth.css"></head><body>
<header class="topbar"><a class="brand" href="/"><span>F</span>FastComps</a><nav><button data-view="overview" class="nav-button active">Overview</button><button data-view="competitors" class="nav-button">Competitors</button><button data-view="coverage" class="nav-button">Coverage</button><button data-view="evidence" class="nav-button">Evidence</button></nav><div class="header-actions"><label class="market-picker"><span>Market</span><select id="country"><option value="">All EEA</option></select></label><span class="signed-in">{{USER_EMAIL}}</span><a class="sign-in" href="/auth/logout">Sign out</a></div></header>
<main class="workspace"><section class="content"><div class="intro"><div><p class="eyebrow">CLINICS · COMPETITIVE INTELLIGENCE</p><h1>See the market as evidence, not noise.</h1><p>Track competitors, service portfolios and published prices across 30 EEA markets—each claim linked back to its source.</p></div><div class="sync-pill"><i></i><span id="sync-status">Connecting to evidence base…</span></div></div>
<section class="metrics" id="metrics"><article class="skeleton"></article><article class="skeleton"></article><article class="skeleton"></article><article class="skeleton"></article></section>
<section class="panel view-panel" data-panel="overview"><div class="panel-head"><div><p class="eyebrow">MARKET SIGNAL</p><h2>Competitive footprint</h2></div><span class="panel-note">Verified locations only</span></div><div class="overview-grid"><div id="market-map" class="market-map"><div class="map-label">EEA clinic locations</div></div><div><h3>Category depth</h3><div id="categories" class="bar-list"></div></div></div></section>
<section class="panel view-panel" data-panel="overview"><div class="panel-head"><div><p class="eyebrow">LATEST EVIDENCE</p><h2>Observed services & prices</h2></div><input id="price-search" class="compact-input" placeholder="Filter service or clinic"></div><div class="table-wrap"><table><thead><tr><th>Competitor</th><th>Offering</th><th>Price</th><th>Type</th><th>Market</th><th>Evidence</th></tr></thead><tbody id="prices"></tbody></table></div></section>
<section class="panel view-panel hidden" data-panel="competitors"><div class="panel-head"><div><p class="eyebrow">LANDSCAPE</p><h2>Competitors</h2></div><input id="competitor-search" class="compact-input" placeholder="Search competitors"></div><div class="table-wrap"><table><thead><tr><th>Competitor</th><th>Market</th><th>Locations</th><th>Offerings</th><th>Evidence</th><th>Last observed</th></tr></thead><tbody id="competitors"></tbody></table></div></section>
<section class="panel view-panel hidden" data-panel="coverage"><div class="panel-head"><div><p class="eyebrow">30 EEA MARKETS</p><h2>Coverage status</h2></div><span class="panel-note">Target: 10 verified competitors / market</span></div><div id="coverage-grid" class="coverage-grid"></div><div class="subpanel-head"><div><p class="eyebrow">CURATED MONITORING</p><h2>Priority watchlist</h2></div></div><div id="watchlist-grid" class="watchlist-grid"></div><div class="subpanel-head"><div><p class="eyebrow">DISCOVERY PIPELINE</p><h2>Candidate queue</h2></div><span class="panel-note">Every lead retained for review</span></div><div class="table-wrap"><table><thead><tr><th>Candidate</th><th>Market</th><th>State</th><th>Sources</th><th>Last seen</th></tr></thead><tbody id="candidates"></tbody></table></div></section>
<section class="panel view-panel hidden" data-panel="evidence"><div class="panel-head"><div><p class="eyebrow">SOURCE REGISTER</p><h2>Recent evidence</h2></div><span class="panel-note">Retained snapshots</span></div><div id="evidence-list" class="evidence-list"></div><div class="subpanel-head"><div><p class="eyebrow">COLLECTION HISTORY</p><h2>Recent runs</h2></div></div><div class="table-wrap"><table><thead><tr><th>Run</th><th>Trigger</th><th>Status</th><th>Started</th><th>Result</th></tr></thead><tbody id="runs"></tbody></table></div></section></section>
<aside class="assistant"><div class="assistant-head"><div class="assistant-mark">✦</div><div><p class="eyebrow">FASTCOMPS AI</p><h2>Evidence analyst</h2></div><span class="live-dot">LIVE</span></div><div id="assistant-feed" class="assistant-feed" aria-live="polite"><div class="assistant-message"><p>Ask about competitors, coverage, services or prices. I’ll stream a governed analysis and keep its evidence visible.</p></div><div class="suggestions"><button>Which markets need attention?</button><button>Compare clinic pricing in Lithuania</button><button>Where is IV therapy observed?</button></div></div><form id="assistant-form" class="assistant-form"><textarea id="question" rows="2" maxlength="500" placeholder="Ask about this market…" required></textarea><button aria-label="Send question">↑</button></form><p class="assistant-foot">Read-only governed analytics · No SQL exposed</p></aside></main><script src="/static/app.js" defer></script></body></html>"""
