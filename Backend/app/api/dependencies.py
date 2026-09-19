"""Shared API dependencies: authentication, CSRF, rate limiting, and helpers."""

from __future__ import annotations

import copy
import hmac
import secrets
import time
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import HTTPException, Request, Response

from ..config.settings import Settings
from ..core.security import DUMMY_PASSWORD_HASH, hash_password, new_token, token_hash, verify_password
from .. import mail

API = "/api/v1"
AUTH_ERROR = "Credentials are incorrect."


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def public_user(user: dict) -> dict:
    return {key: copy.deepcopy(user.get(key)) for key in (
        "id", "name", "email", "is_guest", "preferences", "onboarding_completed",
    )}


def public_playlist(playlist: dict) -> dict:
    result = {key: value for key, value in playlist.items() if key not in {"owner_id", "_revision", "request_fingerprint"}}
    result["revision"] = playlist.get("_revision", 0)
    return result


def rate(request: Request, bucket: str, limit: int, window: int, identity: str | None = None):
    """Rate-limit a request. Raises HTTPException(429) if limit exceeded."""
    identity = identity or (request.client.host if request.client else "unknown")
    key = f"{bucket}:{token_hash(identity)}"
    permitted, retry_after = request.app.state.store.rate_limit(key, limit, window)
    if not permitted:
        raise HTTPException(429, "Too many requests. Please try again shortly.", headers={"Retry-After": str(retry_after)})


def authenticated(request: Request) -> tuple[dict, dict]:
    """Validate the session cookie and CSRF token. Returns (user, session)."""
    config: Settings = request.app.state.settings
    token = request.cookies.get(config.cookie_name)
    if not token or len(token) > 200:
        raise HTTPException(401, "Please sign in to continue.")
    session = request.app.state.store.get("session", token_hash(token))
    if not session:
        raise HTTPException(401, "Your session has expired. Please sign in again.")
    user = request.app.state.store.get("user", session["user_id"])
    if not user:
        raise HTTPException(401, "Please sign in to continue.")
    if session.get("auth_version", 0) != user.get("auth_version", 0):
        raise HTTPException(401, "Your session has expired. Please sign in again.")
    if not user["is_guest"] and not session.get("otp_verified"):
        raise HTTPException(401, "Please sign in again and verify your email code.")
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        submitted = request.headers.get("x-csrf-token", "")
        if not hmac.compare_digest(submitted.encode("utf-8"), session["csrf_token"].encode("utf-8")):
            raise HTTPException(403, "Your security token is missing or expired. Refresh and try again.")
        rate(request, "mutation", 120, 60, user["id"])
    return user, session


def issue_session(request: Request, response: Response, user: dict) -> dict:
    """Create a new session, rotate old tokens, and set the cookie."""
    config: Settings = request.app.state.settings
    store = request.app.state.store
    old_token = request.cookies.get(config.cookie_name)
    if old_token and len(old_token) <= 200:
        old_session = store.get("session", token_hash(old_token))
        if old_session:
            old_user = store.get("user", old_session["user_id"])
            if old_user and old_user["is_guest"] and old_user["id"] != user["id"]:
                store.delete_user(old_user["id"])
        store.delete("session", token_hash(old_token))
    token, csrf = new_token(), new_token()
    max_age = (config.guest_session_hours if user["is_guest"] else config.session_hours) * 3600
    session = {
        "id": token_hash(token), "user_id": user["id"], "csrf_token": csrf,
        "otp_verified": not user["is_guest"],
        "auth_version": user.get("auth_version", 0),
        "created_at": utcnow(), "expires_at": time.time() + max_age,
    }
    store.put("session", session["id"], session, owner=user["id"], expires_at=session["expires_at"])
    response.set_cookie(config.cookie_name, token, max_age=max_age, httponly=True,
                        secure=config.cookie_secure, samesite=config.cookie_samesite, path="/")
    return {"user": public_user(user), "csrf_token": csrf}


def require_mail(request: Request):
    config: Settings = request.app.state.settings
    if not mail.mail_ready(config):
        raise HTTPException(503, "Email sign-in is not configured. Set the mail settings and OTP_SECRET on the server.")


def issue_otp(request: Request, response: Response, user: dict):
    """Generate, store, and send a one-time password via email."""
    config: Settings = request.app.state.settings
    require_mail(request)
    rate(request, "otp-send-cooldown", 1, config.otp_resend_seconds, user["id"])
    rate(request, "otp-send-account", 10, 3600, user["id"])
    token, code = new_token(), f"{secrets.randbelow(1000000):06d}"
    binding = token_hash(token)
    challenge = {
        "user_id": user["id"], "binding": binding,
        "code_hash": mail.code_hash(config, binding, code),
        "auth_version": user.get("auth_version", 0),
        "attempts": 0, "consumed": False,
        "expires_at": time.time() + config.otp_expiry_seconds,
    }
    store = request.app.state.store
    store.put("otp", user["id"], challenge, owner=user["id"], expires_at=challenge["expires_at"])
    try:
        mail.send_otp(config, user["email"], code)
    except mail.MailUnavailable as exc:
        store.delete("otp", user["id"])
        raise HTTPException(503, str(exc)) from None
    response.set_cookie(
        "curator_login", f"{user['id']}.{token}", max_age=config.otp_expiry_seconds,
        httponly=True, secure=config.cookie_secure, samesite=config.cookie_samesite, path=API + "/auth",
    )
    local, domain = user["email"].split("@", 1)
    return {
        "otp_required": True, "masked_email": local[:1] + "***@" + domain,
        "expires_in": config.otp_expiry_seconds, "resend_after": config.otp_resend_seconds,
    }


def pending_otp(request: Request):
    """Retrieve and validate the in-progress OTP challenge."""
    token = request.cookies.get("curator_login", "")
    if len(token) > 200 or "." not in token:
        raise HTTPException(400, "Code is invalid or expired. Start sign-in again.")
    user_id, secret = token.split(".", 1)
    binding = token_hash(secret)
    challenge = request.app.state.store.get("otp", user_id)
    if not challenge or challenge.get("consumed") or not hmac.compare_digest(challenge["binding"], binding):
        raise HTTPException(400, "Code is invalid or expired. Start sign-in again.")
    return user_id, binding, challenge


def check_revision(playlist: dict, revision: int | None):
    if revision is not None and revision != playlist.get("_revision", 0):
        raise HTTPException(409, "This playlist changed in another request. Review the latest version and try again.")


def owned_playlist(request: Request, playlist_id: str, user: dict) -> dict:
    if len(playlist_id) > 100:
        raise HTTPException(404, "Playlist not found.")
    playlist = request.app.state.store.get("playlist", playlist_id)
    if not playlist or playlist.get("owner_id") != user["id"]:
        raise HTTPException(404, "Playlist not found.")
    return playlist


def save_playlist(request: Request, playlist: dict) -> dict:
    playlist["updated_at"] = utcnow()
    previous_revision = playlist.get("_revision", 0)
    playlist["_revision"] = previous_revision + 1
    if not request.app.state.store.save_playlist(playlist, previous_revision):
        raise HTTPException(409, "This playlist changed while your request was running. Refresh and try again.")
    return public_playlist(playlist)
