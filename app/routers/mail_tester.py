"""Mail-Tester: Public Tool a la mail-tester.com.

Flow:
1. GET /mailtest -> Token generieren, Test-Adresse anzeigen, "warte auf deine Mail"
2. User sendet Mail von seinem Setup an <token>@<MAILTEST_DOMAIN>
3. Backend-Worker (mt_worker.poll_mailtest_inbox) pollt, matched, scored
4. Frontend pollt /api/mailtest/<token>/status alle 3s
5. Sobald ready -> Detail-View

Lead-Capture:
- Eingeloggte User sehen den vollen Breakdown sofort
- Anonyme User sehen Score + grobes Breakdown; Detail-Tipps + PDF erst nach Email-Eingabe.
"""
from __future__ import annotations

import json
import logging
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..database import get_db
from ..dependencies import get_current_user as current_user_optional
from ..models import MailTest, User
from ..templating import render

log = logging.getLogger(__name__)

router = APIRouter()


def _gen_token() -> str:
    """URL-safe Token mit 12 Zeichen -- kollisionsfrei genug fuer Mail-Test-Zwecke."""
    # nur Buchstaben + Zahlen, kein '-' / '_' damit Mail-Adresse hübsch ist
    alphabet = "abcdefghijkmnpqrstuvwxyz23456789"  # ohne i,l,o,0,1 -- verwechslungsfrei
    return "".join(secrets.choice(alphabet) for _ in range(12))


def _format_address(token: str, domain: str) -> str:
    return f"mt-{token}@{domain}"


def _gate_breakdown(test: MailTest, user: User | None) -> dict:
    """Wenn user logged-in ODER lead_email eingegeben -> full breakdown.
    Sonst nur Score + 3 Top-Checks, Rest 'unlock with email'."""
    try:
        bd = json.loads(test.breakdown_json or "{}")
    except json.JSONDecodeError:
        bd = {"total": test.score or 0, "checks": []}

    unlocked = bool(user) or bool(test.lead_email)
    if unlocked:
        bd["_unlocked"] = True
        return bd

    # Anonym: nur die "headline"-Checks (SPF, DKIM, DMARC). Rest hinter Gate.
    headline_keys = {"spf", "dkim", "dmarc"}
    locked_count = 0
    visible_checks = []
    for c in bd.get("checks", []):
        if c.get("key") in headline_keys:
            visible_checks.append(c)
        else:
            locked_count += 1
            visible_checks.append({**c, "_locked": True,
                                    "detail": "🔒 hinter dem Detail-Report",
                                    "fix_hint": None})
    bd["checks"] = visible_checks
    bd["_unlocked"] = False
    bd["_locked_count"] = locked_count
    return bd


# ============================================================================
# Routes
# ============================================================================


@router.get("/mailtest")
def landing(request: Request, db: Session = Depends(get_db),
             user: User | None = Depends(current_user_optional)):
    """Landing: generate a new token + show waiting page."""
    s = get_settings()
    if not s.mailtest_domain:
        # Tool noch nicht konfiguriert -- zeige Hinweis aber kein Fehler
        return render(request, "mailtest_landing.html",
                       user=user, tenant=user.tenant if user else None,
                       active=None, configured=False)

    # Rate-Limit: zu viele Tests von dieser IP heute? Eingeloggte = unlimited.
    ip = request.client.host if request.client else "-"
    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    n_today = db.execute(
        select(MailTest).where(
            MailTest.requester_ip == ip,
            MailTest.created_at >= today_start,
        )
    ).scalars().all()
    if user is None and len(n_today) >= s.mailtest_max_per_ip_per_day:
        return render(request, "mailtest_landing.html",
                       user=user, tenant=user.tenant if user else None,
                       active=None, configured=True,
                       rate_limited=True, max_per_day=s.mailtest_max_per_ip_per_day)

    # Neuer Token + DB-Row
    token = _gen_token()
    # Kollision pro Halbsekunde unwahrscheinlich, aber sicher ist sicher:
    for _ in range(3):
        if not db.execute(select(MailTest).where(MailTest.token == token)).scalars().first():
            break
        token = _gen_token()

    test = MailTest(
        token=token,
        created_at=datetime.now(timezone.utc),
        expires_at=datetime.now(timezone.utc) + timedelta(hours=24),
        requester_ip=ip,
        user_id=user.id if user else None,
    )
    db.add(test)
    db.commit()

    address = _format_address(token, s.mailtest_domain)
    return render(request, "mailtest_landing.html",
                   user=user, tenant=user.tenant if user else None,
                   active=None, configured=True,
                   token=token, address=address)


@router.get("/api/mailtest/{token}/status")
def status(token: str, db: Session = Depends(get_db),
            user: User | None = Depends(current_user_optional)):
    """JSON: ready? + breakdown (mit Gate-Logic)."""
    test = db.execute(select(MailTest).where(MailTest.token == token)).scalars().first()
    if test is None:
        return JSONResponse({"status": "unknown", "msg": "Token unbekannt oder abgelaufen"}, status_code=404)
    if test.received_at is None:
        return JSONResponse({
            "status": "waiting",
            "created_at": test.created_at.isoformat(),
            "expires_at": test.expires_at.isoformat(),
        })
    bd = _gate_breakdown(test, user)
    return JSONResponse({
        "status": "ready",
        "received_at": test.received_at.isoformat(),
        "score": round(test.score or 0, 2),
        "breakdown": bd,
    })


@router.get("/mailtest/{token}")
def result_page(token: str, request: Request, db: Session = Depends(get_db),
                  user: User | None = Depends(current_user_optional)):
    """Result-View. Wenn noch keine Mail eingegangen ist, fallback auf landing-poll."""
    test = db.execute(select(MailTest).where(MailTest.token == token)).scalars().first()
    if test is None:
        raise HTTPException(status_code=404, detail="Test nicht gefunden oder abgelaufen.")
    s = get_settings()
    address = _format_address(test.token, s.mailtest_domain)

    if test.received_at is None:
        # Noch nicht da -> zeige Landing-Style-Status-Page
        return render(request, "mailtest_landing.html",
                       user=user, tenant=user.tenant if user else None,
                       active=None, configured=True,
                       token=test.token, address=address)

    bd = _gate_breakdown(test, user)
    return render(request, "mailtest_result.html",
                   user=user, tenant=user.tenant if user else None,
                   active=None,
                   test=test, address=address,
                   breakdown=bd, unlocked=bd.get("_unlocked"),
                   locked_count=bd.get("_locked_count", 0),
                   score=round(test.score or 0, 1))


@router.post("/mailtest/{token}/unlock")
async def unlock_detail(token: str, request: Request, db: Session = Depends(get_db)):
    """Email entgegennehmen -> Detail-View freischalten + Lead-Notify firen."""
    test = db.execute(select(MailTest).where(MailTest.token == token)).scalars().first()
    if test is None:
        raise HTTPException(status_code=404, detail="Test nicht gefunden.")
    form = await request.form()
    email = (form.get("email") or "").strip().lower()
    if "@" not in email or "." not in email or len(email) < 6:
        return JSONResponse({"ok": False, "error": "Bitte gültige Email-Adresse angeben."}, status_code=400)

    test.lead_email = email
    test.lead_email_at = datetime.now(timezone.utc)
    db.commit()

    # Lead-Notify ans Operator-Postfach (haben wir Helper in marketing.py)
    try:
        from .marketing import _operator_recipients
        from .. import mail as mail_mod
        s = get_settings()
        rcpts = _operator_recipients(s)
        ip = request.client.host if request.client else "-"
        subj = f"[Lead] mailtest unlock: {email} ({test.sender_domain or '?'})"
        text = (
            f"Mail-Tester Lead: jemand hat den Detail-Report freigeschaltet.\n\n"
            f"  Email:           {email}\n"
            f"  Test-Sender:     {test.sender_email or '-'}\n"
            f"  Sender-Domain:   {test.sender_domain or '-'}\n"
            f"  Sender-IP:       {test.sender_ip or '-'}\n"
            f"  Score:           {test.score:.2f}\n"
            f"  Test-IP:         {ip}\n"
            f"  Test-Token:      {test.token}\n\n"
            f"-> Resultat: https://dmarc-geeks.ch/mailtest/{test.token}\n"
        )
        mail_mod.send_mail(to=rcpts, subject=subj, text=text, reply_to=email)
    except Exception as e:  # noqa: BLE001
        log.warning("mailtest unlock notify failed: %s", e)

    return JSONResponse({"ok": True, "redirect": f"/mailtest/{test.token}"})


# Convenience: kurze /mt-Adresse als Server-Side 301 -> mailtest.dmarc-geeks.ch
@router.get("/mt")
def mt_short(request: Request):
    """Wenn jemand /mt aufruft (oder gar mt.dmarc-geeks.ch hier landet),
    redirect auf das eigentliche /mailtest. NPM-redirection-host fuer
    mt.dmarc-geeks.ch -> mailtest.dmarc-geeks.ch ist die saubere Variante."""
    return RedirectResponse("/mailtest", status_code=301)
