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


def test_dashboard_contract(signed_in):
    response = signed_in.get("/")
    assert response.status_code == 200
    assert "FastComps" in response.text
    assert "Evidence analyst" in response.text
    assert "analyst@example.com" in response.text
    assert "Sign out" in response.text
    assert "30 EEA MARKETS" in response.text
    assert "Priority watchlist" in response.text
    assert "Candidate queue" in response.text
    assert "COLLECTION HISTORY" in response.text


def test_sign_in_offers_google():
    response = client.get("/auth/sign-in")
    assert response.status_code == 200
    assert "Continue with Google" in response.text
    assert "openid" not in response.text


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
