"""Runtime configuration with safe deployment defaults."""
import os

APP_NAME = "FastComps"
APP_VERSION = "0.8.1"
PUBLIC_URL = os.getenv("PUBLIC_URL", "https://comps.fastsme.com").rstrip("/")
PORT = int(os.getenv("PORT", "5063"))
SYNC_INTERVAL_SECONDS = max(30, int(os.getenv("SYNC_INTERVAL_SECONDS", "300")))
WORKER_POLL_SECONDS = max(2, int(os.getenv("WORKER_POLL_SECONDS", "15")))
WORKER_ENABLED = os.getenv("FASTCOMPS_WORKER_ENABLED", "true").lower() in {"1","true","yes"}
DAILY_SCAN_ENABLED = os.getenv("DAILY_SCAN_ENABLED", "true").lower() in {"1", "true", "yes"}
DAILY_SCAN_HOUR_LOCAL = min(23, max(0, int(os.getenv("DAILY_SCAN_HOUR_LOCAL", "8"))))
DAILY_SCAN_TIMEZONE = os.getenv("DAILY_SCAN_TIMEZONE", "Europe/Vilnius")
# Email cadence: "daily" (default) or "weekly" (sent only on DAILY_SCAN_WEEKDAY,
# 0=Mon … 6=Sun, at DAILY_SCAN_HOUR_LOCAL in DAILY_SCAN_TIMEZONE).
DAILY_SCAN_FREQUENCY = (os.getenv("DAILY_SCAN_FREQUENCY") or "daily").strip().lower()
DAILY_SCAN_WEEKDAY = min(6, max(0, int((os.getenv("DAILY_SCAN_WEEKDAY") or "0").strip() or 0)))
INITIAL_DAILY_SCAN_RECIPIENTS = tuple(filter(None, (
    email.strip().lower()
    for email in os.getenv(
        "INITIAL_DAILY_SCAN_RECIPIENTS", "kaljuvee@gmail.com,mj@1am.lt"
    ).split(",")
)))
XAI_API_KEY = os.getenv("XAI_API_KEY") or os.getenv("MARKET_LLM_API_KEY")
XAI_BASE_URL = (os.getenv("XAI_BASE_URL") or os.getenv("MARKET_LLM_BASE_URL") or "https://api.x.ai/v1").rstrip("/")
XAI_MODEL = os.getenv("GROK_MODEL") or os.getenv("MARKET_LLM_MODEL") or "grok-4-1-fast-non-reasoning"
EXA_API_KEY = os.getenv("EXA_API_KEY")
SESSION_SECRET = os.getenv("SESSION_SECRET", "")
