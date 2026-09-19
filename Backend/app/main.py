"""HTTP application: authenticated curation, account safety, and local playback."""
from __future__ import annotations

import copy
import csv
import hmac
import io
import json
import logging
import mimetypes
import secrets
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4, uuid5, NAMESPACE_URL

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException as StarletteHTTPException

from .config import Settings, settings as default_settings
from .schemas import (
    DEFAULT_PREFERENCES, AccountDelete, Feedback, Generate, Login, PasswordChange,
    PlaylistUpdate, ProfileUpdate, Refine, Register, VerifyOTP, CreatePlaylist, AddTrack,
)
from . import mail
from .security import DUMMY_PASSWORD_HASH, hash_password, new_token, token_hash, verify_password
from .storage import DuplicateUser, create_store

logger = logging.getLogger("curator")
API = "/api/v1"
AUTH_ERROR = "Credentials are incorrect."


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class BodyLimitMiddleware:
    """Bound JSON uploads, including requests without a Content-Length header."""
    def __init__(self, app, max_bytes: int = 32768):
        self.app, self.max_bytes = app, max_bytes

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] not in {"POST", "PUT", "PATCH", "DELETE"}:
            return await self.app(scope, receive, send)
        chunks, size = [], 0
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            chunk = message.get("body", b"")
            size += len(chunk)
            if size > self.max_bytes:
                response = JSONResponse({"detail": "Request is too large."}, status_code=413)
                return await response(scope, receive, send)
            chunks.append(chunk)
            if not message.get("more_body", False):
                break
        body, delivered = b"".join(chunks), False

        async def bounded_receive():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": body, "more_body": False}
            return await receive()

        await self.app(scope, bounded_receive, send)


def public_user(user: dict) -> dict:
    return {key: copy.deepcopy(user.get(key)) for key in (
        "id", "name", "email", "is_guest", "preferences", "onboarding_completed",
    )}


def public_playlist(playlist: dict) -> dict:
    result = {key: value for key, value in playlist.items() if key not in {"owner_id", "_revision", "request_fingerprint"}}
    result["revision"] = playlist.get("_revision", 0)
    return result


def create_app(settings: Settings | None = None) -> FastAPI:
    config = settings or default_settings

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        application.state.store = await run_in_threadpool(create_store, config)
        try:
            yield
        finally:
            await run_in_threadpool(application.state.store.close)

    app = FastAPI(
        title="AI Music Curator", version="1.0.0", lifespan=lifespan,
        description="Mood-based music curation, explainable recommendations, and local audio fallback.",
        docs_url="/docs" if config.environment != "production" else None,
        openapi_url="/openapi.json" if config.environment != "production" else None,
        redoc_url=None,
    )
    app.state.settings = config
    app.add_middleware(BodyLimitMiddleware)
    app.add_middleware(
        CORSMiddleware, allow_origins=config.allowed_origins, allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "X-CSRF-Token", "Range"],
        expose_headers=["Content-Disposition", "Content-Range", "Accept-Ranges", "Retry-After"],
    )

    @app.middleware("http")
    async def guard_browser_requests(request: Request, call_next):
        if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            origin = request.headers.get("origin")
            fetch_site = request.headers.get("sec-fetch-site")
            if (origin and origin.rstrip("/") not in config.allowed_origins) or (not origin and fetch_site == "cross-site"):
                response = JSONResponse({"detail": "This request origin is not allowed."}, status_code=403)
            else:
                response = await call_next(request)
        else:
            response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        if request.url.path.startswith(API):
            response.headers["Cache-Control"] = "no-store"
            response.headers["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none'"
        elif request.url.path not in {"/docs", "/openapi.json"}:
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
                "font-src 'self' https://fonts.gstatic.com; img-src 'self' data: https:; "
                "media-src 'self' blob: https:; connect-src 'self'; "
                "base-uri 'self'; form-action 'self'; frame-ancestors 'none'"
            )
        if config.cookie_secure:
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return response

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        # Pydantic includes submitted values by default. Never reflect passwords.
        issues = [{"field": ".".join(str(part) for part in error["loc"] if part != "body"),
                   "message": error["msg"]} for error in exc.errors()]
        return JSONResponse(status_code=422, content={"detail": "Check the submitted information.", "errors": issues})

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException):
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail}, headers=exc.headers)

    @app.exception_handler(Exception)
    async def unexpected_error(request: Request, exc: Exception):
        logger.exception("Request failed on %s", request.url.path)
        return JSONResponse(status_code=500, content={"detail": "Something went wrong. Please try again."})

    def rate(request: Request, bucket: str, limit: int, window: int, identity: str | None = None):
        # Do not trust X-Forwarded-For supplied by arbitrary clients.
        identity = identity or (request.client.host if request.client else "unknown")
        key = f"{bucket}:{token_hash(identity)}"
        permitted, retry_after = request.app.state.store.rate_limit(key, limit, window)
        if not permitted:
            raise HTTPException(429, "Too many requests. Please try again shortly.", headers={"Retry-After": str(retry_after)})

    def authenticated(request: Request) -> tuple[dict, dict]:
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
        store = request.app.state.store
        # Rotate the browser's previous session; signing in never upgrades a known token.
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
        session = {"id": token_hash(token), "user_id": user["id"], "csrf_token": csrf,
                   "otp_verified": not user["is_guest"],
                   "auth_version": user.get("auth_version", 0),
                   "created_at": utcnow(), "expires_at": time.time() + max_age}
        store.put("session", session["id"], session, owner=user["id"], expires_at=session["expires_at"])
        response.set_cookie(config.cookie_name, token, max_age=max_age, httponly=True,
                            secure=config.cookie_secure, samesite=config.cookie_samesite, path="/")
        return {"user": public_user(user), "csrf_token": csrf}

    def require_mail():
        if not mail.mail_ready(config):
            raise HTTPException(503, "Email sign-in is not configured. Set the mail settings and OTP_SECRET on the server.")

    def issue_otp(request: Request, response: Response, user: dict):
        require_mail()
        rate(request, "otp-send-cooldown", 1, config.otp_resend_seconds, user["id"])
        rate(request, "otp-send-account", 10, 3600, user["id"])
        token, code = new_token(), f"{secrets.randbelow(1000000):06d}"
        binding = token_hash(token)
        challenge = {"user_id": user["id"], "binding": binding, "code_hash": mail.code_hash(config, binding, code),
                     "auth_version": user.get("auth_version", 0), "attempts": 0, "consumed": False,
                     "expires_at": time.time() + config.otp_expiry_seconds}
        store = request.app.state.store
        store.put("otp", user["id"], challenge, owner=user["id"], expires_at=challenge["expires_at"])
        try:
            mail.send_otp(config, user["email"], code)
        except mail.MailUnavailable as exc:
            store.delete("otp", user["id"])
            raise HTTPException(503, str(exc)) from None
        response.set_cookie("curator_login", f"{user['id']}.{token}", max_age=config.otp_expiry_seconds,
                            httponly=True, secure=config.cookie_secure, samesite=config.cookie_samesite, path=API + "/auth")
        local, domain = user["email"].split("@", 1)
        return {"otp_required": True, "masked_email": local[:1] + "***@" + domain,
                "expires_in": config.otp_expiry_seconds, "resend_after": config.otp_resend_seconds}

    def pending_otp(request: Request):
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

    @app.get(f"{API}/health")
    def health(request: Request):
        from .music import list_local_tracks
        storage = request.app.state.store
        if not storage.ping():
            raise HTTPException(503, "Storage is unavailable.")
        has_spotify = bool(config.spotify_client_id and config.spotify_client_secret)
        return {"status": "ok", "storage": storage.kind, "ai_configured": bool(config.groq_api_key),
                "mail_configured": mail.mail_ready(config),
                "spotify_configured": has_spotify,
                "music_api_configured": has_spotify or bool(config.lastfm_api_key),
                "local_track_count": len(list_local_tracks())}

    @app.post(f"{API}/auth/register", status_code=201)
    def register(body: Register, request: Request, response: Response):
        rate(request, "register", 10, 3600)
        require_mail()
        existing = request.app.state.store.user_by_email(body.email)
        if existing:
            if not existing.get("email_verified") and verify_password(body.password, existing["password_hash"]):
                return issue_otp(request, response, existing)
            raise HTTPException(400, "Unable to create an account with those details.")
        user = {"id": str(uuid4()), "name": body.name, "email": body.email, "is_guest": False,
                "auth_version": 0, "email_verified": False,
                "password_hash": hash_password(body.password), "preferences": copy.deepcopy(DEFAULT_PREFERENCES),
                "onboarding_completed": False, "created_at": utcnow()}
        try:
            request.app.state.store.create_user(user)
        except DuplicateUser:
            raise HTTPException(400, "Unable to create an account with those details.") from None
        return issue_otp(request, response, user)

    @app.post(f"{API}/auth/login")
    def login(body: Login, request: Request, response: Response):
        rate(request, "login-ip", 30, 900)
        rate(request, "login-account", 10, 900, body.email)
        user = request.app.state.store.user_by_email(body.email)
        valid = verify_password(body.password, user["password_hash"] if user else DUMMY_PASSWORD_HASH)
        if not user or not valid:
            raise HTTPException(401, AUTH_ERROR)
        return issue_otp(request, response, user)

    @app.post(f"{API}/auth/verify-otp")
    def verify_otp(body: VerifyOTP, request: Request, response: Response):
        rate(request, "otp-verify-ip", 50, 900)
        user_id, binding, _ = pending_otp(request)
        store = request.app.state.store
        challenge = store.consume_otp(user_id, binding, mail.code_hash(config, binding, body.code))
        if not challenge:
            raise HTTPException(400, "Code is invalid or expired. Request a new code if needed.")
        user = store.get("user", user_id)
        if not user or user.get("auth_version", 0) != challenge["auth_version"]:
            raise HTTPException(400, "Code is invalid or expired. Start sign-in again.")
        store.update_profile(user_id, {"email_verified": True})
        response.delete_cookie("curator_login", path=API + "/auth", secure=config.cookie_secure,
                               httponly=True, samesite=config.cookie_samesite)
        return issue_session(request, response, user)

    @app.post(f"{API}/auth/resend-otp")
    def resend_otp(request: Request, response: Response):
        rate(request, "otp-resend-ip", 20, 3600)
        user_id, _, challenge = pending_otp(request)
        user = request.app.state.store.get("user", user_id)
        if not user or user.get("auth_version", 0) != challenge["auth_version"]:
            raise HTTPException(400, "Start sign-in again to request a new code.")
        return issue_otp(request, response, user)

    @app.post(f"{API}/auth/guest", status_code=201)
    def guest(request: Request, response: Response):
        rate(request, "guest", 60, 3600)
        request.app.state.store.cleanup()
        user = {"id": str(uuid4()), "name": "Guest listener", "email": None, "is_guest": True,
                "auth_version": 0,
                "preferences": copy.deepcopy(DEFAULT_PREFERENCES), "onboarding_completed": True,
                "created_at": utcnow(), "expires_at": time.time() + config.guest_session_hours * 3600}
        request.app.state.store.create_user(user)
        return issue_session(request, response, user)

    @app.get(f"{API}/auth/me")
    @app.get(f"{API}/profile")
    def me(auth: tuple = Depends(authenticated)):
        user, session = auth
        return {"user": public_user(user), "csrf_token": session["csrf_token"]}

    @app.post(f"{API}/auth/logout")
    def logout(request: Request, response: Response, auth: tuple = Depends(authenticated)):
        user, session = auth
        if user["is_guest"]:
            request.app.state.store.delete_user(user["id"])
        else:
            request.app.state.store.delete("session", session["id"])
        response.delete_cookie(config.cookie_name, path="/", secure=config.cookie_secure,
                               httponly=True, samesite=config.cookie_samesite)
        return {"message": "You have been signed out."}

    @app.put(f"{API}/profile")
    def update_profile(body: ProfileUpdate, request: Request, auth: tuple = Depends(authenticated)):
        user, session = auth
        user = request.app.state.store.update_profile(user["id"], body.model_dump(exclude_none=True))
        if not user:
            raise HTTPException(401, "Please sign in to continue.")
        return {"user": public_user(user), "csrf_token": session["csrf_token"]}

    @app.post(f"{API}/auth/change-password")
    def change_password(body: PasswordChange, request: Request, response: Response, auth: tuple = Depends(authenticated)):
        user, _ = auth
        if user["is_guest"]:
            raise HTTPException(400, "Create an account to set a password.")
        rate(request, "password-change", 10, 900, user["id"])
        if not verify_password(body.current_password, user["password_hash"]):
            raise HTTPException(401, AUTH_ERROR)
        user = request.app.state.store.rotate_password(user["id"], hash_password(body.new_password), user.get("auth_version", 0))
        if not user:
            raise HTTPException(409, "Your credentials changed. Please sign in again.")
        return issue_session(request, response, user)

    @app.delete(f"{API}/account")
    def delete_account(body: AccountDelete, request: Request, response: Response, auth: tuple = Depends(authenticated)):
        user, _ = auth
        rate(request, "account-delete", 10, 900, user["id"])
        if not user["is_guest"] and not verify_password(body.password, user["password_hash"]):
            raise HTTPException(401, AUTH_ERROR)
        request.app.state.store.delete_user(user["id"])
        response.delete_cookie(config.cookie_name, path="/", secure=config.cookie_secure,
                               httponly=True, samesite=config.cookie_samesite)
        return {"message": "Your account and playlists have been deleted."}

    @app.get(f"{API}/playlists")
    def playlists(request: Request, auth: tuple = Depends(authenticated)):
        user, _ = auth
        items = request.app.state.store.list_owned("playlist", user["id"])
        return {"playlists": [public_playlist(item) for item in sorted(items, key=lambda item: item["updated_at"], reverse=True) if item.get("kind") != "queue"]}

    @app.post(f"{API}/playlists", status_code=201)
    def create_playlist(body: CreatePlaylist, request: Request, auth: tuple = Depends(authenticated)):
        now = utcnow()
        playlist = {"id": str(uuid4()), "owner_id": auth[0]["id"], "session_id": str(uuid4()),
                    "kind": "collection", "name": body.name, "description": body.description.strip(),
                    "profile": None, "tracks": [], "messages": [], "version": 1, "saved": True,
                    "created_at": now, "updated_at": now, "source": "collection", "parser": "manual",
                    "warnings": [], "feedback": {}}
        return save_playlist(request, playlist)

    def find_track(request: Request, body: AddTrack, user: dict):
        if body.source_id:
            source = owned_playlist(request, body.source_id, user)
            track = next((track for track in source["tracks"] if track["id"] == body.track_id), None)
        else:
            saved = request.app.state.store.get("saved_song", token_hash(user["id"] + ":" + body.track_id))
            track = saved.get("track") if saved else None
            if not track:
                from .music import list_local_tracks
                track = next((track for track in list_local_tracks() if track["id"] == body.track_id), None)
        if not track:
            raise HTTPException(404, "Song is no longer available in this source. Refresh and try again.")
        return copy.deepcopy(track)

    @app.post(f"{API}/playlists/{{playlist_id}}/tracks")
    def add_track(playlist_id: str, body: AddTrack, request: Request, auth: tuple = Depends(authenticated)):
        playlist = owned_playlist(request, playlist_id, auth[0])
        if playlist.get("kind") == "queue":
            raise HTTPException(400, "Choose one of your playlists to store this song.")
        check_revision(playlist, body.revision)
        if any(track["id"] == body.track_id for track in playlist["tracks"]):
            return public_playlist(playlist)
        if len(playlist["tracks"]) >= 500:
            raise HTTPException(400, "This playlist has reached its 500-song limit.")
        track = find_track(request, body, auth[0])
        track.pop("feedback", None)
        playlist["tracks"].append(track)
        playlist.setdefault("feedback", {}).pop(body.track_id, None)
        return save_playlist(request, playlist)

    @app.get(f"{API}/saved-songs")
    def saved_songs(request: Request, auth: tuple = Depends(authenticated)):
        return {"tracks": [item["track"] for item in request.app.state.store.list_owned("saved_song", auth[0]["id"])]}

    @app.post(f"{API}/saved-songs", status_code=201)
    def save_song(body: AddTrack, request: Request, auth: tuple = Depends(authenticated)):
        track = find_track(request, body, auth[0])
        track.pop("feedback", None)
        key = token_hash(auth[0]["id"] + ":" + body.track_id)
        request.app.state.store.put("saved_song", key, {"track": track}, owner=auth[0]["id"])
        return {"track": track}

    @app.delete(f"{API}/saved-songs/{{track_id}}")
    def unsave_song(track_id: str, request: Request, auth: tuple = Depends(authenticated)):
        request.app.state.store.delete("saved_song", token_hash(auth[0]["id"] + ":" + track_id))
        return {"message": "Song removed from saved songs."}

    @app.get(f"{API}/queue")
    def get_queue(request: Request, auth: tuple = Depends(authenticated)):
        key = str(uuid5(NAMESPACE_URL, auth[0]["id"] + ":mood-queue"))
        item = request.app.state.store.get("playlist", key)
        return {"queue": public_playlist(item) if item else None}

    @app.post(f"{API}/playlists/generate", status_code=201)
    @app.post(f"{API}/queue/generate", status_code=201)
    async def generate(body: Generate, request: Request, auth: tuple = Depends(authenticated)):
        from .engine import curate
        user, _ = auth
        playlist_id = str(uuid5(NAMESPACE_URL, user["id"] + ":mood-queue"))
        fingerprint = token_hash(json.dumps([body.description, body.playlist_size], ensure_ascii=False))
        existing = request.app.state.store.get("playlist", playlist_id)
        if existing and body.request_id and existing.get("queue_request_id") == str(body.request_id):
            if existing.get("request_fingerprint") != fingerprint:
                raise HTTPException(409, "This creation request was already used for a different playlist.")
            return public_playlist(existing)
        rate(request, "curation", 20, 60, user["id"])
        preferences = copy.deepcopy(user["preferences"])
        preferences["_selection_seed"] = str(body.request_id or uuid4())
        result = await curate(body.description, playlist_size=body.playlist_size, preferences=preferences)
        now = utcnow()
        count = len(result["tracks"])
        playlist = {"id": playlist_id, "owner_id": user["id"], "session_id": str(uuid4()),
                    "kind": "queue", "queue_request_id": str(body.request_id or uuid4()), "_revision": existing.get("_revision", 0) if existing else 0,
                    "request_fingerprint": fingerprint,
                    "name": result["name"], "description": body.description, "profile": result["profile"],
                    "tracks": result["tracks"], "messages": [
                        {"role": "user", "content": body.description, "created_at": now},
                        {"role": "assistant", "content": f"I curated {count} tracks for your moment. Explore why each song fits, or tell me what to change.", "created_at": now},
                    ], "version": 1, "saved": False, "created_at": now, "updated_at": now,
                    "source": result["source"], "parser": result["parser"], "warnings": result.get("warnings", []),
                    "playlist_size": min(10, body.playlist_size), "feedback": {}}
        try:
            return save_playlist(request, playlist)
        except HTTPException as exc:
            existing = request.app.state.store.get("playlist", playlist_id)
            if exc.status_code == 409 and existing and body.request_id and existing.get("queue_request_id") == str(body.request_id):
                return public_playlist(existing)
            raise

    @app.get(f"{API}/playlists/{{playlist_id}}")
    def get_playlist(playlist_id: str, request: Request, auth: tuple = Depends(authenticated)):
        return public_playlist(owned_playlist(request, playlist_id, auth[0]))

    @app.patch(f"{API}/playlists/{{playlist_id}}")
    def update_playlist(playlist_id: str, body: PlaylistUpdate, request: Request, auth: tuple = Depends(authenticated)):
        playlist = owned_playlist(request, playlist_id, auth[0])
        if playlist.get("kind") == "queue" and body.saved:
            raise HTTPException(400, "Create a named playlist and add the songs you want to keep.")
        check_revision(playlist, body.revision)
        playlist.update(body.model_dump(exclude_none=True, exclude={"revision"}))
        return save_playlist(request, playlist)

    @app.delete(f"{API}/playlists/{{playlist_id}}")
    def delete_playlist(playlist_id: str, request: Request, auth: tuple = Depends(authenticated)):
        playlist = owned_playlist(request, playlist_id, auth[0])
        if playlist.get("kind") == "queue":
            playlist.update(tracks=[], messages=[], feedback={}, warnings=[], description="", name="Your mood queue")
            save_playlist(request, playlist)
            return {"message": "Queue cleared."}
        request.app.state.store.put("deleted_playlist", playlist_id, {"id": playlist_id}, owner=auth[0]["id"])
        request.app.state.store.delete("playlist", playlist_id)
        return {"message": "Playlist deleted."}

    @app.post(f"{API}/playlists/{{playlist_id}}/refine")
    async def refine(playlist_id: str, body: Refine, request: Request, auth: tuple = Depends(authenticated)):
        from .engine import curate
        user, _ = auth
        playlist = owned_playlist(request, playlist_id, user)
        if playlist.get("kind") == "collection":
            raise HTTPException(400, "Refine your mood queue, then add the songs you want to this playlist.")
        check_revision(playlist, body.revision)
        rate(request, "curation", 20, 60, user["id"])
        if len(playlist["messages"]) >= 200:
            raise HTTPException(400, "This conversation has reached its limit. Start a new playlist to continue.")
        preferences = copy.deepcopy(user["preferences"])
        preferences["_excluded_track_ids"] = [track_id for track_id, feedback in playlist.get("feedback", {}).items() if feedback in {"dislike", "remove"}]
        preferences["_selection_seed"] = playlist_id + ":" + str(playlist["version"] + 1)
        if any(word in body.message.casefold() for word in ("refresh", "different songs", "new songs", "regenerate")):
            preferences["_previous_track_ids"] = [track["id"] for track in playlist["tracks"]]
        result = await curate(body.message, playlist_size=min(10, playlist.get("playlist_size", 10)),
                              previous_profile=playlist["profile"], preferences=preferences)
        playlist.update({key: result[key] for key in ("profile", "tracks", "source", "parser", "warnings")})
        for track in playlist["tracks"]:
            if track["id"] in playlist.get("feedback", {}):
                track["feedback"] = playlist["feedback"][track["id"]]
        playlist["version"] += 1
        now = utcnow()
        playlist["messages"].extend([
            {"role": "user", "content": body.message, "created_at": now},
            {"role": "assistant", "content": f"Updated your playlist to version {playlist['version']} with {len(playlist['tracks'])} tracks, keeping your previous preferences in mind.", "created_at": now},
        ])
        return save_playlist(request, playlist)

    @app.get(f"{API}/sessions/{{session_id}}/history")
    def history(session_id: str, request: Request, auth: tuple = Depends(authenticated)):
        items = request.app.state.store.list_owned("playlist", auth[0]["id"])
        playlist = next((item for item in items if item["session_id"] == session_id), None)
        if not playlist:
            raise HTTPException(404, "Conversation not found.")
        return {"session_id": session_id, "playlist_id": playlist["id"], "messages": playlist["messages"], "profile": playlist["profile"]}

    @app.post(f"{API}/playlists/{{playlist_id}}/feedback")
    def feedback(playlist_id: str, body: Feedback, request: Request, auth: tuple = Depends(authenticated)):
        playlist = owned_playlist(request, playlist_id, auth[0])
        check_revision(playlist, body.revision)
        track = next((track for track in playlist["tracks"] if track["id"] == body.track_id), None)
        if not track:
            raise HTTPException(404, "Track not found in this playlist.")
        playlist.setdefault("feedback", {})[body.track_id] = body.feedback
        if body.feedback in {"remove", "dislike"}:
            playlist["tracks"] = [track for track in playlist["tracks"] if track["id"] != body.track_id]
        else:
            track["feedback"] = body.feedback
        return save_playlist(request, playlist)

    @app.get(f"{API}/playlists/{{playlist_id}}/export")
    def export_playlist(playlist_id: str, request: Request, format: Literal["json", "csv"] = "json", auth: tuple = Depends(authenticated)):
        playlist = public_playlist(owned_playlist(request, playlist_id, auth[0]))
        headers = {"Content-Disposition": f'attachment; filename="playlist-{playlist_id}.{format}"'}
        if format == "json":
            return Response(json.dumps(playlist, ensure_ascii=False, indent=2), media_type="application/json", headers=headers)
        output = io.StringIO(newline="")
        writer = csv.writer(output)
        writer.writerow(["Position", "Title", "Artist", "Album", "Genres", "Match score", "Why this song", "Source", "URL"])

        def safe_cell(value) -> str:
            value = str(value or "")
            if value.lstrip().startswith(("=", "+", "-", "@")) or value.startswith(("\t", "\r", "\n")):
                return "'" + value
            return value

        for position, track in enumerate(playlist["tracks"], 1):
            writer.writerow([safe_cell(value) for value in (
                position, track.get("title"), track.get("artist"), track.get("album"),
                ", ".join(track.get("genres", [])), track.get("total_score", track.get("score", "")),
                track.get("explanation"), track.get("source"), track.get("external_url"),
            )])
        return Response("\ufeff" + output.getvalue(), media_type="text/csv; charset=utf-8", headers=headers)

    @app.get(f"{API}/library")
    def library(auth: tuple = Depends(authenticated)):
        from .music import list_local_tracks
        return {"tracks": list_local_tracks()}

    @app.post(f"{API}/library/rescan")
    def rescan_library(request: Request, auth: tuple = Depends(authenticated)):
        from . import music
        rate(request, "rescan", 10, 60, auth[0]["id"])
        if hasattr(music, "rescan_library"):
            return {"tracks": music.rescan_library()}
        if hasattr(music, "invalidate_cache"):
            music.invalidate_cache()
        return {"tracks": music.list_local_tracks()}

    @app.get(f"{API}/media/{{track_id}}")
    def local_media(track_id: str, auth: tuple = Depends(authenticated)):
        from .music import resolve_media
        if len(track_id) > 200:
            raise HTTPException(404, "Audio file not found.")
        path = resolve_media(track_id)
        if path is None or not path.is_file():
            raise HTTPException(404, "Audio file not found. Rescan your local library.")
        media_type = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
        return FileResponse(path, media_type=media_type, filename=path.name, content_disposition_type="inline")

    @app.get("/{path:path}", include_in_schema=False)
    def frontend(path: str):
        """Serve the built SPA from the same origin as its protected API."""
        if path == "api" or path.startswith("api/"):
            raise HTTPException(404, "Endpoint not found.")
        dist = (config.project_root / "Frontend" / "dist").resolve()
        candidate = (dist / path).resolve()
        if not candidate.is_relative_to(dist):
            raise HTTPException(404, "File not found.")
        if candidate.is_file():
            response = FileResponse(candidate)
            if candidate.name == "favicon.svg":
                response.headers["Cache-Control"] = "no-cache"
            return response
        index = dist / "index.html"
        if not index.is_file():
            raise HTTPException(404, "Frontend build not found. Start the Vite development server or build Frontend first.")
        # Missing asset requests should fail, rather than return HTML as JavaScript.
        if path.startswith("assets/") or candidate.suffix:
            raise HTTPException(404, "File not found.")
        return FileResponse(index)

    return app


app = create_app()
