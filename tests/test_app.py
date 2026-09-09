from fastapi.testclient import TestClient
import main

client = TestClient(main.app)


def test_dashboard_contract():
    response = client.get("/")
    assert response.status_code == 200
    assert "FastComps" in response.text
    assert "Evidence analyst" in response.text
    assert "Sign in" in response.text
    assert "30 EEA MARKETS" in response.text
    assert "Priority watchlist" in response.text
    assert "Candidate queue" in response.text
    assert "COLLECTION HISTORY" in response.text


def test_sign_in_is_public_preview():
    response = client.get("/auth/sign-in")
    assert response.status_code == 200
    assert "No sign-in needed yet" in response.text


def test_country_validation(monkeypatch):
    monkeypatch.setattr(main.repository,"overview",lambda country: {"country":country})
    assert client.get("/api/overview?country=lt").json() == {"country":"LT"}
    assert client.get("/api/overview?country=lithuania").status_code == 400


def test_read_endpoints_delegate(monkeypatch):
    monkeypatch.setattr(main.repository,"coverage",lambda: [{"country_code":"EE"}])
    monkeypatch.setattr(main.repository,"competitors",lambda *args: [{"name":"Clinic"}])
    assert client.get("/api/coverage").json()[0]["country_code"] == "EE"
    assert client.get("/api/competitors").json()[0]["name"] == "Clinic"


def test_operational_read_endpoints(monkeypatch):
    monkeypatch.setattr(main.repository,"candidates",lambda *args: [{"state":"discovered"}])
    monkeypatch.setattr(main.repository,"watchlist",lambda *args: [{"name":"SYNC"}])
    monkeypatch.setattr(main.repository,"runs",lambda *args: [{"status":"completed"}])
    assert client.get("/api/candidates").json()[0]["state"] == "discovered"
    assert client.get("/api/watchlist").json()[0]["name"] == "SYNC"
    assert client.get("/api/runs").json()[0]["status"] == "completed"


def test_assistant_request(monkeypatch):
    monkeypatch.setattr(main,"answer",lambda q,c: {"answer":q,"country":c,"citations":[]})
    response = client.post("/api/assistant",json={"question":"What changed?","country":"EE"})
    assert response.status_code == 200
    assert response.json()["country"] == "EE"


def test_assistant_rejects_empty_question():
    assert client.post("/api/assistant",json={"question":""}).status_code == 422
