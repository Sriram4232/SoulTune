"""Email OTP delivery. Codes and provider credentials are never logged."""
import hashlib
import hmac
import smtplib
import ssl
from email.message import EmailMessage

import httpx

from .config import Settings


class MailUnavailable(Exception):
    pass


def mail_ready(config: Settings) -> bool:
    provider_ready = bool(config.resend_api_key) if config.mail_provider == "resend" else bool(
        config.smtp_host and config.smtp_username and config.smtp_password
    )
    return bool(provider_ready and config.mail_from and len(config.otp_secret) >= 32)


def code_hash(config: Settings, binding: str, code: str) -> str:
    return hmac.new(config.otp_secret.encode(), f"{binding}:{code}".encode(), hashlib.sha256).hexdigest()


def send_otp(config: Settings, recipient: str, code: str) -> None:
    if not mail_ready(config):
        raise MailUnavailable("Email sign-in is not configured. Set the mail settings and OTP_SECRET on the server.")
    subject = "Your SoulTune sign-in code"
    text = (f"Your sign-in code is {code}.\n\n"
            f"It expires in {config.otp_expiry_seconds // 60} minutes and can only be used once.\n"
            "If you did not request this code, ignore this email. Do not share it with anyone.")
    try:
        if config.mail_provider == "resend":
            with httpx.Client(timeout=10) as client:
                result = client.post("https://api.resend.com/emails", headers={
                    "Authorization": f"Bearer {config.resend_api_key}",
                }, json={"from": config.mail_from, "to": [recipient], "subject": subject, "text": text})
                result.raise_for_status()
        else:
            message = EmailMessage()
            message["From"], message["To"], message["Subject"] = config.mail_from, recipient, subject
            message.set_content(text)
            context = ssl.create_default_context()
            if config.smtp_security == "ssl":
                connection = smtplib.SMTP_SSL(config.smtp_host, config.smtp_port, timeout=10, context=context)
            else:
                connection = smtplib.SMTP(config.smtp_host, config.smtp_port, timeout=10)
            with connection:
                if config.smtp_security == "starttls":
                    connection.starttls(context=context)
                connection.login(config.smtp_username, config.smtp_password)
                connection.send_message(message)
    except Exception:
        # Provider errors can contain recipients, message bodies or credentials.
        raise MailUnavailable("We couldn't send your code. Check the mail configuration or try again later.") from None
