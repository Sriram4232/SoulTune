"""Mail facade delegating to ``app.infrastructure.mail``.

Maintained for backward compatibility and test runner monkeypatching.
"""

from __future__ import annotations

import httpx
import smtplib

from .infrastructure.mail import (
    MailUnavailable,
    code_hash,
    mail_ready,
    send_otp,
)

__all__ = [
    "MailUnavailable",
    "code_hash",
    "httpx",
    "mail_ready",
    "send_otp",
    "smtplib",
]
