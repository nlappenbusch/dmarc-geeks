"""Public Tool: M365 Threat-Policy-Test mit Empfaenger-Verifikation.

Schickt eine Matrix markierter Test-Mails an ein M365-Postfach, jede triggert
gezielt einen Defender-/EOP-Policy-Pfad. OEFFENTLICH nutzbar — aber mit
Double-Opt-In gegen Missbrauch: Bevor der Batch rausgeht, muss der Anfragende
einen Code bestaetigen, der an das Ziel-Postfach geschickt wurde. So kann
niemand Fremde beschiessen; nur das eigene Postfach ist erreichbar.

Wo die Mails landen (Inbox/Junk/Quarantaene), sieht man im M365-Portal — die
App hat darauf keinen Zugriff.

Payloads sind harmlose Industrie-Teststrings (EICAR/GTUBE), kein Schadcode.
Der Fall-Bau liegt in app/threattest.py (geteilt mit dem CLI).
"""
from __future__ import annotations

import hmac
import logging
import secrets
import smtplib
import ssl
import time
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import mail as mail_mod
from ..config import get_settings
from ..database import get_db
from ..models import ThreatTest
from ..templating import render
from ..threattest import build_message, make_cases

log = logging.getLogger(__name__)

router = APIRouter()

CODE_TTL_MIN = 30      # Gueltigkeit des Bestaetigungs-Codes
MAX_ATTEMPTS = 5       # Code-Eingabe-Versuche


def _groups():
    """Faelle nach Kategorie gruppiert (fuer die Formular-Anzeige)."""
    cases = [c for c in make_cases(None) if not c.skip_reason]
    groups: dict[str, list] = {}
    for c in cases:
        groups.setdefault(c.category, []).append(c)
    return groups


def _render(request: Request, state: str, **extra):
    s = get_settings()
    ctx = dict(state=state, groups=_groups(),
               smtp_configured=bool(s.smtp_host), user=None, tenant=None,
               active=None)
    ctx.update(extra)
    return render(request, "threattest_landing.html", **ctx)


def _send_batch(recipient: str, case_ids: list[str], spoof_from: str | None,
                run_id: str, impersonate: str | None = None,
                delay: float = 1.0) -> None:
    """Sendet den Test-Batch. Laeuft als BackgroundTask (Starlette-Threadpool)."""
    s = get_settings()
    if not s.smtp_host:
        log.warning("threattest[%s]: SMTP nicht konfiguriert, Abbruch", run_id)
        return
    sender = s.smtp_from or s.smtp_user
    all_cases = make_cases(
        spoof_from if "spoof-from" in case_ids else None,
        impersonate if "impersonation" in case_ids else None)
    selected = [c for c in all_cases if c.id in case_ids and not c.skip_reason]
    if not selected:
        return

    if s.smtp_tls_verify:
        ctx = ssl.create_default_context()
    else:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE

    try:
        if s.smtp_port == 465:
            srv = smtplib.SMTP_SSL(s.smtp_host, s.smtp_port, context=ctx, timeout=20)
            srv.ehlo()
        else:
            srv = smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=20)
            srv.ehlo()
            if srv.has_extn("starttls") and (s.smtp_use_tls or s.smtp_port != 25):
                srv.starttls(context=ctx)
                srv.ehlo()
        if s.smtp_user and srv.has_extn("auth"):
            srv.login(s.smtp_user, s.smtp_password)

        ok, fail = 0, 0
        for i, case in enumerate(selected):
            msg = build_message(case, run_id, sender, recipient)
            try:
                srv.send_message(msg, from_addr=sender, to_addrs=[recipient])
                ok += 1
            except smtplib.SMTPException as exc:
                fail += 1
                log.warning("threattest[%s]: %s fehlgeschlagen: %s",
                            run_id, case.id, exc)
            if delay and i < len(selected) - 1:
                time.sleep(delay)
        srv.quit()
        log.info("threattest[%s]: %d gesendet, %d Fehler -> %s",
                 run_id, ok, fail, recipient)
    except (smtplib.SMTPException, OSError) as exc:
        log.warning("threattest[%s]: SMTP-Fehler: %s", run_id, exc)


# ============================================================================ #
# Routes
# ============================================================================ #

@router.get("/threattest")
def landing(request: Request):
    """Oeffentliches Formular: Ziel-Postfach + Faelle auswaehlen."""
    return _render(request, "form")


@router.get("/threattest/{token}/verify")
def verify_landing(token: str, request: Request, code: str = "",
                   db: Session = Depends(get_db)):
    """Magic-Link aus der Code-Mail: Verify-Seite mit vorausgefuelltem Code.
    Reiner GET (kein Versand) -> Safe-Links-Prefetch loest nichts aus."""
    tt = db.execute(
        select(ThreatTest).where(ThreatTest.token == token)
    ).scalars().first()
    if tt is None:
        return _render(request, "form",
                       error="Anfrage nicht gefunden. Bitte neu starten.")
    if tt.sent_at is not None:
        return _render(request, "done", **_done_ctx(tt))
    if datetime.now(timezone.utc) > tt.expires_at:
        return _render(request, "form",
                       error="Der Code ist abgelaufen. Bitte neu starten.")
    return _render(request, "verify", token=token, recipient=tt.recipient,
                   ttl=CODE_TTL_MIN, prefill_code=code)


@router.post("/threattest/request")
async def request_code(request: Request, db: Session = Depends(get_db)):
    """Anfrage validieren, Row anlegen, Bestaetigungs-Code ans Ziel senden."""
    s = get_settings()
    if not s.smtp_host:
        return _render(request, "form",
                       error="Das Tool wird gerade konfiguriert (SMTP fehlt). "
                             "Bitte spaeter erneut versuchen.")

    form = await request.form()
    recipient = (form.get("recipient") or "").strip().lower()
    case_ids = [c for c in form.getlist("cases")]
    spoof_from = (form.get("spoof_from") or "").strip().lower() or None
    impersonate = (form.get("impersonate") or "").strip() or None

    if "@" not in recipient or "." not in recipient.split("@")[-1]:
        return _render(request, "form", recipient=recipient,
                       error="Bitte ein gueltiges Ziel-Postfach angeben.")
    if not case_ids:
        return _render(request, "form", recipient=recipient,
                       error="Mindestens einen Test-Fall auswaehlen.")
    if "spoof-from" in case_ids and not spoof_from:
        return _render(request, "form", recipient=recipient,
                       error="Fuer den Spoof-Fall bitte die zu faelschende "
                             "Absender-Adresse angeben.")
    if "impersonation" in case_ids and not impersonate:
        return _render(request, "form", recipient=recipient,
                       error="Fuer den Impersonation-Fall bitte den Anzeigenamen "
                             "des zu testenden Users angeben.")

    # Rate-Limit pro IP/Tag (jede Anfrage sendet eine Code-Mail). Exempt-IPs umgehen es.
    ip = request.client.host if request.client else "-"
    exempt = {x.strip() for x in s.threattest_ratelimit_exempt_ips.split(",") if x.strip()}
    if ip not in exempt:
        today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0,
                                                   microsecond=0)
        n_today = db.execute(
            select(ThreatTest).where(ThreatTest.requester_ip == ip,
                                     ThreatTest.created_at >= today)
        ).scalars().all()
        if len(n_today) >= s.threattest_max_per_ip_per_day:
            return _render(request, "form",
                           error=f"Tages-Limit erreicht "
                                 f"({s.threattest_max_per_ip_per_day} Anfragen/Tag). "
                                 "Bitte morgen wieder.")

    token = secrets.token_urlsafe(9)
    code = f"{secrets.randbelow(1000000):06d}"
    now = datetime.now(timezone.utc)
    tt = ThreatTest(
        token=token, created_at=now,
        expires_at=now + timedelta(minutes=CODE_TTL_MIN),
        requester_ip=ip, recipient=recipient,
        case_ids=",".join(case_ids), spoof_from=spoof_from,
        impersonate=impersonate,
        verify_code=code, verify_attempts=0,
    )
    db.add(tt)
    db.commit()

    # EINZIGE Mail an eine unverifizierte Adresse: der Bestaetigungs-Code.
    base = (s.base_url or "https://dmarc-geeks.ch").rstrip("/")
    verify_url = f"{base}/threattest/{token}/verify?code={code}"
    subject = f"DMARC-Geeks Threat-Test — Bestaetigungscode {code}"
    text = (
        "Hallo,\n\n"
        "jemand (hoffentlich du) moechte einen M365-Threat-Policy-Test an dieses\n"
        "Postfach schicken. Damit niemand Fremde beschiessen kann, bestaetige\n"
        f"bitte mit diesem Code:\n\n    {code}\n\n"
        f"Oder direkt bestaetigen: {verify_url}\n\n"
        f"Der Code gilt {CODE_TTL_MIN} Minuten. Erst NACH der Bestaetigung gehen die\n"
        "eigentlichen Test-Mails raus (harmlose EICAR/GTUBE-Teststrings, kein Schadcode).\n\n"
        "Wenn du das nicht warst: ignoriere diese Mail einfach, dann passiert nichts.\n\n"
        "— DMARC Geeks\n"
    )
    html = f"""\
<div style="font-family:-apple-system,Segoe UI,Inter,Helvetica,sans-serif;max-width:480px;margin:0 auto;color:#0f172a;">
  <h2 style="color:#2563eb;margin:0 0 8px;">&#128737; Threat-Test bestätigen</h2>
  <p style="line-height:1.5;">Jemand (hoffentlich du) möchte einen M365-Threat-Policy-Test an dieses Postfach schicken. Zur Bestätigung, dass es dein Postfach ist:</p>
  <div style="background:#f1f5f9;border:2px dashed #2563eb;border-radius:12px;padding:20px;text-align:center;margin:18px 0;">
    <div style="font-size:11px;color:#64748b;text-transform:uppercase;letter-spacing:.06em;margin-bottom:6px;">Dein Code</div>
    <div style="font:700 34px Menlo,Consolas,monospace;letter-spacing:.3em;color:#2563eb;">{code}</div>
  </div>
  <p style="text-align:center;margin:22px 0;">
    <a href="{verify_url}" style="display:inline-block;background:#2563eb;color:#ffffff;text-decoration:none;padding:13px 30px;border-radius:8px;font-weight:700;font-size:15px;">&#10003; Bestätigen &amp; Test starten</a>
  </p>
  <p style="color:#64748b;font-size:13px;line-height:1.5;">Der Code gilt {CODE_TTL_MIN} Minuten. Erst nach der Bestätigung gehen die Test-Mails raus (harmlose EICAR/GTUBE-Teststrings, kein echter Schadcode). Nicht du? Ignorier diese Mail einfach — dann passiert nichts.</p>
  <p style="color:#94a3b8;font-size:12px;">DMARC Geeks &middot; dmarc-geeks.ch</p>
</div>"""
    sent = mail_mod.send_mail(to=recipient, subject=subject, text=text, html=html)
    if not sent:
        return _render(request, "form", recipient=recipient,
                       error="Konnte den Bestaetigungs-Code nicht an diese "
                             "Adresse senden. Tippfehler im Postfach?")

    return _render(request, "verify", token=token, recipient=recipient,
                   ttl=CODE_TTL_MIN)


@router.post("/threattest/{token}/verify")
async def verify(token: str, request: Request, background: BackgroundTasks,
                 db: Session = Depends(get_db)):
    """Code pruefen; bei Erfolg den Test-Batch im Hintergrund senden."""
    tt = db.execute(
        select(ThreatTest).where(ThreatTest.token == token)
    ).scalars().first()
    if tt is None:
        return _render(request, "form",
                       error="Anfrage nicht gefunden. Bitte neu starten.")

    now = datetime.now(timezone.utc)
    if tt.sent_at is not None:
        # Schon bestaetigt + gesendet -> Bestaetigung erneut zeigen (idempotent).
        return _render(request, "done", **_done_ctx(tt))
    if now > tt.expires_at:
        return _render(request, "form",
                       error="Der Code ist abgelaufen. Bitte neu starten.")
    if tt.verify_attempts >= MAX_ATTEMPTS:
        return _render(request, "form",
                       error="Zu viele Fehlversuche. Bitte neu starten.")

    form = await request.form()
    entered = (form.get("code") or "").strip()
    if not hmac.compare_digest(entered, tt.verify_code):
        tt.verify_attempts += 1
        db.commit()
        left = MAX_ATTEMPTS - tt.verify_attempts
        return _render(request, "verify", token=token, recipient=tt.recipient,
                       ttl=CODE_TTL_MIN,
                       error=f"Code stimmt nicht. Noch {left} Versuch(e).")

    # Verifiziert -> Batch planen.
    tt.verified_at = now
    tt.sent_at = now
    db.commit()

    case_ids = [c for c in tt.case_ids.split(",") if c]
    run_id = now.strftime("%m%d-%H%M") + "-" + token[:4]
    background.add_task(_send_batch, tt.recipient, case_ids, tt.spoof_from,
                        run_id, tt.impersonate)
    log.info("threattest[%s]: verifiziert + Batch geplant an %s",
             run_id, tt.recipient)
    return _render(request, "done", **_done_ctx(tt, run_id))


def _done_ctx(tt: ThreatTest, run_id: str | None = None) -> dict:
    s = get_settings()
    case_ids = [c for c in tt.case_ids.split(",") if c]
    resolved = make_cases(
        tt.spoof_from if "spoof-from" in case_ids else None,
        tt.impersonate if "impersonation" in case_ids else None)
    chosen = [c for c in resolved if c.id in case_ids and not c.skip_reason]
    if run_id is None:
        run_id = (tt.sent_at or tt.created_at).strftime("%m%d-%H%M") \
            + "-" + tt.token[:4]
    return dict(run_id=run_id, recipient=tt.recipient,
                sender=(s.smtp_from or s.smtp_user or "—"),
                cases=chosen, count=len(chosen))
