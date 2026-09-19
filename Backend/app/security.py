"""Security facade delegating to ``app.core.security``.

Maintained for backward compatibility.
"""

from __future__ import annotations

from .core.security import (
    DUMMY_PASSWORD_HASH,
    SCRYPT_N,
    SCRYPT_P,
    SCRYPT_R,
    hash_password,
    new_token,
    token_hash,
    verify_password,
)

__all__ = [
    "DUMMY_PASSWORD_HASH",
    "SCRYPT_N",
    "SCRYPT_P",
    "SCRYPT_R",
    "hash_password",
    "new_token",
    "token_hash",
    "verify_password",
]
