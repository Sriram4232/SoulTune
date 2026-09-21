"""Configuration module: settings, environment resolution, and path setup."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

BACKEND_ROOT = Path(__file__).resolve().parents[2]
PROJECT_ROOT = BACKEND_ROOT.parent
load_dotenv(BACKEND_ROOT / ".env", override=False)


def _database_path() -> Path:
    path = Path(os.getenv("DATABASE_PATH", "data/curator.sqlite3"))
    return path if path.is_absolute() else BACKEND_ROOT / path


def _cookie_secure_default() -> bool:
    val = os.getenv("COOKIE_SECURE")
    if val is not None:
        return val.lower() == "true"
    return os.getenv("ENVIRONMENT") == "production" or bool(os.getenv("RENDER"))


def _cookie_samesite_default() -> str:
    val = os.getenv("COOKIE_SAMESITE")
    if val is not None:
        return val.lower()
    if os.getenv("ENVIRONMENT") == "production" or bool(os.getenv("RENDER")):
        return "none"
    return "lax"


@dataclass
class Settings:
    database_path: Path = field(default_factory=_database_path)
    mongodb_uri: str = field(default_factory=lambda: os.getenv("MONGODB_URI", ""), repr=False)
    mongodb_database: str = field(default_factory=lambda: os.getenv("MONGODB_DATABASE", "ai_music_curator"))
    allowed_origins: list[str] = field(default_factory=lambda: [
        origin.strip().rstrip("/") for origin in os.getenv(
            "ALLOWED_ORIGINS",
            "http://localhost:5173,http://127.0.0.1:5173,http://localhost:4173,http://127.0.0.1:4173,http://localhost:8000,http://127.0.0.1:8000,https://soul-tune-kappa.vercel.app,https://soultune-zctz.onrender.com",
        ).split(",") if origin.strip()
    ])
    cookie_secure: bool = field(default_factory=_cookie_secure_default)
    cookie_samesite: str = field(default_factory=_cookie_samesite_default)
    session_hours: int = field(default_factory=lambda: int(os.getenv("SESSION_HOURS", "168")))
    guest_session_hours: int = field(default_factory=lambda: int(os.getenv("GUEST_SESSION_HOURS", "24")))
    environment: str = field(default_factory=lambda: os.getenv("ENVIRONMENT", "development"))
    cookie_name: str = "curator_session"
    mail_provider: str = field(default_factory=lambda: os.getenv("MAIL_PROVIDER", "smtp").lower())
    mail_from: str = field(default_factory=lambda: os.getenv("MAIL_FROM", ""))
    smtp_host: str = field(default_factory=lambda: os.getenv("SMTP_HOST", ""))
    smtp_port: int = field(default_factory=lambda: int(os.getenv("SMTP_PORT", "587")))
    smtp_username: str = field(default_factory=lambda: os.getenv("SMTP_USERNAME", ""))
    smtp_password: str = field(default_factory=lambda: os.getenv("SMTP_PASSWORD", ""), repr=False)
    smtp_security: str = field(default_factory=lambda: os.getenv("SMTP_SECURITY", "starttls").lower())
    resend_api_key: str = field(default_factory=lambda: os.getenv("RESEND_API_KEY", ""), repr=False)
    otp_secret: str = field(default_factory=lambda: os.getenv("OTP_SECRET", ""), repr=False)
    otp_expiry_seconds: int = 600
    otp_resend_seconds: int = 60
    groq_api_key: str = field(default_factory=lambda: os.getenv("GROQ_API_KEY", ""), repr=False)
    groq_model: str = field(default_factory=lambda: os.getenv("GROQ_MODEL", "openai/gpt-oss-20b"))
    groq_fallback_model: str = field(default_factory=lambda: os.getenv("GROQ_FALLBACK_MODEL", "openai/gpt-oss-20b"))
    spotify_client_id: str = field(default_factory=lambda: os.getenv("SPOTIFY_CLIENT_ID", ""), repr=False)
    spotify_client_secret: str = field(default_factory=lambda: os.getenv("SPOTIFY_CLIENT_SECRET", ""), repr=False)
    lastfm_api_key: str = field(default_factory=lambda: os.getenv("LASTFM_API_KEY", ""), repr=False)
    local_music_dir: Path = field(default_factory=lambda: Path(os.getenv("LOCAL_MUSIC_DIR") or PROJECT_ROOT / "fallback_songs"))
    project_root: Path = PROJECT_ROOT
    backend_root: Path = BACKEND_ROOT

    def __post_init__(self) -> None:
        self.database_path = Path(self.database_path)
        if self.mail_provider not in {"smtp", "resend"}:
            raise ValueError("MAIL_PROVIDER must be smtp or resend.")
        if self.smtp_security not in {"starttls", "ssl"}:
            raise ValueError("SMTP_SECURITY must be starttls or ssl.")
        if self.cookie_samesite not in {"lax", "strict", "none"}:
            raise ValueError("COOKIE_SAMESITE must be lax, strict, or none.")
        if self.cookie_samesite == "none" and not self.cookie_secure:
            raise ValueError("COOKIE_SAMESITE=none requires COOKIE_SECURE=true.")
        if "*" in self.allowed_origins:
            raise ValueError("ALLOWED_ORIGINS must contain explicit origins.")
        if self.environment == "production" and not self.cookie_secure:
            raise ValueError("Production requires COOKIE_SECURE=true and HTTPS.")
        if not 1 <= self.session_hours <= 720 or not 1 <= self.guest_session_hours <= 72:
            raise ValueError("Session lifetime is out of range.")


settings = Settings()
