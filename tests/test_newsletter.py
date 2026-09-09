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
    assert 'src="cid:fastcomps-market-map"' in output
    assert "Country · treatment type · treatment map" in output
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
    attachment = captured["json"]["Attachments"][0]
    assert attachment["ContentType"] == "image/png"
    assert attachment["ContentID"] == "cid:fastcomps-market-map"
    assert attachment["Content"]
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
    assert [row["country_code"] for row in scan["signals"]] == ["LT", "EE", "LV", "LT", "LT"]
    assert "coverage_watch" not in scan


def test_benchmarks_require_different_clinics_and_group_safe_synonyms():
    rows = [
        {"country_code": "LT", "competitor_id": "a", "competitor": "AUM",
         "treatment": "Glutathione infusion", "mapped_type": "IV Therapy",
         "price_min": 70, "high_price": 70, "source_url": "https://a.example", "retrieved_at": "2026-09-09", "fx_effective_date": "2026-09-08"},
        {"country_code": "LT", "competitor_id": "b", "competitor": "UnaVita",
         "treatment": "Vitamin therapy - Glutathione therapy (infusion solution included)", "mapped_type": "IV Therapy",
         "price_min": 75, "high_price": 75, "source_url": "https://b.example", "retrieved_at": "2026-09-09", "fx_effective_date": "2026-09-08"},
        {"country_code": "LT", "competitor_id": "a", "competitor": "AUM",
         "treatment": "Personalized infusion", "mapped_type": "IV Therapy",
         "price_min": 130, "high_price": 130, "source_url": "https://a.example", "retrieved_at": "2026-09-09", "fx_effective_date": "2026-09-08"},
    ]
    result = newsletter._benchmark_rows(rows, 10)
    assert len(result) == 1
    assert result[0]["treatment"] == "Glutathione IV therapy"
    assert result[0]["lowest_clinic"] == "AUM"
    assert result[0]["highest_clinic"] == "UnaVita"
    assert result[0]["lowest_clinic"] != result[0]["highest_clinic"]
    assert result[0]["clinic_count"] == 2
