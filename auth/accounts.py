"""Email/password accounts, verification and password recovery for FastComps."""

from __future__ import annotations

import hashlib
import html
import logging
import os
import re
import secrets
from datetime import datetime, timedelta, timezone

import bcrypt
import httpx
from psycopg2.extras import RealDictCursor

from config import PUBLIC_URL
from db import SCHEMA, connection


log = logging.getLogger(__name__)
EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


def normalize_email(value: str) -> str:
    return value.strip().lower()


def valid_email(value: str) -> bool:
    return bool(EMAIL_RE.fullmatch(normalize_email(value)))


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except (TypeError, ValueError):
        return False


def create_user(email: str, password: str, name: str = "") -> dict | None:
    email = normalize_email(email)
    with connection() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            f"""INSERT INTO {SCHEMA}.users (email,name,password_hash,email_verified)
                VALUES (%s,%s,%s,FALSE)
                ON CONFLICT (email) DO NOTHING
                RETURNING id,email,name,role,email_verified""",
            (email, name.strip() or None, hash_password(password)),
        )
        row = cur.fetchone()
        conn.commit()
        return dict(row) if row else None


def authenticate(email: str, password: str) -> tuple[dict | None, str | None]:
    with connection(read_only=True) as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            f"""SELECT id,email,name,role,password_hash,email_verified
                FROM {SCHEMA}.users WHERE lower(email)=%s""",
            (normalize_email(email),),
        )
        row = cur.fetchone()
    if not row or not row["password_hash"] or not verify_password(password, row["password_hash"]):
        return None, "invalid"
    if not row["email_verified"]:
        return None, "unverified"
    user = dict(row)
    user.pop("password_hash", None)
    return user, None


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_token(user_id: str, purpose: str, *, lifetime_minutes: int) -> str:
    token = secrets.token_urlsafe(48)
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=lifetime_minutes)
    with connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"UPDATE {SCHEMA}.account_tokens SET used_at=NOW() WHERE user_id=%s AND purpose=%s AND used_at IS NULL",
            (user_id, purpose),
        )
        cur.execute(
            f"""INSERT INTO {SCHEMA}.account_tokens (user_id,purpose,token_hash,expires_at)
                VALUES (%s,%s,%s,%s)""",
            (user_id, purpose, _token_hash(token), expires_at),
        )
        conn.commit()
    return token


def user_for_email(email: str) -> dict | None:
    with connection(read_only=True) as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            f"SELECT id,email,name,role,email_verified FROM {SCHEMA}.users WHERE lower(email)=%s",
            (normalize_email(email),),
        )
        row = cur.fetchone()
        return dict(row) if row else None


def verify_email_token(token: str) -> dict | None:
    return _consume_token(token, "verify_email", verify_email=True)


def reset_password(token: str, password: str) -> dict | None:
    return _consume_token(token, "reset_password", new_password=password)


def _consume_token(
    token: str,
    purpose: str,
    *,
    verify_email: bool = False,
    new_password: str | None = None,
) -> dict | None:
    with connection() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            f"""SELECT t.id,t.user_id,u.email,u.name,u.role
                FROM {SCHEMA}.account_tokens t
                JOIN {SCHEMA}.users u ON u.id=t.user_id
                WHERE t.token_hash=%s AND t.purpose=%s AND t.used_at IS NULL AND t.expires_at>NOW()
                FOR UPDATE""",
            (_token_hash(token), purpose),
        )
        row = cur.fetchone()
        if not row:
            return None
        if verify_email:
            cur.execute(
                f"UPDATE {SCHEMA}.users SET email_verified=TRUE,updated_at=NOW() WHERE id=%s",
                (row["user_id"],),
            )
        if new_password is not None:
            cur.execute(
                f"UPDATE {SCHEMA}.users SET password_hash=%s,email_verified=TRUE,updated_at=NOW() WHERE id=%s",
                (hash_password(new_password), row["user_id"]),
            )
        cur.execute(f"UPDATE {SCHEMA}.account_tokens SET used_at=NOW() WHERE id=%s", (row["id"],))
        conn.commit()
        return {
            "id": str(row["user_id"]),
            "email": row["email"],
            "name": row["name"] or row["email"],
            "role": row["role"],
        }


def send_account_email(email: str, *, purpose: str, token: str) -> bool:
    api_token = os.getenv("POSTMARK_API_TOKEN", "")
    if not api_token:
        log.error("POSTMARK_API_TOKEN is not configured")
        return False
    if purpose == "verify_email":
        url = f"{PUBLIC_URL}/auth/verify?token={token}"
        subject = "Verify your FastComps account"
        heading = "Verify your email"
        copy = "Confirm your email address to finish creating your FastComps account."
        button = "Verify email"
    else:
        url = f"{PUBLIC_URL}/auth/reset?token={token}"
        subject = "Reset your FastComps password"
        heading = "Reset your password"
        copy = "Use this one-time link to choose a new password. It expires in one hour."
        button = "Reset password"
    safe_url = html.escape(url, quote=True)
    body = f"""<div style="font-family:Inter,Arial,sans-serif;max-width:520px;margin:auto;padding:32px">
    <h1 style="color:#12241f">{heading}</h1><p style="color:#65756f;line-height:1.6">{copy}</p>
    <p style="margin:28px 0"><a href="{safe_url}" style="background:#177357;color:white;padding:12px 18px;border-radius:8px;text-decoration:none">{button}</a></p>
    <p style="color:#8a9692;font-size:12px">If you did not request this, you can ignore this email.</p></div>"""
    try:
        response = httpx.post(
            "https://api.postmarkapp.com/email",
            headers={"X-Postmark-Server-Token": api_token, "Accept": "application/json"},
            json={
                "From": f"FastComps <{os.getenv('FROM_EMAIL', 'info@fastsme.com')}>",
                "To": email,
                "Subject": subject,
                "HtmlBody": body,
                "TextBody": f"{heading}\n\n{copy}\n\n{url}",
                "MessageStream": "outbound",
            },
            timeout=15,
        )
        response.raise_for_status()
        return True
    except httpx.HTTPError:
        log.exception("FastComps account email delivery failed")
        return False
