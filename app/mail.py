"""SMTP sender. No-op if SMTP is not configured."""
from __future__ import annotations

import logging
import smtplib
import ssl
from email.message import EmailMessage
from typing import Iterable, Optional

from .config import get_settings
from .templating import templates

log = logging.getLogger(__name__)


def render_email(name: str, **context) -> str:
    """Render an HTML email template by name (without .html)."""
    # Default branding context — overridable per call
    context.setdefault("brand_name", "DMARC Aggregator")
    context.setdefault("brand_logo", None)
    context.setdefault("brand_color", "#2563eb")
    return templates.get_template(f"email/{name}.html").render(**context)


def brand_for(reseller) -> dict:
    """Build the branding context dict for a Reseller. Falls back to platform default."""
    if reseller is None or getattr(reseller, "is_platform", False):
        return {"brand_name": "DMARC Aggregator", "brand_logo": None, "brand_color": "#2563eb"}
    return {
        "brand_name": reseller.app_name or "DMARC Aggregator",
        "brand_logo": reseller.logo_url,
        "brand_color": reseller.brand_color or "#2563eb",
    }


def smtp_configured() -> bool:
    s = get_settings()
    return bool(s.smtp_host)


def send_mail(*, to: Iterable[str] | str, subject: str, text: str, html: Optional[str] = None) -> bool:
    """Send an email via SMTP. Returns True on success, False otherwise.

    Verhandelt EHLO-Capabilities: opportunistic STARTTLS wenn der Server's
    anbietet, AUTH nur wenn advertised. Loggt klare Fehler-Details, damit
    silent-fail leichter zu diagnostizieren ist.
    """
    s = get_settings()
    if not s.smtp_host:
        log.info("SMTP not configured — skipping mail to %s (subject=%r)", to, subject)
        return False

    recipients = [to] if isinstance(to, str) else list(to)
    if not recipients:
        return False

    msg = EmailMessage()
    msg["From"] = s.smtp_from
    msg["To"] = ", ".join(recipients)
    msg["Subject"] = subject
    msg.set_content(text)
    if html:
        msg.add_alternative(html, subtype="html")

    # Build TLS context. If smtp_tls_verify is False, accept self-signed certs
    # (common with small/private mail providers). Strict verify is default.
    if s.smtp_tls_verify:
        tls_ctx = ssl.create_default_context()
    else:
        tls_ctx = ssl.create_default_context()
        tls_ctx.check_hostname = False
        tls_ctx.verify_mode = ssl.CERT_NONE

    try:
        if s.smtp_port == 465:
            srv = smtplib.SMTP_SSL(s.smtp_host, s.smtp_port, context=tls_ctx, timeout=15)
            srv.ehlo()
        else:
            srv = smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=15)
            srv.ehlo()
            offers_starttls = srv.has_extn("starttls")
            # Opportunistic TLS: if server offers it, use it (unless explicitly
            # on plain port 25 with use_tls=False).
            if offers_starttls and (s.smtp_use_tls or s.smtp_port != 25):
                srv.starttls(context=tls_ctx)
                srv.ehlo()

        # AUTH only if server advertises it AND credentials are configured
        offers_auth = srv.has_extn("auth")
        if s.smtp_user and offers_auth:
            srv.login(s.smtp_user, s.smtp_password)
        elif s.smtp_user and not offers_auth:
            log.info("SMTP %s:%s does not advertise AUTH — sending anonymously",
                     s.smtp_host, s.smtp_port)

        srv.send_message(msg)
        srv.quit()
        log.info("Mail sent to %s (subject=%r)", recipients, subject)
        return True
    except smtplib.SMTPRecipientsRefused as e:
        # Common: relay refuses with 550 + Spamhaus / DNSBL hint
        log.warning("SMTP recipient refused for %s: %s", recipients, e.recipients)
        return False
    except smtplib.SMTPSenderRefused as e:
        log.warning("SMTP sender %s refused: %s %s", msg["From"], e.smtp_code, e.smtp_error)
        return False
    except smtplib.SMTPAuthenticationError as e:
        log.warning("SMTP AUTH refused on %s:%s: %s %s", s.smtp_host, s.smtp_port,
                    e.smtp_code, e.smtp_error)
        return False
    except smtplib.SMTPException as e:
        log.warning("SMTP error talking to %s:%s: %s", s.smtp_host, s.smtp_port, e)
        return False
    except Exception as e:  # noqa: BLE001
        log.warning("SMTP send failed (%s): %s", type(e).__name__, e)
        return False
