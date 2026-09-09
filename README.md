# FastComps

Source-backed competitive intelligence for clinics across all 30 EEA markets.

FastComps is a dashboard-first application with a persistent evidence analyst. It shares FastClinic's PostgreSQL server but owns the isolated `fast_comps` schema. FastClinic remains the system collecting its Market data; FastComps mirrors all 18 Market tables losslessly and projects them into an extensible model for verticals, competitors, locations, categories, services/products, observations, sources, candidates, campaigns and watchlists.

## Architecture

- `web`: public read-only dashboard/API on port 5063.
- `worker`: independent lease-protected worker, currently synchronizing FastClinic every five minutes and able to process durable FastComps jobs.
- `fast_clinic` schema: read-only source.
- `fast_comps` schema: application-owned schema and `legacy_*` mirrors.

The model starts with the `clinics` vertical. `offering_type` supports `service` and `product`, so later categories and competitor types do not require a schema fork.

## Run locally

Use only the FastClinic database URL; no MedBackend configuration is required.

```bash
export DATABASE_URL_PROD='postgresql://...'
export DB_SCHEMA=fast_comps
export SOURCE_DB_SCHEMA=fast_clinic
python migration.py
uvicorn main:app --host 0.0.0.0 --port 5063
```

Or run both processes with `docker compose up --build`. Optional `XAI_API_KEY` enables generated assistant answers; without it, the assistant returns deterministic evidence summaries.

## API

- `GET /healthz`
- `GET /api/overview`
- `GET /api/coverage`
- `GET /api/competitors`
- `GET /api/observations`
- `GET /api/locations`
- `GET /api/categories`
- `GET /api/evidence`
- `POST /api/assistant`

All endpoints are public and read-only in the initial release. Mutation routes are intentionally absent until access gating is enabled.

## Deployment

Canonical URL: `https://comps.fastsme.com`. Coolify deploys the compose stack from `main`; `/healthz` is the readiness endpoint. Runtime secrets are synchronized from FastDevOps and are never committed.
