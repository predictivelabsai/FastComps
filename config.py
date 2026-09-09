"""Runtime configuration with safe deployment defaults."""
import os

APP_NAME = "FastComps"
APP_VERSION = "0.5.1"
PUBLIC_URL = os.getenv("PUBLIC_URL", "https://comps.fastsme.com").rstrip("/")
PORT = int(os.getenv("PORT", "5063"))
SYNC_INTERVAL_SECONDS = max(30, int(os.getenv("SYNC_INTERVAL_SECONDS", "300")))
WORKER_POLL_SECONDS = max(2, int(os.getenv("WORKER_POLL_SECONDS", "15")))
WORKER_ENABLED = os.getenv("FASTCOMPS_WORKER_ENABLED", "true").lower() in {"1","true","yes"}
DAILY_SCAN_ENABLED = os.getenv("DAILY_SCAN_ENABLED", "true").lower() in {"1", "true", "yes"}
DAILY_SCAN_HOUR_UTC = min(23, max(0, int(os.getenv("DAILY_SCAN_HOUR_UTC", "7"))))
XAI_API_KEY = os.getenv("XAI_API_KEY") or os.getenv("MARKET_LLM_API_KEY")
XAI_BASE_URL = (os.getenv("XAI_BASE_URL") or os.getenv("MARKET_LLM_BASE_URL") or "https://api.x.ai/v1").rstrip("/")
XAI_MODEL = os.getenv("GROK_MODEL") or os.getenv("MARKET_LLM_MODEL") or "grok-4-1-fast-non-reasoning"
EXA_API_KEY = os.getenv("EXA_API_KEY")
SESSION_SECRET = os.getenv("SESSION_SECRET", "")
