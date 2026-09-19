"""Strict request models; never trust browser-supplied ownership or scores."""
from __future__ import annotations

import re
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


DEFAULT_PREFERENCES = {
    "genres": [], "languages": [], "activities": [], "excluded_artists": [],
    "excluded_genres": [], "playlist_size": 10, "allow_explicit": False,
    "theme": "dark", "personalization": True, "diversity": True,
}


class InputModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Register(InputModel):
    name: str = Field(min_length=1, max_length=80)
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=10, max_length=128, repr=False)

    @field_validator("name")
    @classmethod
    def clean_name(cls, value: str) -> str:
        value = value.strip()
        if not value or any(ord(ch) < 32 for ch in value):
            raise ValueError("Enter a valid name.")
        return value

    @field_validator("email")
    @classmethod
    def clean_email(cls, value: str) -> str:
        value = value.strip().casefold()
        if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value):
            raise ValueError("Enter a valid email address.")
        return value

    @field_validator("password")
    @classmethod
    def check_password(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Use a password with at least 10 characters.")
        return value


class Login(InputModel):
    # Invalid account/password combinations receive the same authentication error.
    email: str = Field(max_length=254)
    password: str = Field(max_length=128, repr=False)

    @field_validator("email")
    @classmethod
    def clean_email(cls, value: str) -> str:
        return value.strip().casefold()


class VerifyOTP(InputModel):
    code: str = Field(pattern=r"^[0-9]{6}$", repr=False)


class PreferenceUpdate(InputModel):
    genres: list[str] | None = Field(default=None, max_length=25)
    languages: list[str] | None = Field(default=None, max_length=25)
    activities: list[str] | None = Field(default=None, max_length=25)
    excluded_artists: list[str] | None = Field(default=None, max_length=100)
    excluded_genres: list[str] | None = Field(default=None, max_length=25)
    playlist_size: int | None = Field(default=None, ge=1, le=10)
    allow_explicit: bool | None = None
    theme: Literal["dark", "light", "system"] | None = None
    personalization: bool | None = None
    diversity: bool | None = None

    @field_validator("genres", "languages", "activities", "excluded_artists", "excluded_genres")
    @classmethod
    def clean_list(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return value
        if any(not item.strip() or len(item) > 100 or any(ord(ch) < 32 for ch in item) for item in value):
            raise ValueError("Preference items must contain 1 to 100 printable characters.")
        return list(dict.fromkeys(item.strip() for item in value))


class ProfileUpdate(InputModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    preferences: PreferenceUpdate | None = None
    onboarding_completed: bool | None = None

    @field_validator("name")
    @classmethod
    def clean_name(cls, value: str | None) -> str | None:
        return Register.clean_name(value) if value is not None else None


class PasswordChange(InputModel):
    current_password: str = Field(max_length=128, repr=False)
    new_password: str = Field(min_length=10, max_length=128, repr=False)

    @field_validator("new_password")
    @classmethod
    def check_password(cls, value: str) -> str:
        return Register.check_password(value)


class AccountDelete(InputModel):
    password: str = Field(default="", max_length=128, repr=False)


class Generate(InputModel):
    request_id: UUID | None = None
    description: str = Field(min_length=3, max_length=2000)
    playlist_size: int = Field(default=10, ge=1, le=20)

    @field_validator("description")
    @classmethod
    def clean_description(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 3:
            raise ValueError("Describe your mood in at least 3 characters.")
        return value


class Refine(InputModel):
    revision: int | None = Field(default=None, ge=0)
    message: str = Field(min_length=2, max_length=2000)

    @field_validator("message")
    @classmethod
    def clean_message(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 2:
            raise ValueError("Describe the change you want.")
        return value


class PlaylistUpdate(InputModel):
    revision: int | None = Field(default=None, ge=0)
    name: str | None = Field(default=None, min_length=1, max_length=120)
    saved: bool | None = None

    @field_validator("name")
    @classmethod
    def clean_name(cls, value: str | None) -> str | None:
        return Register.clean_name(value) if value is not None else None


class CreatePlaylist(InputModel):
    name: str = Field(min_length=1, max_length=80)
    description: str = Field(default="", max_length=500)

    @field_validator("name")
    @classmethod
    def clean_name(cls, value: str) -> str:
        return Register.clean_name(value)


class AddTrack(InputModel):
    track_id: str = Field(min_length=1, max_length=200)
    source_id: str | None = Field(default=None, max_length=100)
    revision: int | None = Field(default=None, ge=0)


class Feedback(InputModel):
    revision: int | None = Field(default=None, ge=0)
    track_id: str = Field(min_length=1, max_length=200)
    feedback: Literal["like", "dislike", "remove"]
