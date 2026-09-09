import os
import sys
from pathlib import Path

os.environ.setdefault("DB_URL","postgresql://unused:unused@127.0.0.1:1/unused")
os.environ.setdefault("GOOGLE_CLIENT_ID", "test-client.apps.googleusercontent.com")
os.environ.setdefault("GOOGLE_CLIENT_SECRET", "test-client-secret")
os.environ.setdefault("GOOGLE_REDIRECT_URI", "https://comps.fastsme.com/auth/google/callback")
os.environ.setdefault("SESSION_SECRET", "test-session-secret-with-sufficient-entropy")
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
