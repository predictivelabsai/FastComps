from fastapi.testclient import TestClient

from i18n import catalog, safe_return_path, t
from main import app


def test_catalogs_include_core_navigation_and_streaming_copy():
    for lang in ("et", "lt"):
        translations = catalog(lang)
        assert translations["Sign in"] != "Sign in"
        assert translations["Dashboard"] != "Dashboard"
        assert translations["Understanding your question…"] != "Understanding your question…"
        assert t("{metric} by {dimension}", lang, metric="X", dimension="Y") != "X by Y"


def test_language_selection_persists_and_returns_to_fragment():
    client = TestClient(app, base_url="https://testserver")
    response = client.get(
        "/set-lang/et",
        params={"next": "/dashboard?country=EE#coverage"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/dashboard?country=EE#coverage"
    page = client.get("/auth/sign-in")
    assert 'lang="et"' in page.text
    assert "Logi FastCompsi sisse" in page.text


def test_accept_language_selects_lithuanian_on_first_visit():
    client = TestClient(app, base_url="https://testserver")
    page = client.get("/", headers={"Accept-Language": "lt-LT,lt;q=0.9,en;q=0.5"})
    assert page.status_code == 200
    assert 'lang="lt"' in page.text
    assert "Matykite klinikų rinką, o ne triukšmą" in page.text


def test_language_return_path_rejects_external_redirects():
    assert safe_return_path("https://evil.example/phish") == "/"
    assert safe_return_path("//evil.example/phish") == "/"
