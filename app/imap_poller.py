"""Poll configured mailboxes via IMAP and ingest aggregate reports."""
from __future__ import annotations

import imaplib
import logging
import threading
from datetime import datetime, timezone

from imap_tools import AND, OR, MailBox, MailBoxUnencrypted
from sqlalchemy import select

from .database import session_scope
from .ingest import ingest_payload
from .models import Mailbox
from .security import decrypt_secret

log = logging.getLogger(__name__)

ATTACH_EXTS = (".zip", ".gz", ".xml")
MAX_FETCH_PER_POLL = 100   # hard cap so a slow IMAP doesn't block forever
_in_flight: set[int] = set()
_lock = threading.Lock()


def _is_dmarc_attachment(filename: str | None) -> bool:
    if not filename:
        return False
    lower = filename.lower()
    return lower.endswith(ATTACH_EXTS)


_DMARC_CONTENT_TYPES = {
    "application/zip", "application/x-zip", "application/x-zip-compressed",
    "application/gzip", "application/x-gzip",
    "application/xml", "text/xml",
}


def _extract_attachments(msg) -> list[tuple[str, bytes]]:
    """Return [(filename, bytes), …] for every attachment-like part.

    Handles both:
    - normal multipart mails (text body + attachment parts)
    - single-part mails where the entire body IS the attachment
      (Google sometimes ships DMARC reports this way: Content-Type: application/zip
      with Content-Disposition: attachment at the top level, no multipart wrapper)
    """
    out: list[tuple[str, bytes]] = []
    raw = getattr(msg, "obj", None)
    if raw is None:
        # Fallback for older imap-tools versions
        for att in getattr(msg, "attachments", []) or []:
            out.append((att.filename, att.payload))
        return out

    for part in raw.walk():
        if part.is_multipart():
            continue
        cd = (part.get("Content-Disposition") or "").lower()
        ct = (part.get_content_type() or "").lower()
        fn = part.get_filename()
        looks_like_dmarc = ct in _DMARC_CONTENT_TYPES or _is_dmarc_attachment(fn)
        if "attachment" in cd or looks_like_dmarc:
            payload = part.get_payload(decode=True)
            if payload:
                # If filename is missing but content-type matches, fabricate one
                if not fn:
                    if "zip" in ct: fn = "report.zip"
                    elif "gzip" in ct: fn = "report.xml.gz"
                    elif "xml" in ct: fn = "report.xml"
                    else: fn = "report.bin"
                out.append((fn, payload))
    return out


def _friendly_login_error(mb: Mailbox, exc: Exception) -> str:
    """Translate raw IMAP error strings into actionable messages."""
    raw = str(exc)
    low = raw.lower()
    host = (mb.host or "").lower()

    if "application-specific password required" in low or "185833" in raw:
        return ("Gmail braucht ein App-Passwort, kein normales Passwort. "
                "→ https://support.google.com/accounts/answer/185833 "
                "(2FA aktivieren, dann App-Passwort generieren).")
    if "authenticationfailed" in low.replace(" ", "") or "auth failed" in low or "invalid credentials" in low:
        return f"Anmeldung fehlgeschlagen — Benutzername oder Passwort falsch. ({raw[:120]})"
    if "imap is disabled" in low or "imap access is disabled" in low or ("imap" in low and "not enabled" in low):
        return ("IMAP ist beim Mail-Anbieter nicht aktiviert. "
                "Bei Gmail/Workspace: in den Einstellungen 'IMAP-Zugriff aktivieren'.")
    if "timeout" in low or "timed out" in low:
        return f"Verbindung zu {mb.host}:{mb.port} hat zu lange gedauert. Firewall? Falscher Host?"
    if "name or service not known" in low or "nodename nor servname" in low or "getaddrinfo" in low:
        return f"Host {mb.host!r} ließ sich nicht auflösen. Tippfehler im Host-Namen?"
    if "ssl" in low or "certificate" in low:
        return f"TLS/SSL-Problem ({raw[:120]}). Port und SSL-Toggle prüfen."
    if host.endswith("outlook.office365.com") and ("logindenied" in low.replace(" ", "") or "no" in low and "auth" in low):
        return ("Microsoft 365: Modern Auth ist Pflicht. App-Passwort erstellen oder Basic-Auth-Policy "
                "vom M365-Admin freischalten lassen.")
    return f"Login fehlgeschlagen: {raw[:200]}"


IMAP_TIMEOUT_S = 25


def _open_box(mb: Mailbox):
    pw = decrypt_secret(mb.password_encrypted) or ""
    if mb.use_ssl:
        return MailBox(mb.host, port=mb.port, timeout=IMAP_TIMEOUT_S).login(
            mb.username, pw, initial_folder=mb.folder)
    return MailBoxUnencrypted(mb.host, port=mb.port, timeout=IMAP_TIMEOUT_S).login(
        mb.username, pw, initial_folder=mb.folder)


def poll_mailbox(mailbox_id: int, *, rescan: bool = False, rescan_days: int = 90) -> dict:
    """Poll a single mailbox.

    Two modes:
    - Default (rescan=False): only NEW (unseen) mails matching subject filter.
      Marks them as seen so next poll skips them.
    - Rescan (rescan=True): all DMARC-looking mails from the last `rescan_days`,
      regardless of seen-flag. Does NOT toggle seen-flag (preserves user's
      read state in their inbox). Dedup happens at report level.
    """
    summary = {"mailbox_id": mailbox_id, "fetched": 0, "imported": 0, "duplicates": 0,
               "errors": 0, "ignored": 0, "rescan": rescan}

    with session_scope() as db:
        mb = db.get(Mailbox, mailbox_id)
        if not mb or not mb.enabled:
            summary["error"] = "mailbox disabled or missing"
            return summary

        try:
            box = _open_box(mb)
        except Exception as e:  # noqa: BLE001
            mb.last_error = _friendly_login_error(mb, e)
            mb.last_polled_at = datetime.now(timezone.utc)
            log.warning("Mailbox %s login failed: %s", mb.id, e)
            summary["error"] = mb.last_error
            return summary

        # Filter: only mails likely to be DMARC reports.
        # Subject usually contains "Report" (Google: "Report Domain: …",
        # MS/Yahoo: "Report-ID: …", others: "DMARC Aggregate Report").
        if rescan:
            from datetime import date, timedelta
            since = date.today() - timedelta(days=max(1, rescan_days))
            criteria = AND(subject="Report", date_gte=since)
            mark_seen = False
        else:
            criteria = AND(seen=False, subject="Report")
            mark_seen = True
        scanned = 0
        try:
            for msg in box.fetch(criteria=criteria, mark_seen=mark_seen, bulk=False):
                scanned += 1
                if scanned > MAX_FETCH_PER_POLL:
                    summary["truncated"] = True
                    break
                handled = False
                for filename, payload in _extract_attachments(msg):
                    if not _is_dmarc_attachment(filename):
                        continue
                    summary["fetched"] += 1
                    try:
                        results = ingest_payload(
                            db,
                            filename or "report",
                            payload,
                            tenant_id=mb.tenant_id,
                            reseller_id=mb.reseller_id,
                            auto_create_domain=False,
                            source="imap",
                        )
                        for r in results:
                            if r.status == "ok":
                                summary["imported"] += 1
                            elif r.status == "dup":
                                summary["duplicates"] += 1
                            elif r.status == "ignored":
                                summary["ignored"] += 1
                            else:
                                summary["errors"] += 1
                        handled = True
                    except Exception as e:  # noqa: BLE001
                        summary["errors"] += 1
                        log.exception("Failed to ingest %s: %s", filename, e)
                if handled and mb.move_to_folder:
                    try:
                        box.move(msg.uid, mb.move_to_folder)
                    except Exception as e:  # noqa: BLE001
                        log.warning("Could not move message %s: %s", msg.uid, e)
            # All-or-partial success: clear stale errors
            if summary.get("truncated"):
                mb.last_error = (f"Hard-Limit erreicht ({MAX_FETCH_PER_POLL} Mails/Poll). "
                                  "Weitere kommen beim nächsten Lauf.")
            else:
                mb.last_error = None
        except (imaplib.IMAP4.abort, imaplib.IMAP4.error) as e:
            # Server kicked us during fetch — keep what we already imported
            mb.last_error = f"IMAP-Server brach Verbindung ab: {e}. Importiert: {summary['imported']}, abgebrochen nach {scanned} Mails."
            log.warning("IMAP abort on mailbox %s after %s scanned: %s", mb.id, scanned, e)
        except Exception as e:  # noqa: BLE001
            mb.last_error = f"poll failed: {e}"
            log.exception("Poll failed for mailbox %s", mb.id)
            summary["error"] = mb.last_error
        finally:
            mb.last_polled_at = datetime.now(timezone.utc)
            try:
                box.logout()
            except Exception:  # noqa: BLE001
                pass

    return summary


def poll_in_background(mailbox_id: int, *, rescan: bool = False, rescan_days: int = 90) -> bool:
    """Spawn a daemon thread to poll the mailbox. Returns False if a poll for
    this mailbox is already in flight."""
    with _lock:
        if mailbox_id in _in_flight:
            return False
        _in_flight.add(mailbox_id)

    def _run():
        try:
            poll_mailbox(mailbox_id, rescan=rescan, rescan_days=rescan_days)
        finally:
            with _lock:
                _in_flight.discard(mailbox_id)

    threading.Thread(target=_run, daemon=True).start()
    return True


def is_polling(mailbox_id: int) -> bool:
    with _lock:
        return mailbox_id in _in_flight


def poll_all_enabled() -> list[dict]:
    with session_scope() as db:
        ids = db.execute(select(Mailbox.id).where(Mailbox.enabled.is_(True))).scalars().all()
    return [poll_mailbox(mid) for mid in ids]
