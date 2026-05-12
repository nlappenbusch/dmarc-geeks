"""Mail-Tester Worker: pollt die System-Catch-All-Mailbox, matched eingehende
Mails per <token>@<mailtest_domain> an offene MailTests, scored, speichert.

Wird vom Scheduler periodisch aufgerufen (interval=MAILTEST_POLL_SECONDS).
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta, timezone
from email.utils import parseaddr
from typing import Optional

from sqlalchemy import select

from .config import get_settings
from .database import SessionLocal
from .models import LeadSnapshot, MailTest

log = logging.getLogger(__name__)


# Adresse hat die Form 'mt-<token>@<domain>' -- _format_address() in
# routers/mail_tester.py legt das so an. Plus-Adressing tolerieren wir
# (mt-XXX+sub@... funktioniert genauso) damit User die Adresse z.B. fuer
# Filter-Tags benutzen kann.
_TOKEN_LOCAL_RE = re.compile(r"^mt-([A-Za-z0-9]{4,32})(?:\+.*)?$", re.IGNORECASE)


def _extract_token(addr: str, domain: str) -> Optional[str]:
    """E-Mail-Adresse 'mt-<token>@<domain>' → '<token>' (ohne Prefix).
    Plus-Adressing-tolerant. Returns None wenn Adresse nicht zum Pattern passt."""
    if not addr or "@" not in addr:
        return None
    local, dom = addr.rsplit("@", 1)
    if dom.lower() != domain.lower():
        return None
    m = _TOKEN_LOCAL_RE.match(local.strip())
    return m.group(1).lower() if m else None


def _mirror_mailtest_to_lead(db, test: MailTest, breakdown) -> bool:
    """Erstellt/updated einen LeadSnapshot fuer die Sender-Domain dieser
    Test-Mail. Source = 'mailtest-incoming'. Email + Domain ist Pflicht.

    Idempotent: existierender Lead mit gleicher (email, domain)-Kombi wird
    upgedated (Score/Top-Action), nicht doppelt angelegt.
    """
    if not (test.sender_email and test.sender_domain):
        return False
    try:
        email = test.sender_email.lower().strip()
        domain = test.sender_domain.lower().strip()

        # Score 0..10 -> 0..100 normalisiert + Grade-Mapping
        ml_score = test.score or 0
        ml_grade = ("A" if ml_score >= 9 else
                     "B" if ml_score >= 7 else
                     "C" if ml_score >= 5 else
                     "D" if ml_score >= 3 else "F")

        # Top-Issue: erstes fail/warn aus dem Breakdown
        top_action = None
        try:
            bd_dict = json.loads(breakdown.to_json())
            for c in bd_dict.get("checks", []):
                if c.get("status") in ("fail", "warn"):
                    top_action = c.get("fix_hint") or c.get("detail")
                    if top_action:
                        break
        except Exception:  # noqa: BLE001
            pass

        # has_dmarc/spf/dkim aus den Authentication-Results-Checks ableiten
        has_dmarc = has_spf = has_dkim = None
        for c in (breakdown.checks or []):
            key = getattr(c, "key", None)
            status = getattr(c, "status", None)
            if key == "spf":
                has_spf = (status == "pass")
            elif key == "dkim":
                has_dkim = (status == "pass")
            elif key == "dmarc":
                has_dmarc = (status == "pass")

        existing = db.execute(
            select(LeadSnapshot).where(
                LeadSnapshot.email == email,
                LeadSnapshot.domain == domain,
            )
        ).scalars().first()
        if existing is None:
            lead = LeadSnapshot(
                email=email, domain=domain,
                grade=ml_grade, score=int(round(ml_score * 10)),
                top_action=top_action,
                has_dmarc=has_dmarc, has_spf=has_spf, has_dkim=has_dkim,
                source="mailtest-incoming",
                utm_campaign=f"mt-{test.token}",
                requester_ip=test.sender_ip,
            )
            db.add(lead)
            log.info("mailtest: lead created (sender=%s, domain=%s, grade=%s)",
                      email, domain, ml_grade)
        else:
            existing.grade = ml_grade
            existing.score = int(round(ml_score * 10))
            if top_action and not existing.top_action:
                existing.top_action = top_action
            if has_dmarc is not None: existing.has_dmarc = has_dmarc
            if has_spf is not None: existing.has_spf = has_spf
            if has_dkim is not None: existing.has_dkim = has_dkim
            log.info("mailtest: lead updated (sender=%s, domain=%s, grade=%s)",
                      email, domain, ml_grade)
        db.commit()
        return True
    except Exception:  # noqa: BLE001
        log.warning("mailtest: lead mirror failed", exc_info=True)
        db.rollback()
        return False


def _notify_operators_about_mailtest(test: MailTest, breakdown) -> None:
    """Schick Operator-Mail (smtp_from + superadmin + lead_notify_emails)
    direkt nach Test-Empfang — wie alle anderen Lead-Flows."""
    s = get_settings()
    try:
        from . import mail as mail_mod
        from .routers.marketing import _operator_recipients
        rcpts = _operator_recipients(s)
        if not rcpts:
            return

        score = test.score or 0
        grade = ("A" if score >= 9 else "B" if score >= 7 else
                  "C" if score >= 5 else "D" if score >= 3 else "F")
        base_url = (s.base_url or "https://dmarc-geeks.ch").rstrip("/")
        result_url = f"{base_url}/mailtest/{test.token}"

        # Top-3 Issues fuer den Operator
        issues_text = []
        issues_html = []
        for c in (breakdown.checks or []):
            if getattr(c, "status", None) in ("fail", "warn"):
                lab = getattr(c, "label", "")
                det = getattr(c, "detail", "")
                issues_text.append(f"  - [{c.status}] {lab}: {det[:140]}")
                issues_html.append(
                    f'<li><strong>[{c.status}] {lab}:</strong> {det[:200]}</li>'
                )
                if len(issues_text) >= 3:
                    break

        subj = (f"[Mailtest] {test.sender_domain or '?'} — "
                f"Score {score:.1f}/10 (Grade {grade})")
        text = (
            f"Neuer Mail-Tester-Eingang -- Sender hat unsere Test-Adresse "
            f"benutzt, ist damit ein eingehender Lead.\n\n"
            f"  Sender-Email:    {test.sender_email or '-'}\n"
            f"  Sender-Domain:   {test.sender_domain or '-'}\n"
            f"  Sender-IP:       {test.sender_ip or '-'}\n"
            f"  Subject:         {(test.subject or '-')[:120]}\n"
            f"  Score:           {score:.2f}/10 (Grade {grade})\n"
            f"  Test-Token:      {test.token}\n"
            f"  Empfangen:       {test.received_at.strftime('%d.%m.%Y %H:%M UTC') if test.received_at else '-'}\n\n"
            + ("Auffaellige Checks:\n" + "\n".join(issues_text) + "\n\n" if issues_text else "")
            + f"-> Resultat:    {result_url}\n"
            f"-> Lead-Detail: {base_url}/admin/leads (Filter source=mailtest-incoming)\n"
        )
        html = (
            f'<table cellpadding="0" cellspacing="0" '
            f'style="font:14px -apple-system,Inter,sans-serif;color:#0f172a">'
            f'<tr><td style="padding:0 0 12px 0">'
            f'<div style="display:inline-block;background:linear-gradient(135deg,#2563eb,#7c3aed);'
            f'color:white;padding:6px 14px;border-radius:999px;font-size:12px;font-weight:600;'
            f'letter-spacing:.04em;text-transform:uppercase">Mailtest-Lead</div></td></tr>'
            f'<tr><td style="padding:0 0 14px 0"><h2 style="margin:0;font-size:20px">'
            f'<a href="{result_url}" style="color:#2563eb;text-decoration:none">'
            f'{test.sender_domain or "?"}</a> · Score <strong>{score:.1f}/10</strong> (Grade {grade})'
            f'</h2></td></tr>'
            f'<tr><td><table style="border-collapse:collapse;font-size:13.5px">'
            f'<tr><td style="padding:4px 14px 4px 0;color:#64748b">Sender-Email</td>'
            f'<td><a href="mailto:{test.sender_email}">{test.sender_email or "-"}</a></td></tr>'
            f'<tr><td style="padding:4px 14px 4px 0;color:#64748b">Subject</td>'
            f'<td>{(test.subject or "-")[:120]}</td></tr>'
            f'<tr><td style="padding:4px 14px 4px 0;color:#64748b">Sender-IP</td>'
            f'<td><code>{test.sender_ip or "-"}</code></td></tr>'
            f'<tr><td style="padding:4px 14px 4px 0;color:#64748b">Token</td>'
            f'<td><code>{test.token}</code></td></tr></table></td></tr>'
            + (f'<tr><td style="padding:14px 0 0 0">'
               f'<div style="font-weight:600;margin-bottom:6px;color:#dc2626">'
               f'Auffaellige Checks:</div>'
               f'<ul style="margin:0;padding-left:20px;color:#1f2937">'
               + "".join(issues_html) + '</ul></td></tr>' if issues_html else '')
            + f'<tr><td style="padding:16px 0 0 0">'
            f'<a href="{result_url}" style="display:inline-block;background:#2563eb;color:white;'
            f'padding:9px 16px;border-radius:8px;text-decoration:none;font-weight:600;'
            f'margin-right:6px">Resultat &ouml;ffnen</a>'
            f'<a href="{base_url}/admin/leads" style="display:inline-block;background:#16a34a;'
            f'color:white;padding:9px 16px;border-radius:8px;text-decoration:none;font-weight:600">'
            f'Lead-Dashboard</a>'
            f'</td></tr></table>'
        )
        mail_mod.send_mail(
            to=rcpts,
            subject=subj, text=text, html=html,
            reply_to=test.sender_email,
        )
        log.info("mailtest: operator-notify sent for token=%s sender=%s",
                  test.token, test.sender_email or "?")
    except Exception:  # noqa: BLE001
        log.warning("mailtest: operator-notify failed", exc_info=True)


def _expire_old_tests(db) -> int:
    """Cleanup: alte abgelaufene Tests (24h+) loeschen. Returns count."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    old = db.execute(
        select(MailTest).where(MailTest.created_at < cutoff)
    ).scalars().all()
    n = 0
    for t in old:
        db.delete(t)
        n += 1
    if n:
        db.commit()
        log.info("mailtest: %d alte Tests aufgeraeumt", n)
    return n


def poll_mailtest_inbox() -> dict:
    """Hauptfunktion: einmal pollen, alle neuen Mails einsortieren.

    Schedulig: alle MAILTEST_POLL_SECONDS Sekunden via APScheduler.
    Returns dict mit checked/matched/skipped/errors UND optional error_msg
    + error_hint fuer manuelle Diagnose im Admin-UI.
    """
    s = get_settings()
    if not s.mailtest_imap_host or not s.mailtest_domain:
        log.debug("mailtest: not configured (host=%r domain=%r)",
                  s.mailtest_imap_host, s.mailtest_domain)
        missing = []
        if not s.mailtest_domain: missing.append("MAILTEST_DOMAIN")
        if not s.mailtest_imap_host: missing.append("MAILTEST_IMAP_HOST")
        return {"status": "not_configured", "checked": 0, "matched": 0,
                 "skipped": 0, "errors": 0,
                 "error_msg": f"Fehlende Settings: {', '.join(missing)}",
                 "error_hint": "ENV-Vars in /admin/system → Mail-Tester-Gruppe ausfüllen + speichern."}
    if not s.mailtest_imap_user or not s.mailtest_imap_password:
        return {"status": "not_configured", "checked": 0, "matched": 0,
                 "skipped": 0, "errors": 0,
                 "error_msg": "MAILTEST_IMAP_USER oder MAILTEST_IMAP_PASSWORD fehlt.",
                 "error_hint": "User-Form: catch-all@<MAILTEST_DOMAIN>, Passwort aus Mailcow."}

    summary: dict = {"checked": 0, "matched": 0, "skipped": 0, "errors": 0,
                      "host": s.mailtest_imap_host, "port": s.mailtest_imap_port,
                      "user": s.mailtest_imap_user, "ssl": s.mailtest_imap_ssl}

    # Sanity-Check fuer den haeufigsten Konfig-Fehler: Port 993 ist SSL-only,
    # Port 143 ist STARTTLS oder plain. Wenn die Kombi nicht passt, fail fast
    # mit klarer Meldung statt 25s Timeout.
    if s.mailtest_imap_port == 993 and not s.mailtest_imap_ssl:
        summary["errors"] = 1
        summary["error_msg"] = "Config-Fehler: Port 993 + SSL=off"
        summary["error_hint"] = ("Port 993 ist der SSL-Port — ohne SSL gibt's nur Timeout. "
                                  "Setting 'MAILTEST_IMAP_SSL' aktivieren ✓ und speichern.")
        return summary
    if s.mailtest_imap_port == 143 and s.mailtest_imap_ssl:
        summary["errors"] = 1
        summary["error_msg"] = "Config-Fehler: Port 143 + SSL=on"
        summary["error_hint"] = ("Port 143 ist plain/STARTTLS, nicht reines SSL. "
                                  "Entweder Port auf 993 (mit SSL) oder SSL deaktivieren (STARTTLS).")
        return summary

    try:
        from imap_tools import AND, MailBox, MailBoxUnencrypted
    except ImportError:
        log.warning("mailtest: imap-tools not installed")
        return {"status": "imap_tools_missing", "checked": 0, "matched": 0,
                 "skipped": 0, "errors": 1,
                 "error_msg": "Python-Library 'imap-tools' fehlt im Container.",
                 "error_hint": "requirements.txt prüfen + Container rebuilden."}

    try:
        if s.mailtest_imap_ssl:
            mb_ctx = MailBox(s.mailtest_imap_host, port=s.mailtest_imap_port, timeout=25).login(
                s.mailtest_imap_user, s.mailtest_imap_password, initial_folder=s.mailtest_imap_folder)
        else:
            mb_ctx = MailBoxUnencrypted(s.mailtest_imap_host, port=s.mailtest_imap_port, timeout=25).login(
                s.mailtest_imap_user, s.mailtest_imap_password, initial_folder=s.mailtest_imap_folder)

        with SessionLocal() as db:
            with mb_ctx as mb:
                # Nur ungelesene Mails -- nach Bearbeitung markieren wir als gelesen
                for msg in mb.fetch(AND(seen=False), mark_seen=False, bulk=False):
                    summary["checked"] += 1

                    # Alle 'To:'-Adressen durchgehen -- match auf einen unserer Tokens
                    candidates: list[str] = []
                    for header in (msg.to_values or []):
                        candidates.append(parseaddr(header.email if hasattr(header, "email") else str(header))[1])
                    # Plus catch-all -- envelope-rcpt aus 'Delivered-To'
                    for hk in ("Delivered-To", "X-Delivered-To", "Envelope-To"):
                        for h in msg.obj.get_all(hk) or []:
                            candidates.append(parseaddr(h)[1])

                    token = None
                    matched_for: Optional[str] = None
                    for c in candidates:
                        if not c:
                            continue
                        t = _extract_token(c, s.mailtest_domain)
                        if t:
                            token = t
                            matched_for = c
                            break

                    if not token:
                        summary["skipped"] += 1
                        log.debug("mailtest: no token in To=%r", candidates)
                        # markieren als gelesen damit wir's nicht wieder ziehen
                        try:
                            mb.flag(msg.uid, "\\Seen", True)
                        except Exception:  # noqa: BLE001
                            pass
                        continue

                    # Existierenden Test laden
                    test = db.execute(
                        select(MailTest).where(MailTest.token == token)
                    ).scalars().first()
                    if test is None:
                        log.info("mailtest: token %r unbekannt (oder abgelaufen)", token)
                        summary["skipped"] += 1
                        try:
                            mb.flag(msg.uid, "\\Seen", True)
                        except Exception:  # noqa: BLE001
                            pass
                        continue
                    if test.received_at is not None:
                        # Schon ge-scored -- ignorieren (User hat 2x gesendet)
                        log.debug("mailtest: token %r already has a result", token)
                        try:
                            mb.flag(msg.uid, "\\Seen", True)
                        except Exception:  # noqa: BLE001
                            pass
                        continue

                    raw = msg.obj.as_string()  # ganze Mail als string
                    # Score!
                    from .mt_scorer import score_email
                    try:
                        breakdown = score_email(raw)
                    except Exception as e:  # noqa: BLE001
                        log.warning("mailtest: scoring failed for token %r: %s", token, e)
                        summary["errors"] += 1
                        continue

                    test.received_at = datetime.now(timezone.utc)
                    breakdown.received_at_utc = test.received_at.isoformat(timespec="seconds")
                    test.sender_email = breakdown.sender_email
                    test.sender_ip = breakdown.sender_ip
                    test.sender_domain = breakdown.sender_domain
                    test.subject = (breakdown.subject or "")[:998]
                    test.raw_email = raw[:200_000]  # cap, sonst sprengt Postgres-TOAST
                    test.score = breakdown.total
                    test.breakdown_json = breakdown.to_json()
                    db.commit()

                    summary["matched"] += 1
                    log.info("mailtest: token=%s score=%.2f sender=%s",
                              token, breakdown.total, breakdown.sender_email or "?")
                    # Mail als gelesen markieren
                    try:
                        mb.flag(msg.uid, "\\Seen", True)
                    except Exception:  # noqa: BLE001
                        pass

                    # === Lead-Pipeline-Integration ===
                    # 1) Sender-Domain als LeadSnapshot persistieren (auch ohne
                    #    Unlock — der Sender hat eine Mail an unser Tool geschickt,
                    #    das ist ein klares Outbound-Lead-Signal).
                    # 2) Operator-Notify an nlappenbusch@gmail.com + lead_notify_emails.
                    _mirror_mailtest_to_lead(db, test, breakdown)
                    _notify_operators_about_mailtest(test, breakdown)

            # Cleanup-Pass
            _expire_old_tests(db)

    except Exception as e:  # noqa: BLE001
        # Konkrete Diagnose-Hints fuer haeufige Fehler -- damit User im UI
        # sofort versteht woran's lag (statt nur "1 Fehler").
        err_str = str(e)
        err_lower = err_str.lower()
        hint = None
        if "privacyrequired" in err_lower or "plaintext authentication disallowed" in err_lower:
            hint = ("Mailcow lehnt Klartext-Login auf unverschlüsselter Verbindung ab (gut so!). "
                    "Setting auf Port=993 + MAILTEST_IMAP_SSL=on stellen — impliziter SSL ist "
                    "der Standard-Modus.")
        elif "authentication" in err_lower or "login failed" in err_lower or "auth failed" in err_lower:
            hint = ("IMAP-Login abgelehnt. User/Passwort prüfen — meist ist's der Username "
                    "(Mailcow erwartet die volle Adresse, z.B. catch-all@mt.dmarc-geeks.ch).")
        elif "connection refused" in err_lower:
            hint = ("Port 993 nicht erreichbar. Firewall offen? Aus dem App-Container testen: "
                    f"nc -zv {s.mailtest_imap_host} {s.mailtest_imap_port}")
        elif "timed out" in err_lower or "timeout" in err_lower:
            hint = ("Connection-Timeout. DNS resolved den IMAP-Host nicht oder Firewall blockt. "
                    f"Aus dem App-Container: dig +short {s.mailtest_imap_host}")
        elif "name or service" in err_lower or "no such host" in err_lower or "name resolution" in err_lower:
            hint = (f"Hostname '{s.mailtest_imap_host}' kann nicht aufgelöst werden — "
                    "DNS fehlt oder MAILTEST_IMAP_HOST falsch geschrieben.")
        elif "ssl" in err_lower or "certificate" in err_lower or "tls" in err_lower:
            hint = ("SSL/TLS-Problem. Wenn Mailcow ein Self-Signed-Cert hat: SSL-Verify "
                    "ist in imap-tools default an. Hostname muss EXAKT zum Cert passen.")
        elif "no such mailbox" in err_lower or "folder" in err_lower:
            hint = (f"Folder '{s.mailtest_imap_folder}' existiert nicht. "
                    "Default ist 'INBOX' (alle Caps).")
        else:
            hint = "Container-Logs der App ansehen für vollständigen Stack-Trace."
        log.warning("mailtest: poll failed: %s", e, exc_info=True)
        summary["errors"] += 1
        summary["error_msg"] = f"{type(e).__name__}: {err_str}"
        summary["error_hint"] = hint

    return summary
