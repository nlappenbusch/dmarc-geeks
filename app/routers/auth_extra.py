"""Forgot-password, password reset, and self-service tenant signup."""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import audit
from ..config import get_settings
from ..database import get_db
from ..mail import brand_for, render_email, send_mail, smtp_configured
from ..models import AuthToken, CustomerProfile, Reseller, Tenant, TenantSettings, User
from ..rate_limit import mail_limiter
from ..security import hash_password, make_token, verify_password
from ..templating import render

router = APIRouter()

_SLUG_RE = re.compile(r"[^a-z0-9-]+")


def _slugify(s: str) -> str:
    out = _SLUG_RE.sub("-", s.lower()).strip("-")
    return out or "tenant"


def _absolute_base(request: Request) -> str:
    """Return a usable absolute base URL.

    Prefers the configured BASE_URL setting. Falls back to the current request's
    scheme+host so dev setups without BASE_URL still produce clickable links.
    """
    configured = (get_settings().base_url or "").strip().rstrip("/")
    if configured and "://" in configured:
        return configured
    # Fallback: derive from current request
    return str(request.base_url).rstrip("/")


# --- Forgot password -----------------------------------------------------------
@router.get("/forgot")
def forgot_form(request: Request):
    return render(request, "forgot.html", error=None, sent=False)


@router.post("/forgot")
def forgot_submit(
    request: Request,
    email: str = Form(...),
    db: Session = Depends(get_db),
):
    email = email.lower().strip()
    ip = request.client.host if request.client else "anon"
    if not mail_limiter.take(f"forgot:{ip}:{email}"):
        return render(request, "forgot.html", error="Zu viele Anfragen. Bitte später nochmal.", sent=False)
    user = db.execute(select(User).where(User.email == email)).scalars().first()
    if user:
        token = make_token(32)
        token_hash = hash_password(token)
        db.add(AuthToken(
            kind="reset", email=email, token_hash=token_hash,
            expires_at=datetime.now(timezone.utc) + timedelta(hours=2),
        ))
        db.commit()
        link = f"{_absolute_base(request)}/reset?email={quote(email)}&token={token}"
        # Pick branding from the user's tenant.reseller — falls back to platform default
        tenant = db.get(Tenant, user.tenant_id)
        reseller = db.get(Reseller, tenant.reseller_id) if tenant and tenant.reseller_id else None
        brand = brand_for(reseller)
        send_mail(
            to=email,
            subject=f"{brand['brand_name']} — Passwort zurücksetzen",
            text=(f"Hallo,\n\nzum Zurücksetzen deines Passworts hier klicken:\n{link}\n\n"
                  "Der Link ist 2 Stunden gültig.\n\n"
                  "Falls du keine Anfrage gestellt hast, ignoriere diese Mail."),
            html=render_email("reset", link=link, **brand),
        )
        if not smtp_configured():
            # In dev: surface the link directly so flow is testable
            request.session["flash"] = {"kind": "warn", "text": f"SMTP aus — Link: {link}"}
    return render(request, "forgot.html", error=None, sent=True)


@router.get("/reset")
def reset_form(request: Request, email: str = "", token: str = ""):
    return render(request, "reset.html", email=email, token=token, error=None)


@router.post("/reset")
def reset_submit(
    request: Request,
    email: str = Form(...),
    token: str = Form(...),
    new_password: str = Form(...),
    db: Session = Depends(get_db),
):
    email = email.lower().strip()
    if len(new_password) < 8:
        return render(request, "reset.html", email=email, token=token,
                      error="Passwort muss min. 8 Zeichen haben.")
    candidates = db.execute(
        select(AuthToken).where(
            AuthToken.kind == "reset",
            AuthToken.email == email,
            AuthToken.used_at.is_(None),
            AuthToken.expires_at > datetime.now(timezone.utc),
        )
    ).scalars().all()
    matched = next((c for c in candidates if verify_password(token, c.token_hash)), None)
    if not matched:
        return render(request, "reset.html", email=email, token=token,
                      error="Token ungültig oder abgelaufen.")
    user = db.execute(select(User).where(User.email == email)).scalars().first()
    if not user:
        return render(request, "reset.html", email=email, token=token,
                      error="Account nicht gefunden.")
    user.password_hash = hash_password(new_password)
    matched.used_at = datetime.now(timezone.utc)
    audit.record(db, action="password.reset", tenant_id=user.tenant_id, target_type="user",
                 target_id=user.id, ip=request.client.host if request.client else None)
    db.commit()
    request.session["flash"] = {"kind": "ok", "text": "Passwort geändert. Bitte einloggen."}
    return RedirectResponse("/login", status_code=303)


# --- Self-service signup -------------------------------------------------------
@router.get("/signup")
def signup_form(request: Request):
    if not get_settings().allow_signup:
        return render(request, "signup.html", error=None, disabled=True, sent=False)
    return render(request, "signup.html", error=None, disabled=False, sent=False)


@router.post("/signup")
def signup_submit(
    request: Request,
    email: str = Form(...),
    tenant_name: str = Form(...),
    db: Session = Depends(get_db),
):
    if not get_settings().allow_signup:
        return render(request, "signup.html", error=None, disabled=True, sent=False)
    email = email.lower().strip()
    tenant_name = tenant_name.strip()
    if "@" not in email or not tenant_name:
        return render(request, "signup.html", error="Bitte alle Felder ausfüllen.",
                      disabled=False, sent=False)
    ip = request.client.host if request.client else "anon"
    if not mail_limiter.take(f"signup:{ip}:{email}"):
        return render(request, "signup.html", error="Zu viele Anfragen. Bitte später nochmal.",
                      disabled=False, sent=False)
    # Already a user? Avoid leaking existence; just render "sent".
    existing = db.execute(select(User).where(User.email == email)).scalars().first()
    fallback_link = None
    if not existing:
        token = make_token(32)
        payload = json.dumps({"tenant_name": tenant_name})
        db.add(AuthToken(
            kind="signup", email=email, token_hash=hash_password(token), payload=payload,
            expires_at=datetime.now(timezone.utc) + timedelta(hours=24),
        ))
        db.commit()
        link = f"{_absolute_base(request)}/signup/confirm?email={quote(email)}&token={token}"
        sent = send_mail(
            to=email,
            subject="DMARC Aggregator — Account aktivieren",
            text=(f"Hallo,\n\nklicke zum Aktivieren deines Accounts und Anlegen deines Tenants:\n{link}\n\n"
                  "Gültig 24 Stunden."),
            html=render_email("signup", link=link, tenant_name=tenant_name),
        )
        if not sent:
            # SMTP not configured OR delivery failed — show link inline so the
            # user isn't stuck waiting for a mail that won't arrive.
            fallback_link = link
            if not smtp_configured():
                request.session["flash"] = {"kind": "warn",
                    "text": "SMTP ist nicht konfiguriert. Klick den Link unten, um den Account zu aktivieren."}
            else:
                request.session["flash"] = {"kind": "warn",
                    "text": "Mail-Versand ist fehlgeschlagen (Server-Log prüfen). Klick den Link unten, um trotzdem zu aktivieren."}
    return render(request, "signup.html", error=None, disabled=False, sent=True,
                  fallback_link=fallback_link)


@router.get("/signup/confirm")
def signup_confirm_form(request: Request, email: str = "", token: str = ""):
    return render(request, "signup_confirm.html", email=email, token=token, error=None)


@router.post("/signup/confirm")
def signup_confirm_submit(
    request: Request,
    email: str = Form(...),
    token: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    email = email.lower().strip()
    if len(password) < 8:
        return render(request, "signup_confirm.html", email=email, token=token,
                      error="Passwort muss min. 8 Zeichen haben.")
    # Defensive: in URLs wird "+" als Leerzeichen dekodiert. Wenn die Email mit
    # einem Leerzeichen ankommt, ist sie unter Umständen unter "+" gespeichert.
    email_candidates = {email}
    if " " in email:
        email_candidates.add(email.replace(" ", "+"))
    candidates = db.execute(
        select(AuthToken).where(
            AuthToken.kind == "signup",
            AuthToken.email.in_(email_candidates),
            AuthToken.used_at.is_(None),
            AuthToken.expires_at > datetime.now(timezone.utc),
        )
    ).scalars().all()
    matched = next((c for c in candidates if verify_password(token, c.token_hash)), None)
    if not matched:
        return render(request, "signup_confirm.html", email=email, token=token,
                      error="Token ungültig oder abgelaufen.")
    # Use the email as actually stored on the token (avoids stale " " variant in DB)
    email = matched.email
    if db.execute(select(User).where(User.email == email)).scalars().first():
        return render(request, "signup_confirm.html", email=email, token=token,
                      error="Account existiert bereits.")
    payload = json.loads(matched.payload or "{}")
    tname = payload.get("tenant_name") or "Mein Tenant"
    base = _slugify(tname); slug = base; n = 1
    while db.execute(select(Tenant).where(Tenant.slug == slug)).scalars().first():
        n += 1; slug = f"{base}-{n}"
    tenant = Tenant(name=tname, slug=slug)
    db.add(tenant); db.flush()
    if db.get(TenantSettings, tenant.id) is None:
        db.add(TenantSettings(tenant_id=tenant.id))
    if db.get(CustomerProfile, tenant.id) is None:
        db.add(CustomerProfile(tenant_id=tenant.id, company_name=tname, contact_email=email))
    user = User(email=email, password_hash=hash_password(password),
                tenant_id=tenant.id, is_admin=True)
    db.add(user)
    matched.used_at = datetime.now(timezone.utc)
    audit.record(db, action="signup.confirm", tenant_id=tenant.id, target_type="user",
                 target_id=email, details={"tenant": tname},
                 ip=request.client.host if request.client else None)
    db.commit()
    request.session["flash"] = {"kind": "ok", "text": f"Tenant „{tname}“ angelegt. Bitte einloggen."}
    return RedirectResponse("/login", status_code=303)
