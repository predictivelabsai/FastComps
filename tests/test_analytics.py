import json

import analytics


def _events(chunks):
    parsed = []
    for chunk in chunks:
        lines = chunk.strip().splitlines()
        parsed.append((lines[0].removeprefix("event: "), json.loads(lines[1].removeprefix("data: "))))
    return parsed


def test_deterministic_plan_routes_coverage_and_country():
    plan = analytics.plan_question("Which markets have a coverage gap in Lithuania?", use_model=False)
    assert plan == analytics.AnalysisPlan("coverage_gap", "market", "LT")


def test_deterministic_plan_extracts_offering_search():
    plan = analytics.plan_question("Where is IV therapy observed?", use_model=False)
    assert plan == analytics.AnalysisPlan("observation_count", "market", search="IV therapy")


def test_known_intent_does_not_depend_on_model(monkeypatch):
    monkeypatch.setattr(analytics, "_model_plan", lambda *_: (_ for _ in ()).throw(AssertionError("model called")))
    assert analytics.plan_question("Where is IV therapy observed?").metric == "observation_count"


def test_normalisation_enforces_allowlist_and_bounds():
    assert analytics._normalise_plan({"metric": "drop_table"}, None) is None
    plan = analytics._normalise_plan(
        {
            "metric": "median_price",
            "dimension": "raw_sql",
            "country": "XX",
            "search": "a" * 120,
            "limit": 999,
        },
        None,
    )
    assert plan.metric == "median_price"
    assert plan.dimension == "offering"
    assert plan.country is None
    assert plan.search == "a" * 80
    assert plan.limit == 20


def test_query_compiler_parameterises_user_filters():
    attack = "IV therapy'; DROP TABLE observations; --"
    sql, params = analytics.build_query(
        analytics.AnalysisPlan("observation_count", "market", "LT", attack, 9)
    )
    assert attack not in sql
    assert params == {"limit": 9, "country": "LT", "search": f"%{attack}%"}
    assert "%(search)s" in sql
    assert "LIMIT %(limit)s" in sql


def test_category_analytics_never_exposes_unmapped_label():
    sql, _ = analytics.build_query(analytics.AnalysisPlan("observation_count", "category"))
    assert "Unmapped" not in sql
    assert "General medicine & other treatments" in sql


def test_median_price_converts_every_currency_to_eur():
    sql, _ = analytics.build_query(analytics.AnalysisPlan("median_price", "market"))
    assert "exchange_rates fx ON fx.currency=o.currency" in sql
    assert "o.price_min/fx.units_per_eur" in sql
    assert "'EUR'::text AS currency" in sql
    assert "GROUP BY c.country_code" in sql


def test_stream_contract_contains_no_sql(monkeypatch):
    plan = analytics.AnalysisPlan("coverage_gap", "market")
    monkeypatch.setattr("assistant.plan_question", lambda *_: plan)
    monkeypatch.setattr(
        "assistant.execute_plan",
        lambda _, lang="en": {
            "summary": "Estonia has a coverage gap.",
            "visual": {"kind": "bar", "title": "Coverage gap", "rows": [{"label": "EE", "value": 4}]},
            "citations": [{"label": "Clinic source", "url": "https://example.test/evidence"}],
            "evidence": {"records": 6, "sources": 1, "markets": 30},
        },
    )

    from assistant import stream_answer

    events = _events(stream_answer("Which markets need attention?"))
    assert [name for name, _ in events] == [
        "progress", "plan", "progress", "progress", "visual", "token", "token", "token", "token", "token", "citations", "done"
    ]
    payload = json.dumps(events)
    assert "SELECT " not in payload
    assert "fast_comps." not in payload
