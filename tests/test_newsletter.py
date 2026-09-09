import newsletter


def sample_scan():
    return {
        "date": "2026-09-09", "hours": 36, "fallback": False, "fx_effective_date": "2026-09-08",
        "stats": {"observations": 42, "competitors": 4, "markets": 3, "sources": 9},
        "signals": [{
            "country_code": "LT", "treatment_type": "Diagnostics & imaging", "treatment": "MRI <scan>",
            "lowest_clinic": "Clinic & Co", "lowest_price": 120,
            "lowest_source_url": "https://clinic-low.example/prices",
            "highest_clinic": "Clinic High", "highest_price": 245, "currency": "EUR", "clinic_count": 4,
            "highest_source_url": "https://www.svmarina.com/bg/%D1%86%D0%B5%D0%BD%D0%BE%D1%80%D0%B0%D0%B7%D0%BF%D0%B8%D1%81",
        }],
    }


def test_daily_scan_email_uses_superia_card_pattern_and_safe_sources():
    output = newsletter.render_daily_scan_html(sample_scan(), recipient_email="analyst@example.com")
    assert "Daily Clinic Market Scan" in output
    assert "Daily evidence scan · 1 signals" in output
    assert 'href="https://www.svmarina.com/bg/%D1%86%D0%B5%D0%BD%D0%BE%D1%80%D0%B0%D0%B7%D0%BF%D0%B8%D1%81"' in output
    assert "MRI &lt;scan&gt;" in output
    assert "Clinic &amp; Co" in output
    assert "Clinic High" in output
    assert "120 EUR" in output
    assert "245 EUR" in output
    assert "LOWEST" in output and "HIGHEST" in output
    assert "ECB reference rates" in output
    assert "effective 2026-09-08" in output
    assert "Coverage watch" not in output
    assert "Unmapped" not in output
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


def test_scan_places_lithuania_first_without_crowding_out_other_markets(monkeypatch):
    candidates = [
        {"country_code": "EE", "treatment": "MRI", "currency": "EUR"},
        {"country_code": "LT", "treatment": "Consultation", "currency": "EUR"},
        {"country_code": "LT", "treatment": "Vitamin infusion", "currency": "EUR"},
        {"country_code": "LV", "treatment": "X-ray", "currency": "EUR"},
        {"country_code": "LT", "treatment": "Blood test", "currency": "EUR"},
        {"country_code": "LT", "treatment": "Ultrasound", "currency": "EUR"},
    ]
    monkeypatch.setattr(newsletter, "fetch_one", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(newsletter, "_signal_rows", lambda *_args, **_kwargs: candidates)
    scan = newsletter.build_daily_scan(signal_limit=5)
    assert [row["country_code"] for row in scan["signals"]] == ["LT", "LT", "LT", "EE", "LV"]
    assert "coverage_watch" not in scan
