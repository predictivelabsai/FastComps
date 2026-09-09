from db import DDL,EEA_MARKETS
from migration import SOURCE_TABLES,_decimal,_id,_json,_ts


def test_all_30_eea_markets_are_seeded():
    assert len(EEA_MARKETS) == 30
    assert len({code for code,_ in EEA_MARKETS}) == 30
    assert {"EE","LT","LV","IS","LI","NO"} <= {code for code,_ in EEA_MARKETS}


def test_complete_market_subsystem_is_mirrored():
    assert len(SOURCE_TABLES) == 18
    assert "market_observation" in SOURCE_TABLES
    assert "market_address_attempt" in SOURCE_TABLES
    assert "search_provider_credentials" in SOURCE_TABLES


def test_operational_tables_have_generic_destinations():
    for table in ("vertical_settings","address_attempts","geocode_cache","geocode_gates","provider_credentials","users","account_tokens","newsletter_deliveries","user_sessions","api_keys"):
        assert f"fast_comps.{table}" in DDL


def test_source_ids_are_namespaced():
    assert _id("abc") == "fc:abc"
    assert _id(None) is None


def test_source_values_are_conservative():
    assert str(_decimal("12,50")) == "12.50"
    assert _decimal("unavailable") is None
    assert _json('["x"]',[]) == ["x"]
    assert _json("not json",{}) == {}
    assert _ts("2026-09-09T10:00:00Z") is not None
