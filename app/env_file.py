"""Read/write the .env file idempotently while preserving comments + ordering.

Writes are atomic: produce a temp file, then rename. Sensitive keys are masked
when read back for display.
"""
from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path
from typing import Iterable, Optional

# Anything containing one of these substrings is masked when displayed.
_SENSITIVE_PATTERNS = (
    "PASSWORD", "PASSWD", "SECRET", "FERNET_KEY", "TOKEN", "API_KEY",
)

# Keys we expose in the admin UI, in display order. Only these are writable
# from the panel. Each entry: (env_key, label, group, hint, kind)
#   kind: text | number | bool | password | secret | url | email
EDITABLE_FIELDS: list[dict] = [
    # ----- App -----
    {"key": "BASE_URL", "label": "Public Base-URL", "group": "App",
     "hint": "Wird in Reset-Mails, Signup-Links und Webhooks verwendet. Inkl. https:// und ohne Trailing-Slash.",
     "kind": "url"},
    {"key": "DEFAULT_TENANT_NAME", "label": "Default-Tenant-Name", "group": "App",
     "hint": "Name des Bootstrap-Tenants beim ersten Start.", "kind": "text"},
    {"key": "ALLOW_SIGNUP", "label": "Self-Signup erlaubt?", "group": "App",
     "hint": "Wenn false: nur Reseller-Admins oder Superadmins können neue Tenants/User anlegen.",
     "kind": "bool"},
    {"key": "COOKIE_SECURE", "label": "Cookies nur über HTTPS", "group": "App",
     "hint": "Auf true setzen, sobald die App hinter HTTPS läuft.", "kind": "bool"},
    {"key": "TRUSTED_PROXIES", "label": "ProxyHeaders auswerten", "group": "App",
     "hint": "True wenn ein Reverse-Proxy (Caddy, nginx, Traefik) X-Forwarded-* Header setzt.",
     "kind": "bool"},
    {"key": "DEBUG_TRACEBACK", "label": "Stacktrace bei 500 anzeigen", "group": "App",
     "hint": "Wenn aktiv, rendert die App bei einem internen Fehler den vollen Python-Stacktrace direkt im Browser statt nur „Da ist etwas schiefgelaufen“. <strong>Nur in Dev/Staging anlassen</strong> — gibt internals + ggf. Pfade preis. Default: aus.",
     "kind": "bool"},

    # ----- Database -----
    {"key": "DATABASE_URL", "label": "Database-URL", "group": "Datenbank",
     "hint": "SQLAlchemy-URL. Beispiele: sqlite:///./dmarc.db · postgresql+psycopg://user:pass@host/db",
     "kind": "secret"},

    # ----- Auth / Security -----
    {"key": "SECRET_KEY", "label": "Secret-Key", "group": "Sicherheit",
     "hint": "Session- und Token-Signing. Random 64+ chars. Tippe ein neuer Wert nur, wenn du wirklich rotieren willst — Sessions werden invalidiert.",
     "kind": "secret"},
    {"key": "FERNET_KEY", "label": "Fernet-Key", "group": "Sicherheit",
     "hint": "Verschlüsselt IMAP-Passwörter. Rotation invalidiert ALLE gespeicherten Mailbox-Credentials.",
     "kind": "secret"},
    {"key": "SUPERADMIN_EMAIL", "label": "Superadmin-Email", "group": "Sicherheit",
     "hint": "Erst-Bootstrap-Admin. Nach Anlage des Users hat das Feld nur noch dokumentarischen Charakter.",
     "kind": "email"},
    {"key": "SUPERADMIN_PASSWORD", "label": "Superadmin-Passwort (Bootstrap)", "group": "Sicherheit",
     "hint": "Nur beim ersten Start verwendet. Spätere Passwort-Änderungen über die App, nicht hier.",
     "kind": "password"},

    # ----- IMAP / DMARC -----
    {"key": "IMAP_POLL_INTERVAL_MINUTES", "label": "IMAP-Poll-Intervall (Minuten)", "group": "DMARC-Polling",
     "hint": "Wie oft der Scheduler IMAP-Postfächer auf neue Reports prüft.",
     "kind": "number"},
    {"key": "RESOLVE_PTR", "label": "PTR-Lookup für Quell-IPs", "group": "DMARC-Polling",
     "hint": "Reverse-DNS für jede einzelne Quell-IP. Macht Auswertungen lesbarer, kostet etwas Performance.",
     "kind": "bool"},
    {"key": "SPAMHAUS_DQS_KEY", "label": "Spamhaus DQS-Auth-Code", "group": "Blacklist-Monitoring",
     "hint": "Spamhaus' offizieller <strong>Data Query Service</strong>-Key. Kostenlos für non-commercial Nutzung bis 100k Queries/Tag, kommerziell ab Volumen-Plan. Mit Key gehen Spamhaus-Lookups über <code>&lt;key&gt;.zen.dq.spamhaus.net</code> statt der rate-limited Public-Zone — keine NXDOMAIN-Fluctuations mehr. Account: <a href='https://www.spamhaus.com/product/data-query-service/' target='_blank'>spamhaus.com/product/data-query-service</a>.",
     "kind": "secret"},
    {"key": "DNSBL_STABILITY_THRESHOLD", "label": "Stability-Threshold für Alerts", "group": "Blacklist-Monitoring",
     "hint": "Anti-Flapping: nur als „gelistet“ werten wenn <strong>N aufeinander folgende Checks</strong> die gleiche Listung zeigen. <code>1</code> = sofort alarmieren (alte Logik), <code>2</code> = nur wenn 2x in Folge gelistet (Default, empfohlen). Schützt vor One-off-Rate-Limit-Antworten.",
     "kind": "number"},
    {"key": "HETZNER_DNS_TOKEN", "label": "Hetzner DNS API-Token", "group": "Managed DMARC (Hetzner DNS)",
     "hint": "Aktiviert <strong>DMARC-as-a-Service</strong>: Auto-Authorization-Records (für RUA-Reports an unsere Mailbox) und CNAME-Delegation (Kunde setzt einen CNAME, wir managen die Policy). Token erstellen: <a href='https://dns.hetzner.com/settings/api-token' target='_blank'>dns.hetzner.com/settings/api-token</a>.",
     "kind": "secret"},
    {"key": "HETZNER_DNS_ZONE", "label": "Managed Zone (FQDN)", "group": "Managed DMARC (Hetzner DNS)",
     "hint": "Die Zone in der wir Records anlegen, z.B. <code>dmarc-geeks.ch</code>. Muss bereits in Hetzner DNS existieren. Authorization-Records leben unter <code>&lt;kundedomain&gt;._report._dmarc.&lt;diese-zone&gt;</code>.",
     "kind": "text"},

    # ----- SMTP -----
    {"key": "SMTP_HOST", "label": "SMTP-Host", "group": "Mail-Versand",
     "hint": "Für Reset-Mails, Spike-Alerts, Weekly-Digest. Leer = Mail-Versand deaktiviert.",
     "kind": "text"},
    {"key": "SMTP_PORT", "label": "SMTP-Port", "group": "Mail-Versand",
     "hint": "587 (STARTTLS) oder 465 (TLS).", "kind": "number"},
    {"key": "SMTP_USER", "label": "SMTP-User", "group": "Mail-Versand",
     "hint": "Login-Username beim SMTP-Server.", "kind": "text"},
    {"key": "SMTP_PASSWORD", "label": "SMTP-Passwort", "group": "Mail-Versand",
     "hint": "Wird beim Speichern verschlüsselt in .env abgelegt.", "kind": "password"},
    {"key": "SMTP_USE_TLS", "label": "STARTTLS verwenden", "group": "Mail-Versand",
     "hint": "Standard true für Port 587, false bei Port 465 (impliziter TLS).", "kind": "bool"},
    {"key": "SMTP_TLS_VERIFY", "label": "TLS-Zertifikat prüfen", "group": "Mail-Versand",
     "hint": "Standard an. Auf <strong>aus</strong> setzen wenn dein Mail-Provider ein selbst-signiertes Zertifikat hat (typisch bei pc4play, kleinen Self-Hosted-Servern). Sicherheits-Trade-off: MITM-Angriffe sind dann möglich — nur in vertrauenswürdigen Netzen ausschalten.", "kind": "bool"},
    {"key": "SMTP_FROM", "label": "From-Adresse", "group": "Mail-Versand",
     "hint": "Absender für alle System-Mails.", "kind": "email"},
    {"key": "LEAD_NOTIFY_EMAILS", "label": "Lead-Mail Empfänger (zusätzlich)", "group": "Mail-Versand",
     "hint": "Komma-separierte Liste zusätzlicher Empfänger für <strong>Lead-Mails</strong> (Kontakt-Anfrage, Domain-Check in öffentlichen Tools). Beispiel: <code>nils@privat.ch, sales@firma.ch</code>. SMTP_FROM und SUPERADMIN_EMAIL bekommen die Lead-Mails sowieso.",
     "kind": "text"},

    # ----- Mail-Tester (mailtest.dmarc-geeks.ch) -----
    {"key": "MAILTEST_DOMAIN", "label": "Mail-Tester Domain", "group": "Mail-Tester",
     "hint": "Domain unter der wir Test-Adressen vergeben. Beispiel: <code>mailtest.dmarc-geeks.ch</code>. Mailcow muss einen Catch-All auf diese Domain haben.",
     "kind": "text"},
    {"key": "MAILTEST_IMAP_HOST", "label": "IMAP-Host", "group": "Mail-Tester",
     "hint": "Mailcow-Hostname für die Catch-All-Mailbox.",
     "kind": "text"},
    {"key": "MAILTEST_IMAP_PORT", "label": "IMAP-Port", "group": "Mail-Tester",
     "hint": "993 (SSL) oder 143 (STARTTLS).",
     "kind": "number"},
    {"key": "MAILTEST_IMAP_USER", "label": "IMAP-User", "group": "Mail-Tester",
     "hint": "Username der Catch-All-Mailbox.",
     "kind": "text"},
    {"key": "MAILTEST_IMAP_PASSWORD", "label": "IMAP-Passwort", "group": "Mail-Tester",
     "hint": "Wird verschlüsselt in .env abgelegt.",
     "kind": "password"},
    {"key": "MAILTEST_IMAP_SSL", "label": "SSL/TLS verwenden", "group": "Mail-Tester",
     "hint": "True für Port 993 (Standard), false für 143.",
     "kind": "bool"},
    {"key": "MAILTEST_IMAP_FOLDER", "label": "IMAP-Folder", "group": "Mail-Tester",
     "hint": "Standard <code>INBOX</code>. Catch-All landet meist dort.",
     "kind": "text"},
    {"key": "MAILTEST_POLL_SECONDS", "label": "Poll-Intervall (Sekunden)", "group": "Mail-Tester",
     "hint": "Wie oft wir die Catch-All-Inbox pollen. Niedriger = schnelleres User-Feedback. 30s ist gut.",
     "kind": "number"},
    {"key": "MAILTEST_MAX_PER_IP_PER_DAY", "label": "Max. Tests pro IP pro Tag", "group": "Mail-Tester",
     "hint": "Anti-Spam-Limit für Anonyme. Eingeloggte User sind nicht limitiert.",
     "kind": "number"},
]


def _env_path() -> Path:
    """Locate .env file in repo root (parent of `app/` package)."""
    here = Path(__file__).resolve().parent
    return here.parent / ".env"


def is_sensitive(key: str) -> bool:
    return any(p in key.upper() for p in _SENSITIVE_PATTERNS)


def mask_value(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 4:
        return "•" * len(value)
    return value[:2] + "•" * min(8, len(value) - 4) + value[-2:]


def read_env(path: Optional[Path] = None) -> dict[str, str]:
    """Return dict of KEY=VALUE pairs. Comments and blank lines ignored."""
    p = path or _env_path()
    out: dict[str, str] = {}
    if not p.exists():
        return out
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        k, _, v = line.partition("=")
        k = k.strip()
        v = v.strip()
        # strip surrounding quotes if present
        if (v.startswith('"') and v.endswith('"')) or (v.startswith("'") and v.endswith("'")):
            v = v[1:-1]
        out[k] = v
    return out


def write_env(updates: dict[str, str], path: Optional[Path] = None) -> dict:
    """Apply `updates` to .env file. Returns dict with `changed` keys list."""
    p = path or _env_path()
    p.parent.mkdir(parents=True, exist_ok=True)

    existing_lines: list[str] = []
    if p.exists():
        existing_lines = p.read_text(encoding="utf-8").splitlines()

    seen_keys: set[str] = set()
    new_lines: list[str] = []
    changed: list[str] = []

    # Re-emit existing lines, replacing any keys present in `updates`
    for line in existing_lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            new_lines.append(line)
            continue
        if "=" not in stripped:
            new_lines.append(line)
            continue
        k = stripped.split("=", 1)[0].strip()
        if k in updates:
            new_value = updates[k]
            old_value = stripped.split("=", 1)[1].strip()
            # strip quotes for comparison
            if (old_value.startswith('"') and old_value.endswith('"')) or \
               (old_value.startswith("'") and old_value.endswith("'")):
                old_value = old_value[1:-1]
            if old_value != new_value:
                changed.append(k)
            new_lines.append(f"{k}={new_value}")
            seen_keys.add(k)
        else:
            new_lines.append(line)

    # Append keys that didn't exist before
    appended = []
    for k, v in updates.items():
        if k not in seen_keys:
            appended.append(f"{k}={v}")
            changed.append(k)

    if appended:
        if new_lines and new_lines[-1].strip():
            new_lines.append("")
        new_lines.extend(appended)

    final_text = "\n".join(new_lines)
    if final_text and not final_text.endswith("\n"):
        final_text += "\n"

    # Atomic write: temp + rename. Faellt zurueck auf in-place-write wenn
    # die Ziel-Datei ein bind-mount ist (Docker single-file mount kann nicht
    # via rename() ersetzt werden -> "Device or resource busy").
    fd, tmp = tempfile.mkstemp(dir=str(p.parent), prefix=".env.", suffix=".tmp", text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(final_text)
        try:
            os.replace(tmp, p)
        except OSError:
            # bind-mounted target -> write in place, dann tmp loeschen
            p.write_text(final_text, encoding="utf-8")
            try: os.unlink(tmp)
            except OSError: pass
    except Exception:
        try: os.unlink(tmp)
        except OSError: pass
        raise

    return {"changed": changed, "path": str(p)}
