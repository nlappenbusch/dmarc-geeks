"""Admin-Tool: M365 Threat-Policy-Test.

Schickt eine Matrix markierter Test-Mails an ein M365-Postfach, jede triggert
gezielt einen Defender-/EOP-Policy-Pfad. Zeigt, was gesendet wurde + wo man
das Ergebnis prueft. Wo die Mails landen (Inbox/Junk/Quarantaene), sieht man
im M365-Portal — die App hat darauf keinen Zugriff.

Payloads sind harmlose Industrie-Teststrings (EICAR/GTUBE), kein Schadcode.
Der eigentliche Fall-Bau liegt in app/threattest.py (geteilt mit dem CLI).
"""
from __future__ import annotations

import logging
import secrets
import smtplib
import ssl
import time
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, Request
from fastapi.responses import RedirectResponse

from ..config import get_settings
from ..dependencies import require_superadmin
from ..models import User
from ..templating import render
from ..threattest import build_message, make_cases

log = logging.getLogger(__name__)

router = APIRouter(prefix="/admin")


def _send_batch(recipient: str, case_ids: list[str], spoof_from: str | None,
                run_id: str, delay: float = 1.0) -> None:
    """Sendet den Test-Batch. Laeuft als BackgroundTask (Starlette-Threadpool)."""
    s = get_settings()
    if not s.smtp_host:
        log.warning("threattest[%s]: SMTP nicht konfiguriert, Abbruch", run_id)
        return
    sender = s.smtp_from or s.smtp_user
    all_cases = make_cases(spoof_from if "spoof-from" in case_ids else None)
    selected = [c for c in all_cases
                if c.id in case_ids and not c.skip_reason]
    if not selected:
        log.warning("threattest[%s]: keine gueltigen Faelle", run_id)
        return

    if s.smtp_tls_verify:
        ctx = ssl.create_default_context()
    else:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE

    try:
        if s.smtp_port == 465:
            srv = smtplib.SMTP_SSL(s.smtp_host, s.smtp_port, context=ctx,
                                   timeout=20)
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


@router.get("/threattest")
def form(request: Request, user: User = Depends(require_superadmin)):
    """Formular: Zielpostfach + Faelle auswaehlen."""
    s = get_settings()
    cases = [c for c in make_cases(None) if not c.skip_reason]
    # nach Kategorie gruppieren (Reihenfolge des Auftretens beibehalten)
    groups: dict[str, list] = {}
    for c in cases:
        groups.setdefault(c.category, []).append(c)
    return render(request, "admin_threattest.html", user=user,
                  tenant=user.tenant, active="threattest",
                  groups=groups,
                  smtp_configured=bool(s.smtp_host),
                  smtp_from=(s.smtp_from or s.smtp_user or "—"),
                  smtp_host=s.smtp_host or "—",
                  sent=None)


@router.post("/threattest/send")
async def send(request: Request, background: BackgroundTasks,
               user: User = Depends(require_superadmin)):
    """Batch validieren + im Hintergrund senden, Bestaetigung anzeigen."""
    s = get_settings()
    form_data = await request.form()
    recipient = (form_data.get("recipient") or "").strip()
    case_ids = form_data.getlist("cases")
    spoof_from = (form_data.get("spoof_from") or "").strip() or None

    cases_all = [c for c in make_cases(None) if not c.skip_reason]
    groups: dict[str, list] = {}
    for c in cases_all:
        groups.setdefault(c.category, []).append(c)

    def _err(msg: str):
        return render(request, "admin_threattest.html", user=user,
                      tenant=user.tenant, active="threattest", groups=groups,
                      smtp_configured=bool(s.smtp_host),
                      smtp_from=(s.smtp_from or s.smtp_user or "—"),
                      smtp_host=s.smtp_host or "—", sent=None, error=msg)

    if not s.smtp_host:
        return _err("SMTP ist nicht konfiguriert (SMTP_HOST fehlt). "
                    "Erst unter Admin → System / .env einrichten.")
    if "@" not in recipient or "." not in recipient.split("@")[-1]:
        return _err("Bitte ein gueltiges Ziel-Postfach angeben.")
    if not case_ids:
        return _err("Mindestens einen Test-Fall auswaehlen.")
    if "spoof-from" in case_ids and not spoof_from:
        return _err("Fuer den Spoof-Fall bitte die zu faelschende Absender-"
                    "Adresse angeben (z.B. ceo@deine-domain.de).")

    run_id = datetime.now(timezone.utc).strftime("%m%d-%H%M") + "-" + \
        secrets.token_hex(2)

    # Auswahl fuer die Bestaetigungs-Ansicht aufloesen (inkl. Spoof-Fall).
    resolved = make_cases(spoof_from if "spoof-from" in case_ids else None)
    chosen = [c for c in resolved if c.id in case_ids and not c.skip_reason]

    background.add_task(_send_batch, recipient, list(case_ids), spoof_from,
                        run_id)
    log.info("threattest[%s]: Batch geplant (%d Faelle) an %s durch %s",
             run_id, len(chosen), recipient, user.email)

    sender = s.smtp_from or s.smtp_user or "—"
    return render(request, "admin_threattest.html", user=user,
                  tenant=user.tenant, active="threattest", groups=groups,
                  smtp_configured=True, smtp_from=sender, smtp_host=s.smtp_host,
                  sent={"run_id": run_id, "recipient": recipient,
                        "sender": sender, "cases": chosen,
                        "count": len(chosen)})
