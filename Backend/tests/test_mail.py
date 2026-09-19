import pytest

from app import mail
from app.config import Settings


def configured(**kwargs):
    return Settings(mail_provider='smtp', mail_from='SoulTune <sender@example.test>',
                    smtp_host='smtp.example.test', smtp_username='sender@example.test',
                    smtp_password='fixture-app-password', otp_secret='fixture-otp-secret-at-least-32-characters', **kwargs)


def test_mail_configuration_requires_a_secret_and_provider_credentials():
    settings = configured()
    assert mail.mail_ready(settings)
    settings.otp_secret = ''
    assert not mail.mail_ready(settings)
    assert 'fixture-app-password' not in repr(configured())


def test_smtp_uses_tls_login_and_sends_code(monkeypatch):
    events = []
    class SMTP:
        def __init__(self, host, port, timeout):
            assert host == 'smtp.example.test' and port == 587 and timeout == 10
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def starttls(self, context):
            assert context.check_hostname
            events.append('tls')
        def login(self, username, password):
            assert events == ['tls'] and password == 'fixture-app-password'
            events.append('login')
        def send_message(self, message):
            assert message['To'] == 'listener@example.test'
            assert '123456' in message.get_content()
            events.append('send')
    monkeypatch.setattr(mail.smtplib, 'SMTP', SMTP)
    mail.send_otp(configured(), 'listener@example.test', '123456')
    assert events == ['tls', 'login', 'send']


def test_mail_provider_errors_are_sanitized(monkeypatch):
    def fail(*args, **kwargs):
        raise RuntimeError('fixture-app-password confidential provider details')
    monkeypatch.setattr(mail.smtplib, 'SMTP', fail)
    with pytest.raises(mail.MailUnavailable) as error:
        mail.send_otp(configured(), 'listener@example.test', '123456')
    assert 'fixture-app-password' not in str(error.value)
    assert '123456' not in str(error.value)
