"""Newsletter-Anmeldung mit Double-Opt-In.

Drei Routes:
- POST /newsletter/subscribe  -> Email annehmen, Confirm-Mail raus, Status-Page
- GET  /newsletter/confirm    -> Token validieren, confirmed_at setzen
- GET  /newsletter/unsubscribe -> Token validieren, abmelden
"""
from __future__ import annotations

import logging
import secrets
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..database import get_db
from ..models import NewsletterSubscriber
from ..rate_limit import mail_limiter
from ..templating import render

log = logging.getLogger(__name__)

router = APIRouter()


@router.post("/newsletter/subscribe")
async def subscribe(request: Request, db: Session = Depends(get_db)):
    """Email annehmen, Confirm-Mail rausschicken (Double-Opt-In)."""
    form = await request.form()
    email = (form.get("email") or "").strip().lower()
    source = (form.get("source") or "").strip()[:64]
    honeypot = (form.get("website") or "").strip()

    if honeypot:
        return RedirectResponse("/newsletter/check-email", status_code=303)

    if "@" not in email or "." not in email or len(email) < 6:
        return render(request, "newsletter_status.html",
                       user=None, tenant=None, active=None,
                       status="error",
                       message="Bitte gültige E-Mail-Adresse angeben.")

    # Rate-Limit pro IP
    ip = request.client.host if request.client else "-"
    if not mail_limiter.take(f"newsletter:{ip}"):
        return render(request, "newsletter_status.html",
                       user=None, tenant=None, active=None,
                       status="error",
                       message="Zu viele Anmelde-Versuche von dieser IP. Bitte später nochmal.")

    sub = db.execute(select(NewsletterSubscriber).where(NewsletterSubscriber.email == email)).scalars().first()
    if sub is None:
        sub = NewsletterSubscriber(
            email=email,
            confirm_token=secrets.token_urlsafe(32),
            unsubscribe_token=secrets.token_urlsafe(32),
            source=source or "footer",
            requester_ip=ip,
        )
        db.add(sub)
        db.commit()
    elif sub.confirmed_at is not None:
        # bereits bestaetigt
        return render(request, "newsletter_status.html",
                       user=None, tenant=None, active=None,
                       status="already",
                       message="Du bist schon angemeldet. Wir melden uns, sobald's was Neues gibt.")
    else:
        # Nicht bestaetigt -> neuen Token + Mail nochmal raus (Resend-Pattern)
        sub.confirm_token = secrets.token_urlsafe(32)
        db.commit()

    # Confirm-Mail rausschicken
    try:
        from .. import mail as mail_mod
        s = get_settings()
        base = (s.base_url or "https://dmarc-geeks.ch").rstrip("/")
        confirm_url = f"{base}/newsletter/confirm?token={sub.confirm_token}"
        text = (
            f"Hallo,\n\n"
            f"du hast dich beim DMARC Geeks Wissens-Newsletter angemeldet. "
            f"Damit wir dir wirklich Mails schicken duerfen, bestaetige bitte deine Adresse:\n\n"
            f"  {confirm_url}\n\n"
            f"Falls du das nicht warst, ignorier diese Mail.\n\n"
            f"Liebe Gruesse\nDMARC Geeks\n"
        )
        html = mail_mod.render_email(
            "newsletter_confirm",
            confirm_url=confirm_url,
            brand_name="DMARC Geeks",
            brand_color="#2563eb",
            brand_logo=None,
        )
        mail_mod.send_mail(
            to=email,
            subject="Bitte bestaetige deine Newsletter-Anmeldung - DMARC Geeks",
            text=text, html=html,
        )
    except Exception as e:  # noqa: BLE001
        log.warning("newsletter: confirm-mail-send failed: %s", e)

    return render(request, "newsletter_status.html",
                   user=None, tenant=None, active=None,
                   status="check_email",
                   message=f"Wir haben dir eine Bestätigungs-Mail an {email} geschickt. Klick den Link drin — dann bist du dabei.")


@router.get("/newsletter/confirm")
def confirm(request: Request, token: str = "", db: Session = Depends(get_db)):
    if not token:
        return render(request, "newsletter_status.html",
                       user=None, tenant=None, active=None,
                       status="error", message="Token fehlt.")
    sub = db.execute(select(NewsletterSubscriber).where(NewsletterSubscriber.confirm_token == token)).scalars().first()
    if sub is None:
        return render(request, "newsletter_status.html",
                       user=None, tenant=None, active=None,
                       status="error",
                       message="Token ungültig oder abgelaufen. Falls du dich neu anmelden willst: zurück zur Anmeldung.")
    if sub.confirmed_at:
        return render(request, "newsletter_status.html",
                       user=None, tenant=None, active=None,
                       status="already",
                       message="Du bist schon bestätigt — alles gut.")
    sub.confirmed_at = datetime.now(timezone.utc)
    sub.confirm_token = None
    db.commit()
    return render(request, "newsletter_status.html",
                   user=None, tenant=None, active=None,
                   status="confirmed",
                   message=f"Geil, {sub.email} — du bist im Verteiler. Du kriegst max. 1 Mail/Monat mit Mail-Security-Insights.")


@router.get("/newsletter/unsubscribe")
def unsubscribe(request: Request, token: str = "", db: Session = Depends(get_db)):
    if not token:
        return render(request, "newsletter_status.html",
                       user=None, tenant=None, active=None,
                       status="error", message="Token fehlt.")
    sub = db.execute(select(NewsletterSubscriber).where(NewsletterSubscriber.unsubscribe_token == token)).scalars().first()
    if sub is None:
        return render(request, "newsletter_status.html",
                       user=None, tenant=None, active=None,
                       status="error",
                       message="Token ungültig — vielleicht schon abgemeldet?")
    sub.unsubscribed_at = datetime.now(timezone.utc)
    db.commit()
    return render(request, "newsletter_status.html",
                   user=None, tenant=None, active=None,
                   status="unsubscribed",
                   message=f"Du bist raus, {sub.email}. Schade — aber wir verstehen.")
