# FastClinic Market migration

FastComps reads `fast_clinic` and writes only `fast_comps`. Every synchronization rebuilds the following 18 raw mirrors in one transaction, then upserts the generic projection. The raw tables retain every source column and row.

| FastClinic table | Raw mirror | Generic destination |
|---|---|---|
| market_address_attempt | legacy_market_address_attempt | address_attempts |
| market_candidate | legacy_market_candidate | candidates |
| market_candidate_source | legacy_market_candidate_source | candidate_sources |
| market_clinic | legacy_market_clinic | competitor_locations |
| market_config | legacy_market_config | vertical_settings |
| market_country_campaign | legacy_market_country_campaign | coverage_campaigns |
| market_geocode_cache | legacy_market_geocode_cache | geocode_cache |
| market_geocode_gate | legacy_market_geocode_gate | geocode_gates |
| market_hospital | legacy_market_hospital | competitors |
| market_lock | legacy_market_lock | raw source-worker state |
| market_observation | legacy_market_observation | observations, competitor_offerings |
| market_run | legacy_market_run | collection_runs |
| market_service | legacy_market_service | offerings |
| market_service_taxonomy | legacy_market_service_taxonomy | offerings taxonomy link |
| market_source | legacy_market_source | sources, source_snapshots |
| market_taxonomy_node | legacy_market_taxonomy_node | categories |
| market_watchlist | legacy_market_watchlist | watchlists, watchlist_targets |
| search_provider_credentials | legacy_search_provider_credentials | provider_credentials (ciphertext only) |

Generic rows retain `source_system`, `legacy_table` and `legacy_id`. Source price semantics remain distinct: `exact`, `from`, `range` and `unavailable`. Raw service labels are retained in `observations.original_name`; unmatched services remain valid offerings with no forced taxonomy category.
