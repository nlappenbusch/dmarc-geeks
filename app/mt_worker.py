"""Mail-Tester Worker: pollt die System-Catch-All-Mailbox, matched eingehende
Mails per <token>@<mailtest_domain> an offene MailTests, scored, speichert.

Wird vom Scheduler periodisch aufgerufen (interval=MAILTEST_POLL_SECONDS).
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone
from email.utils import parseaddr
from typing import Optional

from sqlalchemy import select

from .config import get_settings
from .database import SessionLocal
from .models import MailTest

log = logging.getLogger(__name__)


_TOKEN_LOCAL_RE = re.compile(r"^([A-Za-z0-9_-]{4,32})(?:\+.*)?$")


def _extract_token(addr: str, domain: str) -> Optional[str]:
    """E-Mail-Adresse <token>@<domain> → token. Plus-Adressing-tolerant."""
    if not addr or "@" not in addr:
        return None
    local, dom = addr.rsplit("@", 1)
    if dom.lower() != domain.lower():
        return None
    m = _TOKEN_LOCAL_RE.match(local)
    return m.group(1) if m else None


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
    """
    s = get_settings()
    if not s.mailtest_imap_host or not s.mailtest_domain:
        log.debug("mailtest: not configured (host=%r domain=%r)",
                  s.mailtest_imap_host, s.mailtest_domain)
        return {"status": "not_configured"}

    summary = {"checked": 0, "matched": 0, "skipped": 0, "errors": 0}

    try:
        from imap_tools import AND, MailBox, MailBoxUnencrypted
    except ImportError:
        log.warning("mailtest: imap-tools not installed")
        return {"status": "imap_tools_missing"}

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

            # Cleanup-Pass
            _expire_old_tests(db)

    except Exception as e:  # noqa: BLE001
        log.warning("mailtest: poll failed: %s", e, exc_info=True)
        summary["errors"] += 1

    return summary
