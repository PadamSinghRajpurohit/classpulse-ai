"""Authentication helpers for local SQLite or optional Supabase Auth.

Supabase is used only when SUPABASE_URL and SUPABASE_ANON_KEY are configured.
Never use a Supabase service-role key here. The access token returned for a
Supabase login is private session state; do not render, log, or persist it.
"""

from __future__ import annotations

import hashlib
import hmac
import importlib.util
import os
import re
import secrets
import sqlite3
import threading
import time
from datetime import datetime, timezone
from typing import Any

import classpulse_storage as storage

_PBKDF2_ITERATIONS = 310_000
_EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
_RATE_LOCK = threading.Lock()
_FAILURES: dict[str, list[float]] = {}
_MAX_FAILURES = 8
_WINDOW_SECONDS = 300

# Used to make unknown-user local logins pay approximately the same hash cost.
_DUMMY_HASH = hashlib.pbkdf2_hmac(
    "sha256", b"not-a-real-password", b"classpulse-dummy-salt", _PBKDF2_ITERATIONS
)


class UserIdentity(dict):
    """Dict-like safe identity with a token kept outside serialized fields."""

    __slots__ = ("__token",)

    def __init__(self, values: dict[str, Any], access_token: str | None = None):
        super().__init__(values)
        self.__token = access_token

    @property
    def access_token(self) -> str | None:
        """User JWT for authenticated RLS requests; never part of dict/repr/JSON."""
        return self.__token


def _supabase_configured() -> bool:
    return bool(
        os.getenv("AUTH_BACKEND", "local").strip().casefold() == "supabase"
        and os.getenv("SUPABASE_URL", "").strip()
        and os.getenv("SUPABASE_ANON_KEY", "").strip()
        and importlib.util.find_spec("supabase")
    )


def auth_mode() -> str:
    """Return ``supabase`` when configured, otherwise ``local``."""
    return "supabase" if _supabase_configured() else "local"


def _supabase_client():
    if not _supabase_configured():
        return None
    try:
        from supabase import create_client  # type: ignore[import-not-found]
    except ImportError as exc:
        raise RuntimeError("Supabase is configured but the optional supabase package is not installed") from exc
    return create_client(os.environ["SUPABASE_URL"].strip(), os.environ["SUPABASE_ANON_KEY"].strip())


def _normalize_email(email: str) -> str:
    normalized = (email or "").strip().casefold()
    if len(normalized) > 254 or not _EMAIL_RE.fullmatch(normalized):
        raise ValueError("Enter a valid email address")
    return normalized


def _validate_password(password: str) -> None:
    if not isinstance(password, str) or len(password) < 10:
        raise ValueError("Password must be at least 10 characters")
    if len(password) > 1024:
        raise ValueError("Password is too long")


def _hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${_PBKDF2_ITERATIONS}${salt.hex()}${digest.hex()}"


def _verify_password(password: str, encoded: str | None) -> bool:
    try:
        algorithm, iterations, salt_hex, expected_hex = (encoded or "").split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        rounds = int(iterations)
        if rounds < 100_000 or rounds > 2_000_000:
            return False
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(expected_hex)
    except (ValueError, TypeError):
        hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), b"classpulse-dummy-salt", _PBKDF2_ITERATIONS)
        return False
    actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, rounds)
    return hmac.compare_digest(actual, expected)


def _rate_limited(email: str) -> bool:
    now = time.monotonic()
    with _RATE_LOCK:
        recent = [stamp for stamp in _FAILURES.get(email, []) if now - stamp < _WINDOW_SECONDS]
        _FAILURES[email] = recent
        return len(recent) >= _MAX_FAILURES


def _record_failure(email: str) -> None:
    now = time.monotonic()
    with _RATE_LOCK:
        recent = [stamp for stamp in _FAILURES.get(email, []) if now - stamp < _WINDOW_SECONDS]
        recent.append(now)
        _FAILURES[email] = recent


def _clear_failures(email: str) -> None:
    with _RATE_LOCK:
        _FAILURES.pop(email, None)


def _supabase_user(user: Any, session: Any = None) -> dict[str, Any] | None:
    if user is None:
        return None
    user_id = getattr(user, "id", None)
    email = getattr(user, "email", None)
    if not user_id or not email:
        return None
    metadata = getattr(user, "user_metadata", None) or {}
    session_token = getattr(session, "access_token", None) if session is not None else None
    identity: dict[str, Any] = {
        "id": str(user_id),
        "email": str(email),
        "name": str(metadata.get("full_name") or metadata.get("name") or email.split("@", 1)[0]),
        "backend": "supabase",
    }
    return UserIdentity(identity, str(session_token) if session_token else None)


def register(email: str, password: str, name: str) -> dict[str, Any] | None:
    """Create an account and return a safe identity, or None on conflict/failure.

    ValueError is raised for malformed input. In Supabase mode, ``pending_verification``
    can be true when the project requires email confirmation before login.
    """
    normalized = _normalize_email(email)
    _validate_password(password)
    display_name = (name or "").strip()
    if not display_name or len(display_name) > 100:
        raise ValueError("Name is required and must be 100 characters or fewer")

    if _supabase_configured():
        try:
            client = _supabase_client()
            result = client.auth.sign_up({
                "email": normalized,
                "password": password,
                "options": {"data": {"full_name": display_name}},
            })
            user = getattr(result, "user", None)
            session = getattr(result, "session", None)
            identity = _supabase_user(user, session)
            if identity:
                if session is None:
                    identity["pending_verification"] = True
                return identity
            return None
        except Exception:
            # Keep provider errors out of the UI; callers should display a generic message.
            return None

    storage.init_db()
    try:
        with storage._connect() as db:
            cursor = db.execute(
                "INSERT INTO users(email, display_name, password_hash, created_at) VALUES (?, ?, ?, ?)",
                (
                    normalized,
                    display_name,
                    _hash_password(password),
                    datetime.now(timezone.utc).isoformat(timespec="seconds"),
                ),
            )
        return {"id": int(cursor.lastrowid), "email": normalized, "name": display_name, "backend": "local"}
    except sqlite3.IntegrityError:
        return None


def authenticate(email: str, password: str) -> dict[str, Any] | None:
    """Authenticate and return an identity dict, or None for any login failure."""
    try:
        normalized = _normalize_email(email)
    except ValueError:
        # Perform comparable work even for malformed identifiers.
        hashlib.pbkdf2_hmac("sha256", str(password).encode("utf-8"), b"classpulse-dummy-salt", _PBKDF2_ITERATIONS)
        return None
    if not isinstance(password, str) or len(password) > 1024 or _rate_limited(normalized):
        hashlib.pbkdf2_hmac("sha256", b"invalid-password", b"classpulse-dummy-salt", _PBKDF2_ITERATIONS)
        return None

    if _supabase_configured():
        try:
            client = _supabase_client()
            result = client.auth.sign_in_with_password({"email": normalized, "password": password})
            identity = _supabase_user(getattr(result, "user", None), getattr(result, "session", None))
            if identity:
                _clear_failures(normalized)
                return identity
        except Exception:
            pass
        _record_failure(normalized)
        return None

    storage.init_db()
    with storage._connect() as db:
        row = db.execute(
            "SELECT id, email, display_name, password_hash FROM users WHERE email = ?",
            (normalized,),
        ).fetchone()
    if row is None:
        hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), b"classpulse-dummy-salt", _PBKDF2_ITERATIONS)
        _record_failure(normalized)
        return None
    if not _verify_password(password, row["password_hash"]):
        _record_failure(normalized)
        return None
    _clear_failures(normalized)
    return {"id": int(row["id"]), "email": row["email"], "name": row["display_name"], "backend": "local"}
