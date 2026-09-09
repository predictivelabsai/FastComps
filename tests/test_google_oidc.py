from urllib.parse import parse_qs, urlparse

from auth import google_oidc


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


def test_authorization_url_uses_minimal_oidc_scopes(monkeypatch):
    monkeypatch.setattr(google_oidc, "GOOGLE_CLIENT_ID", "client-id")
    monkeypatch.setattr(google_oidc, "GOOGLE_REDIRECT_URI", "https://comps.fastsme.com/auth/google/callback")
    parsed = urlparse(google_oidc.authorization_url("random-state"))
    query = parse_qs(parsed.query)
    assert parsed.scheme == "https"
    assert parsed.netloc == "accounts.google.com"
    assert query["scope"] == ["openid email profile"]
    assert query["state"] == ["random-state"]
    assert query["redirect_uri"] == ["https://comps.fastsme.com/auth/google/callback"]


def test_exchange_validates_and_returns_verified_identity(monkeypatch):
    monkeypatch.setattr(google_oidc, "GOOGLE_CLIENT_ID", "client-id")
    monkeypatch.setattr(google_oidc, "GOOGLE_CLIENT_SECRET", "client-secret")
    monkeypatch.setattr(google_oidc, "GOOGLE_ALLOWED_DOMAINS", set())
    monkeypatch.setattr(google_oidc, "GOOGLE_ALLOWED_EMAILS", set())
    monkeypatch.setattr(
        google_oidc.httpx,
        "post",
        lambda *args, **kwargs: FakeResponse({"id_token": "id-token", "access_token": "access-token"}),
    )

    def fake_get(url, **kwargs):
        if url.endswith("/tokeninfo"):
            return FakeResponse(
                {
                    "aud": "client-id",
                    "iss": "https://accounts.google.com",
                    "email_verified": "true",
                    "email": "Analyst@Example.com",
                    "sub": "google-123",
                }
            )
        return FakeResponse(
            {
                "email": "Analyst@Example.com",
                "email_verified": True,
                "name": "Clinic Analyst",
                "sub": "google-123",
            }
        )

    monkeypatch.setattr(google_oidc.httpx, "get", fake_get)
    assert google_oidc.exchange_google_code("one-time-code") == {
        "email": "analyst@example.com",
        "name": "Clinic Analyst",
        "sub": "google-123",
    }


def test_exchange_rejects_wrong_audience(monkeypatch):
    monkeypatch.setattr(google_oidc, "GOOGLE_CLIENT_ID", "expected-client")
    monkeypatch.setattr(
        google_oidc.httpx,
        "post",
        lambda *args, **kwargs: FakeResponse({"id_token": "id-token", "access_token": "access-token"}),
    )
    monkeypatch.setattr(
        google_oidc.httpx,
        "get",
        lambda *args, **kwargs: FakeResponse(
            {"aud": "other-client", "iss": "https://accounts.google.com", "email_verified": "true"}
        ),
    )
    assert google_oidc.exchange_google_code("one-time-code") is None


def test_exchange_rejects_mismatched_userinfo_subject(monkeypatch):
    monkeypatch.setattr(google_oidc, "GOOGLE_CLIENT_ID", "client-id")
    monkeypatch.setattr(google_oidc, "GOOGLE_ALLOWED_DOMAINS", set())
    monkeypatch.setattr(google_oidc, "GOOGLE_ALLOWED_EMAILS", set())
    monkeypatch.setattr(
        google_oidc.httpx,
        "post",
        lambda *args, **kwargs: FakeResponse({"id_token": "id-token", "access_token": "access-token"}),
    )

    def fake_get(url, **kwargs):
        if url.endswith("/tokeninfo"):
            return FakeResponse(
                {
                    "aud": "client-id",
                    "iss": "accounts.google.com",
                    "email_verified": "true",
                    "email": "analyst@example.com",
                    "sub": "google-123",
                }
            )
        return FakeResponse(
            {"email": "analyst@example.com", "email_verified": True, "sub": "different-user"}
        )

    monkeypatch.setattr(google_oidc.httpx, "get", fake_get)
    assert google_oidc.exchange_google_code("one-time-code") is None


def test_allowlist_is_optional_but_enforced_when_configured(monkeypatch):
    monkeypatch.setattr(google_oidc, "GOOGLE_ALLOWED_DOMAINS", {"predictivelabs.co.uk"})
    monkeypatch.setattr(google_oidc, "GOOGLE_ALLOWED_EMAILS", {"invited@example.com"})
    assert google_oidc._allowed("person@predictivelabs.co.uk")
    assert google_oidc._allowed("invited@example.com")
    assert not google_oidc._allowed("stranger@example.com")
