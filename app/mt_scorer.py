"""Mail-Tester Score-Engine.

Eingang: rohes RFC822-Mime aus der Catch-All-Inbox.
Ausgang: Score (0..10) + strukturiertes Breakdown.

Wir nehmen so viel wie moeglich aus Headern die Mailcow's rspamd schon setzt
(Authentication-Results, X-Spam-Score, X-Rspamd-Score). Eigene Checks dazu:
PTR / TLS aus Received-Header / DNSBL-Lookup via Spamhaus.
"""
from __future__ import annotations

import email
import json
import logging
import re
from dataclasses import asdict, dataclass, field
from email.message import Message
from email.utils import getaddresses, parseaddr
from typing import Optional

log = logging.getLogger(__name__)


# ============================================================================
# Result-Datenklassen
# ============================================================================


@dataclass
class CheckResult:
    key: str          # "spf", "dkim", "dmarc", ...
    label: str        # "SPF-Authentifizierung"
    status: str       # "pass" | "fail" | "warn" | "neutral" | "skip"
    score: float      # Beitrag zum Gesamtscore (kann negativ sein, weighted)
    max_score: float  # Maximaler Beitrag wenn alles perfekt
    detail: str       # human-readable Erklaerung
    fix_hint: Optional[str] = None  # was tun um's zu reparieren


@dataclass
class ScoreBreakdown:
    total: float            # 0.0 - 10.0
    checks: list[CheckResult] = field(default_factory=list)
    sender_email: Optional[str] = None
    sender_ip: Optional[str] = None
    sender_domain: Optional[str] = None
    subject: Optional[str] = None
    received_at_utc: Optional[str] = None

    def to_json(self) -> str:
        return json.dumps({
            "total": round(self.total, 2),
            "checks": [asdict(c) for c in self.checks],
            "sender_email": self.sender_email,
            "sender_ip": self.sender_ip,
            "sender_domain": self.sender_domain,
            "subject": self.subject,
            "received_at_utc": self.received_at_utc,
        }, ensure_ascii=False)


# ============================================================================
# Header-Parser
# ============================================================================


def _get_first(msg: Message, name: str) -> str:
    v = msg.get(name)
    return (v or "").strip()


_AR_KV = re.compile(r"([a-z][a-z0-9-]*)=([A-Za-z0-9_.-]+)")


def _parse_authentication_results(headers: list[str]) -> dict[str, str]:
    """Authentication-Results-Header parsen: returns dict {'spf': 'pass', 'dkim': 'pass', 'dmarc': 'pass'}.
    Nimmt den ersten AR-Header der vom eigenen Server stammt (top of stack).
    """
    out: dict[str, str] = {}
    for h in headers:
        # Format: "auth-serv.example.com; spf=pass smtp.mailfrom=...; dkim=pass header.d=...; dmarc=pass policy.dmarc=none"
        for m in _AR_KV.finditer(h):
            key, val = m.group(1).lower(), m.group(2).lower()
            if key in ("spf", "dkim", "dmarc") and key not in out:
                out[key] = val
    return out


_IP_RE = re.compile(r"\[?(\d{1,3}(?:\.\d{1,3}){3})\]?|\[?([0-9a-fA-F:]+)\]?")
_TLS_RE = re.compile(r"\(using ([A-Za-z0-9.-]+)\)|\(version=([A-Za-z0-9.-]+)\s+cipher", re.IGNORECASE)


def _extract_sender_ip(received_headers: list[str]) -> Optional[str]:
    """Aus dem aeltesten Received-Header (am Ende der Liste) die externe IP rausziehen."""
    if not received_headers:
        return None
    # Letzter Header = erster Hop (Sender). Suche nach erster IPv4/IPv6, die nicht privat ist.
    last = received_headers[-1]
    for m in _IP_RE.finditer(last):
        ip = m.group(1) or m.group(2)
        if not ip:
            continue
        # private/loopback skippen
        if ip.startswith(("127.", "10.", "192.168.")) or ip == "::1":
            continue
        if ip.startswith("172."):
            parts = ip.split(".")
            if len(parts) >= 2 and 16 <= int(parts[1]) <= 31:
                continue
        return ip
    return None


def _extract_tls(received_headers: list[str]) -> Optional[str]:
    """TLS-Version aus dem letzten 'from'-hop -- das ist unser eigener MX."""
    if not received_headers:
        return None
    first_hop = received_headers[0]  # newest = unsere Annahme
    m = _TLS_RE.search(first_hop)
    if m:
        return (m.group(1) or m.group(2) or "").upper()
    return None


def _reverse_dns(ip: str) -> Optional[str]:
    if not ip:
        return None
    try:
        import dns.resolver, dns.reversename
        rev = dns.reversename.from_address(ip)
        r = dns.resolver.Resolver(configure=False)
        r.nameservers = ["1.1.1.1", "8.8.8.8"]
        r.lifetime = 2.0
        r.timeout = 1.5
        ans = r.resolve(rev, "PTR", lifetime=2.0)
        return str(ans[0]).rstrip(".")
    except Exception:  # noqa: BLE001
        return None


def _spamhaus_listed(ip: str) -> tuple[bool, str]:
    """Best-effort DNSBL-Check via existing blacklist-Module. Returns (listed, info)."""
    if not ip or ":" in ip:  # IPv6 skip for MVP
        return False, "skipped (IPv6)"
    try:
        from .blacklist import check_ip
        hits = check_ip(ip)
        if hits:
            return True, ", ".join(h.get("name") or h.get("zone") or "?" for h in hits)
        return False, "clean"
    except Exception as e:  # noqa: BLE001
        log.debug("DNSBL check failed: %s", e)
        return False, "check failed"


# ============================================================================
# Score-Engine
# ============================================================================


# Wichtung je Check (Summe = 10.0)
_WEIGHTS = {
    "spf":            1.5,
    "dkim":           1.5,
    "dmarc":          1.5,
    "ptr":            1.0,
    "tls":            0.8,
    "dnsbl":          1.0,
    "rspamd":         1.5,   # Mailcow's rspamd-Score, falls vorhanden
    "list_unsub":     0.5,
    "subject_caps":   0.3,
    "html_text":      0.4,
}


def score_email(raw_email: str) -> ScoreBreakdown:
    """Score eine RFC822-Mail. Gibt strukturiertes Breakdown zurueck."""
    msg = email.message_from_string(raw_email)
    breakdown = ScoreBreakdown(total=0.0)

    # Basis-Felder
    breakdown.subject = _get_first(msg, "Subject") or None
    from_addr = parseaddr(_get_first(msg, "From"))[1] or None
    breakdown.sender_email = from_addr
    if from_addr and "@" in from_addr:
        breakdown.sender_domain = from_addr.rsplit("@", 1)[1].lower()

    received_headers = msg.get_all("Received") or []
    breakdown.sender_ip = _extract_sender_ip(received_headers)

    # 1) SPF/DKIM/DMARC aus Authentication-Results (rspamd setzt die)
    ar_headers = msg.get_all("Authentication-Results") or []
    ar = _parse_authentication_results(ar_headers)

    for key, label in (("spf", "SPF-Authentifizierung"),
                        ("dkim", "DKIM-Signatur"),
                        ("dmarc", "DMARC-Policy")):
        max_s = _WEIGHTS[key]
        v = ar.get(key, "")
        if v == "pass":
            breakdown.checks.append(CheckResult(
                key=key, label=label, status="pass", score=max_s, max_score=max_s,
                detail=f"{label} = pass",
            ))
        elif v in ("fail", "softfail", "permerror", "temperror"):
            breakdown.checks.append(CheckResult(
                key=key, label=label, status="fail", score=0.0, max_score=max_s,
                detail=f"{label} = {v}",
                fix_hint=_FIX_HINTS.get(key, "Prüfe deinen DNS-Record."),
            ))
        elif v in ("neutral", "none", "policy"):
            breakdown.checks.append(CheckResult(
                key=key, label=label, status="warn", score=max_s * 0.4, max_score=max_s,
                detail=f"{label} = {v} (kein vollständiger Schutz)",
                fix_hint=_FIX_HINTS.get(key),
            ))
        else:
            breakdown.checks.append(CheckResult(
                key=key, label=label, status="warn", score=max_s * 0.3, max_score=max_s,
                detail=f"{label}-Status unbekannt (Header fehlt)",
                fix_hint="Der empfangende Server konnte deinen Record nicht auswerten.",
            ))

    # 2) Reverse-DNS (PTR) der Sender-IP
    if breakdown.sender_ip:
        ptr = _reverse_dns(breakdown.sender_ip)
        max_s = _WEIGHTS["ptr"]
        if ptr:
            breakdown.checks.append(CheckResult(
                key="ptr", label="Reverse-DNS (PTR)", status="pass",
                score=max_s, max_score=max_s,
                detail=f"{breakdown.sender_ip} → {ptr}",
            ))
        else:
            breakdown.checks.append(CheckResult(
                key="ptr", label="Reverse-DNS (PTR)", status="fail",
                score=0.0, max_score=max_s,
                detail=f"{breakdown.sender_ip} hat keinen PTR-Eintrag",
                fix_hint="Bitte deinen Hosting-Provider um einen PTR-Record (rDNS) auf deinen Mailserver-Hostname.",
            ))

    # 3) TLS-Hop
    tls = _extract_tls(received_headers)
    max_s = _WEIGHTS["tls"]
    if tls and tls.startswith("TLS"):
        breakdown.checks.append(CheckResult(
            key="tls", label="Transport-Verschlüsselung", status="pass",
            score=max_s, max_score=max_s,
            detail=f"{tls}",
        ))
    else:
        breakdown.checks.append(CheckResult(
            key="tls", label="Transport-Verschlüsselung", status="warn",
            score=max_s * 0.3, max_score=max_s,
            detail="TLS-Version aus Received-Header nicht eindeutig lesbar",
        ))

    # 4) DNSBL (Spamhaus)
    if breakdown.sender_ip:
        listed, info = _spamhaus_listed(breakdown.sender_ip)
        max_s = _WEIGHTS["dnsbl"]
        if not listed:
            breakdown.checks.append(CheckResult(
                key="dnsbl", label="Blacklist-Check", status="pass",
                score=max_s, max_score=max_s,
                detail=f"IP nicht gelistet ({info})",
            ))
        else:
            breakdown.checks.append(CheckResult(
                key="dnsbl", label="Blacklist-Check", status="fail",
                score=0.0, max_score=max_s,
                detail=f"IP ist gelistet bei: {info}",
                fix_hint="Delisting bei Spamhaus beantragen. Vorher Ursache klären (kompromittierter Account? offener Relay?).",
            ))

    # 5) rspamd-Score aus dem Header (Mailcow setzt ihn)
    rspamd_score_str = (
        _get_first(msg, "X-Spam-Score") or
        _get_first(msg, "X-Rspamd-Score") or
        ""
    ).strip().rstrip(",")
    max_s = _WEIGHTS["rspamd"]
    try:
        rs = float(rspamd_score_str) if rspamd_score_str else None
    except ValueError:
        rs = None
    if rs is not None:
        # rspamd: niedriger = besser. Negativ = "harmlos". > 5 = wahrscheinlich Spam.
        if rs < 0:
            pct = 1.0
        elif rs < 3:
            pct = max(0.4, 1.0 - rs / 5)
        elif rs < 6:
            pct = max(0.1, 0.4 - (rs - 3) / 10)
        else:
            pct = 0.0
        status = "pass" if pct > 0.8 else "warn" if pct > 0.4 else "fail"
        breakdown.checks.append(CheckResult(
            key="rspamd", label="Spam-Score (rspamd)", status=status,
            score=max_s * pct, max_score=max_s,
            detail=f"rspamd-Score: {rs:+.2f} (niedriger = besser)",
        ))

    # 6) List-Unsubscribe-Header
    max_s = _WEIGHTS["list_unsub"]
    if msg.get("List-Unsubscribe"):
        breakdown.checks.append(CheckResult(
            key="list_unsub", label="List-Unsubscribe-Header", status="pass",
            score=max_s, max_score=max_s,
            detail="Vorhanden",
        ))
    else:
        breakdown.checks.append(CheckResult(
            key="list_unsub", label="List-Unsubscribe-Header", status="warn",
            score=max_s * 0.3, max_score=max_s,
            detail="Fehlt — Gmail/Outlook verlangen ihn seit 2024 bei Bulk-Mail",
            fix_hint="<code>List-Unsubscribe: &lt;mailto:unsub@…&gt;</code> + <code>List-Unsubscribe-Post: List-Unsubscribe=One-Click</code>",
        ))

    # 7) Subject all-caps?
    max_s = _WEIGHTS["subject_caps"]
    subj = breakdown.subject or ""
    letters = [c for c in subj if c.isalpha()]
    caps_ratio = (sum(c.isupper() for c in letters) / len(letters)) if letters else 0
    if caps_ratio < 0.5 or len(letters) < 6:
        breakdown.checks.append(CheckResult(
            key="subject_caps", label="Subject-Lesbarkeit", status="pass",
            score=max_s, max_score=max_s,
            detail="Keine ALL-CAPS-Aggression",
        ))
    else:
        breakdown.checks.append(CheckResult(
            key="subject_caps", label="Subject-Lesbarkeit", status="warn",
            score=0.0, max_score=max_s,
            detail=f"{int(caps_ratio*100)}% Großbuchstaben im Subject",
            fix_hint="Subject in normaler Schreibweise — All-Caps triggert Spamfilter.",
        ))

    # 8) HTML/Text-Ratio
    max_s = _WEIGHTS["html_text"]
    has_html = False
    has_text = False
    for part in msg.walk():
        ct = part.get_content_type()
        if ct == "text/html": has_html = True
        if ct == "text/plain": has_text = True
    if has_html and has_text:
        breakdown.checks.append(CheckResult(
            key="html_text", label="HTML + Plain-Text-Variante", status="pass",
            score=max_s, max_score=max_s,
            detail="Multipart/Alternative mit beidem",
        ))
    elif has_text and not has_html:
        breakdown.checks.append(CheckResult(
            key="html_text", label="HTML + Plain-Text-Variante", status="pass",
            score=max_s * 0.8, max_score=max_s,
            detail="Plain-Text-Only — minimalistisch, immer ok",
        ))
    else:
        breakdown.checks.append(CheckResult(
            key="html_text", label="HTML + Plain-Text-Variante", status="warn",
            score=0.0, max_score=max_s,
            detail="Nur HTML, kein Plain-Text-Fallback",
            fix_hint="Sende immer beides: multipart/alternative mit text/plain UND text/html.",
        ))

    breakdown.total = round(sum(c.score for c in breakdown.checks), 2)
    if breakdown.total > 10.0:
        breakdown.total = 10.0
    return breakdown


_FIX_HINTS = {
    "spf": "Setze einen TXT-Record auf deiner Domain mit <code>v=spf1 ... ~all</code> (alle deine Sender authorisiert).",
    "dkim": "Erstelle ein DKIM-Schlüsselpaar im Mail-Anbieter, veröffentliche den Public-Key als TXT auf <code>selector._domainkey.deine-domain</code>.",
    "dmarc": "Setze <code>_dmarc.deine-domain TXT \"v=DMARC1; p=none; rua=mailto:reports@deine-domain\"</code>.",
}
