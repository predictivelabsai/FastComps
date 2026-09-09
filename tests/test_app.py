from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient

import main

client = TestClient(main.app, base_url="https://testserver")


@pytest.fixture(autouse=True)
def reset_client():
    client.cookies.clear()
    main._requests.clear()
    yield
    client.cookies.clear()


@pytest.fixture
def signed_in(monkeypatch):
    monkeypatch.setattr(
        main.google_oidc,
        "exchange_google_code",
        lambda code: {"email": "analyst@example.com", "name": "Clinic Analyst", "sub": "google-1"},
    )
    monkeypatch.setattr(main.google_oidc, "save_user", lambda identity: "user-1")
    start = client.get("/auth/google", follow_redirects=False)
    state = parse_qs(urlparse(start.headers["location"]).query)["state"][0]
    callback = client.get(
        "/auth/google/callback",
        params={"code": "one-time-code", "state": state},
        follow_redirects=False,
    )
    assert callback.status_code == 303
    return client


def test_chat_workspace_contract(signed_in):
    response = signed_in.get("/")
    assert response.status_code == 200
    assert "FastComps" in response.text
    assert "New Chat" in response.text
    assert "What do you want to know about the clinic market?" in response.text
    assert "/static/chat.js" in response.text
    assert "Evidence analyst" not in response.text
    assert "analyst@example.com" in response.text
    assert "Sign out" in response.text


def test_dashboard_contract(signed_in):
    response = signed_in.get("/dashboard")
    assert response.status_code == 200
    assert "Evidence analyst" in response.text
    assert "30 EEA MARKETS" in response.text
    assert "Priority watchlist" in response.text
    assert "Candidate queue" in response.text
    assert "COLLECTION HISTORY" in response.text
    assert "Country → treatment type → treatment" in response.text
    assert "treatment-treemap" in response.text


def test_developer_portal_contract(signed_in):
    response = signed_in.get("/developers")
    assert response.status_code == 200
    assert "Build with source-backed clinic intelligence" in response.text
    assert "/api/docs" in response.text
    assert "/api/redoc" in response.text
    assert "/api/openapi/v1.json" in response.text
    assert "Streaming event contract" in response.text


def test_sign_in_offers_google():
    response = client.get("/auth/sign-in")
    assert response.status_code == 200
    assert "Continue with Google" in response.text
    assert "Create an account" in response.text
    assert "Forgot password?" in response.text
    assert 'hx-post="/auth/sign-in?next=/"' in response.text
    assert "openid" not in response.text


def test_signup_form_uses_htmx_and_sends_verification(monkeypatch):
    sent = []
    monkeypatch.setattr(main.accounts, "create_user", lambda *args: {"id": "user-2"})
    monkeypatch.setattr(main.accounts, "create_token", lambda *args, **kwargs: "opaque-token")
    monkeypatch.setattr(main.accounts, "send_account_email", lambda email, **kwargs: sent.append((email, kwargs)) or True)
    response = client.post(
        "/auth/sign-up",
        data={"name": "Market Analyst", "email": "ANALYST@example.com", "password": "password123"},
        headers={"HX-Request": "true"},
    )
    assert response.status_code == 200
    assert "Check your email" in response.text
    assert "<html" not in response.text
    assert sent[0][0] == "analyst@example.com"
    assert sent[0][1]["purpose"] == "verify_email"


def test_email_signin_htmx_redirect(monkeypatch):
    monkeypatch.setattr(main.accounts, "authenticate", lambda *_: ({"id": "user-3", "email": "a@example.com", "name": "A"}, None))
    response = client.post(
        "/auth/sign-in?next=/dashboard",
        data={"email": "a@example.com", "password": "password123"},
        headers={"HX-Request": "true"},
    )
    assert response.status_code == 200
    assert response.headers["hx-redirect"] == "/dashboard"


def test_forgot_password_is_non_enumerating(monkeypatch):
    monkeypatch.setattr(main.accounts, "user_for_email", lambda *_: None)
    response = client.post(
        "/auth/forgot", data={"email": "missing@example.com"}, headers={"HX-Request": "true"}
    )
    assert response.status_code == 200
    assert "If that email is registered" in response.text


def test_unauthenticated_workspace_and_api_are_gated():
    response = client.get("/", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/auth/sign-in?next=/"
    assert client.get("/api/overview").status_code == 401
    assert client.get("/static/auth.css").status_code == 200


def test_google_start_contract():
    response = client.get("/auth/google?next=/", follow_redirects=False)
    assert response.status_code == 302
    parsed = urlparse(response.headers["location"])
    query = parse_qs(parsed.query)
    assert parsed.netloc == "accounts.google.com"
    assert query["redirect_uri"] == ["https://comps.fastsme.com/auth/google/callback"]
    assert query["scope"] == ["openid email profile"]
    assert query["response_type"] == ["code"]
    assert len(query["state"][0]) >= 32


def test_google_callback_rejects_invalid_state():
    response = client.get(
        "/auth/google/callback?code=one-time-code&state=forged",
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/auth/sign-in?error=state"


def test_country_validation(monkeypatch, signed_in):
    monkeypatch.setattr(main.repository,"overview",lambda country: {"country":country})
    assert signed_in.get("/api/overview?country=lt").json() == {"country":"LT"}
    assert signed_in.get("/api/overview?country=lithuania").status_code == 400


def test_read_endpoints_delegate(monkeypatch, signed_in):
    monkeypatch.setattr(main.repository,"coverage",lambda: [{"country_code":"EE"}])
    monkeypatch.setattr(main.repository,"competitors",lambda *args: [{"name":"Clinic"}])
    assert signed_in.get("/api/coverage").json()[0]["country_code"] == "EE"
    assert signed_in.get("/api/competitors").json()[0]["name"] == "Clinic"


def test_treemap_endpoint_delegates(monkeypatch, signed_in):
    monkeypatch.setattr(main.repository, "treatment_treemap", lambda country, limit: [{"country_code": country, "limit": limit}])
    response = signed_in.get("/api/treemap?country=lt&limit=42")
    assert response.json() == [{"country_code": "LT", "limit": 42}]


def test_operational_read_endpoints(monkeypatch, signed_in):
    monkeypatch.setattr(main.repository,"candidates",lambda *args: [{"state":"discovered"}])
    monkeypatch.setattr(main.repository,"watchlist",lambda *args: [{"name":"SYNC"}])
    monkeypatch.setattr(main.repository,"runs",lambda *args: [{"status":"completed"}])
    assert signed_in.get("/api/candidates").json()[0]["state"] == "discovered"
    assert signed_in.get("/api/watchlist").json()[0]["name"] == "SYNC"
    assert signed_in.get("/api/runs").json()[0]["status"] == "completed"


def test_assistant_request(monkeypatch, signed_in):
    monkeypatch.setattr(main,"answer",lambda q,c: {"answer":q,"country":c,"citations":[]})
    response = signed_in.post("/api/assistant",json={"question":"What changed?","country":"EE"})
    assert response.status_code == 200
    assert response.json()["country"] == "EE"


def test_assistant_rejects_empty_question(signed_in):
    assert signed_in.post("/api/assistant",json={"question":""}).status_code == 422


def test_assistant_stream_is_sse(monkeypatch, signed_in):
    monkeypatch.setattr(
        main,
        "stream_answer",
        lambda q, c: iter(
            [
                'event: token\ndata: {"token":"Safe result"}\n\n',
                'event: done\ndata: {"mode":"analytics"}\n\n',
            ]
        ),
    )
    response = signed_in.post(
        "/api/assistant/stream",
        json={"question": "Compare pricing", "country": "lt"},
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["cache-control"] == "no-cache, no-transform"
    assert "event: token" in response.text
    assert "event: done" in response.text
