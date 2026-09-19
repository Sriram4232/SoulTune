"""Schemas facade delegating to ``app.core.models``.

Maintained for backward compatibility.
"""

from __future__ import annotations

from .core.models import (
    DEFAULT_PREFERENCES,
    AccountDelete,
    AddTrack,
    CreatePlaylist,
    Feedback,
    Generate,
    InputModel,
    Login,
    MoodProfile,
    PasswordChange,
    PlaylistUpdate,
    ProfileUpdate,
    Refine,
    Register,
    VerifyOTP,
)

__all__ = [
    "AccountDelete",
    "AddTrack",
    "CreatePlaylist",
    "DEFAULT_PREFERENCES",
    "Feedback",
    "Generate",
    "InputModel",
    "Login",
    "MoodProfile",
    "PasswordChange",
    "PlaylistUpdate",
    "ProfileUpdate",
    "Refine",
    "Register",
    "VerifyOTP",
]
