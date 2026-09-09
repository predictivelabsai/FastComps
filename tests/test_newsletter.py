import newsletter


def sample_scan():
    return {
        "date": "2026-09-09", "hours": 36, "fallback": False,
        "stats": {"observations": 42, "competitors": 4, "markets": 3, "sources": 9},
        "signals": [{
            "country_code": "BG", "treatment_type": "Diagnostics", "treatment": "MRI <scan>",
            "competitor": "Clinic & Co", "price_min": 120, "price_max": None, "currency": "EUR",
            "source_url": "https://www.svmarina.com/bg/%D1%86%D0%B5%D0%BD%D0%BE%D1%80%D0%B0%D0%B7%D0%BF%D0%B8%D1%81",
        }],
        "coverage_watch": [{"country_code": "IS", "country_name": "Iceland", "verified": 1, "target": 10, "observations": 5}],
    }


def test_daily_scan_email_uses_superia_card_pattern_and_safe_sources():
    output = newsletter.render_daily_scan_html(sample_scan(), recipient_email="analyst@example.com")
    assert "Daily Clinic Market Scan" in output
    assert "Daily evidence scan · 1 signals" in output
    assert "svmarina.com/bg/ценоразпис" in output
    assert "MRI &lt;scan&gt;" in output
    assert "Clinic &amp; Co" in output
    assert "/auth/unsubscribe?token=" in output


def test_daily_scan_postmark_contract(monkeypatch):
    captured = {}

    class Response:
        def raise_for_status(self): return None
        def json(self): return {"ErrorCode": 0, "MessageID": "message-1"}

    def fake_post(url, **kwargs):
        captured.update({"url": url, **kwargs})
        return Response()

    monkeypatch.setenv("POSTMARK_API_TOKEN", "server-token")
    monkeypatch.setattr(newsletter.httpx, "post", fake_post)
    result = newsletter.send_daily_scan("kaljuvee@gmail.com", scan=sample_scan())
    assert result == {"ok": True, "to": "kaljuvee@gmail.com", "message_id": "message-1"}
    assert captured["json"]["Tag"] == "fastcomps-daily-scan"
    assert "Daily Clinic Market Scan" in captured["json"]["Subject"]
    assert "server-token" not in str(captured["json"])
