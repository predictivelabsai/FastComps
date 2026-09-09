# FastComps

Source-backed competitive intelligence for clinics across all 30 EEA markets.

FastComps is a chat-first application with a separate evidence dashboard. It shares FastClinic's PostgreSQL server but owns the isolated `fast_comps` schema. FastClinic remains the system collecting its Market data; FastComps mirrors all 18 Market tables losslessly and projects them into an extensible model for verticals, competitors, locations, categories, services/products, observations, sources, candidates, campaigns and watchlists.

## Architecture

- `web`: FastHTML/HTMX chat, dashboard, account access and developer portal, plus a governed read-only FastAPI surface on port 5063.
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

Or run both processes with `docker compose up --build`. Optional `XAI_API_KEY` enables generated assistant answers; without it, the assistant returns deterministic evidence summaries. Google sign-in uses `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, and `GOOGLE_REDIRECT_URI`. Email/password registration and recovery use `POSTMARK_API_TOKEN` and `FROM_EMAIL`. A strong, randomly generated `SESSION_SECRET` is mandatory.

## Product surfaces

- `/`: public product landing for anonymous visitors; central streamed conversation workspace with persisted history after sign-in.
- `/dashboard`: market overview, competitor, OpenStreetMap, coverage and evidence views; this is the only surface with the compact Evidence Analyst. Country flag filters are URL-addressable and shared across the dashboard.
- `/dashboard`: Plotly treemap with country → treatment type → treatment hierarchy, observation-based area and within-country EUR-relative price colour. Selecting a treatment drills into its retained price evidence.
- `/competitors/{competitor_id}`: provider footprint, clinic locations and published treatment prices with relative market-level bands and direct evidence links.
- `/developers`: public developer guide, API resource catalogue, quick starts and links to public Swagger, ReDoc and versioned OpenAPI contracts. Data calls remain authenticated.
- `/auth/sign-up`, `/auth/sign-in`, `/auth/forgot`, `/auth/reset`: FastHTML account flows enhanced with HTMX; Google OIDC remains available.

English, Estonian and Lithuanian are available from the flag selector on every public, account and signed-in surface. The selection is stored in the signed session, preserves the current dashboard filter/tab, localises browser-generated country names and number/date formatting, and also controls streamed analyst responses. Checked-in catalogs live in `locales/`.

## Daily Clinic Market Scan

The worker sends a Superia-inspired daily email at `DAILY_SCAN_HOUR_UTC` (07:00 UTC by default). Lithuania leads the digest, followed by comparable treatment benchmarks that are admitted only when at least two distinct clinics publish prices; LOWEST and HIGHEST can never repeat the same clinic. Country breadth is selected before additional comparisons from the same market, and every clinic endpoint links directly to its evidence. Each email embeds a server-rendered PNG of the country → treatment type → treatment comparison map, while the authenticated Daily Scan portal renders the same hierarchy as an interactive Plotly treemap with drill-down. A six-hour ingester persists the ECB daily reference table and all displayed prices are converted to EUR; original currency amounts remain retained for audit. Unpriced and single-clinic records remain retained for future scans but are excluded from the email, as is operational coverage-queue reporting. Delivery is deduplicated per user/day and every message includes a signed unsubscribe link.

```bash
python -m scripts.daily_scan --dry-run
python -m scripts.daily_scan --to analyst@example.com
python -m scripts.daily_scan --all
```

Set `DAILY_SCAN_ENABLED=false` to disable the scheduled send without disabling the collection worker.

## API

- `GET /healthz`
- `GET /api/overview`
- `GET /api/coverage`
- `GET /api/competitors`
- `GET /api/competitors/{competitor_id}`
- `GET /api/observations`
- `GET /api/locations`
- `GET /api/categories`
- `GET /api/treemap`
- `GET /api/evidence`
- `GET /api/candidates`
- `GET /api/watchlist`
- `GET /api/runs`
- `POST /api/assistant`
- `POST /api/assistant/stream` (SSE progress, governed analysis, inline visual data and citations)
- `GET /api/threads` and `GET /api/threads/{thread_id}`

The workspaces and API require a signed session. Users can authenticate with Google or a verified email/password account; `/healthz`, static assets, and the account access routes remain public. Market mutation routes are intentionally absent.

## Product tour

The landing-page animation is captured from the real signed-in FastHTML application. With local development dependencies installed, regenerate it with:

```bash
.venv/bin/python scripts/demo_walkthrough.py
```

The script starts a local server, captures the chat and key dashboard views into `output/playwright/`, and writes the optimised public asset to `static/product-demo.gif`.
When the database URL lives in another ignored environment file, pass its path as `DEMO_ENV_FILE`.

Conversational analytics never accepts or exposes SQL. The model can select only an allowlisted metric, dimension and bounded filters; FastComps compiles the PostgreSQL internally, runs it in a read-only transaction with a five-second statement timeout, and returns aggregate results with coverage and retained-source context.

## Deployment

Canonical URL: `https://comps.fastsme.com`. Coolify deploys the compose stack from `main`; `/healthz` is the readiness endpoint. Runtime secrets are synchronized from FastDevOps and are never committed.
