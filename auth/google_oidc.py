"""Google OpenID Connect helpers for FastComps."""

from __future__ import annotations

import os
import secrets
from urllib.parse import urlencode

import httpx

from db import SCHEMA, connection


GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")
GOOGLE_REDIRECT_URI = os.getenv(
    "GOOGLE_REDIRECT_URI", "https://comps.fastsme.com/auth/google/callback"
)
GOOGLE_ALLOWED_DOMAINS = {
    item.strip().lower()
    for item in os.getenv("GOOGLE_ALLOWED_DOMAINS", "").split(",")
    if item.strip()
}
GOOGLE_ALLOWED_EMAILS = {
    item.strip().lower()
    for item in os.getenv("GOOGLE_ALLOWED_EMAILS", "").split(",")
    if item.strip()
}


def enabled() -> bool:
    return bool(GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET and GOOGLE_REDIRECT_URI)


def new_state() -> str:
    return secrets.token_urlsafe(32)


def authorization_url(state: str) -> str:
    query = urlencode(
        {
            "client_id": GOOGLE_CLIENT_ID,
            "redirect_uri": GOOGLE_REDIRECT_URI,
            "response_type": "code",
            "scope": "openid email profile",
            "state": state,
            "access_type": "online",
            "prompt": "select_account",
        }
    )
    return f"https://accounts.google.com/o/oauth2/v2/auth?{query}"


def _allowed(email: str) -> bool:
    if not GOOGLE_ALLOWED_DOMAINS and not GOOGLE_ALLOWED_EMAILS:
        return True
    domain = email.rsplit("@", 1)[-1]
    return email in GOOGLE_ALLOWED_EMAILS or domain in GOOGLE_ALLOWED_DOMAINS


def exchange_google_code(code: str) -> dict[str, str] | None:
    """Exchange a one-time code and validate the returned OIDC identity."""
    try:
        token_response = httpx.post(
            "https://oauth2.googleapis.com/token",
            data={
                "code": code,
                "client_id": GOOGLE_CLIENT_ID,
                "client_secret": GOOGLE_CLIENT_SECRET,
                "redirect_uri": GOOGLE_REDIRECT_URI,
                "grant_type": "authorization_code",
            },
            timeout=20,
        )
        token_response.raise_for_status()
        tokens = token_response.json()
        id_token = tokens.get("id_token")
        access_token = tokens.get("access_token")
        if not id_token or not access_token:
            return None

        claims_response = httpx.get(
            "https://oauth2.googleapis.com/tokeninfo",
            params={"id_token": id_token},
            timeout=20,
        )
        claims_response.raise_for_status()
        claims = claims_response.json()
        if claims.get("aud") != GOOGLE_CLIENT_ID or claims.get("iss") not in {
            "accounts.google.com",
            "https://accounts.google.com",
        }:
            return None
        if str(claims.get("email_verified", "")).lower() != "true":
            return None

        userinfo_response = httpx.get(
            "https://openidconnect.googleapis.com/v1/userinfo",
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=20,
        )
        userinfo_response.raise_for_status()
        userinfo = userinfo_response.json()
        email = str(claims.get("email") or "").strip().lower()
        subject = str(claims.get("sub") or "")
        userinfo_email = str(userinfo.get("email") or "").strip().lower()
        userinfo_subject = str(userinfo.get("sub") or "")
        if not email or not subject or not _allowed(email):
            return None
        if userinfo.get("email_verified") is False:
            return None
        if userinfo_email and userinfo_email != email:
            return None
        if userinfo_subject and userinfo_subject != subject:
            return None
        return {
            "email": email,
            "name": str(userinfo.get("name") or email),
            "sub": subject,
        }
    except (httpx.HTTPError, KeyError, TypeError, ValueError):
        return None


def save_user(identity: dict[str, str]) -> str:
    with connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"""INSERT INTO {SCHEMA}.users (email,name,google_sub,email_verified)
                VALUES (%(email)s,%(name)s,%(sub)s,TRUE)
                ON CONFLICT (email) DO UPDATE SET
                  name=COALESCE(NULLIF(EXCLUDED.name,''),{SCHEMA}.users.name),
                  google_sub=EXCLUDED.google_sub,email_verified=TRUE,updated_at=NOW()
                RETURNING id""",
            {"email": identity["email"], "name": identity.get("name"), "sub": identity["sub"]},
        )
        user_id = str(cur.fetchone()[0])
        conn.commit()
        return user_id
