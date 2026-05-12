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
    # Optional: tatsächlicher DNS-Record (SPF/DKIM/DMARC) oder andere Roh-Daten
    # zum Anzeigen im Detail-View (mail-tester.com-Style — "we retained X as
    # your current SPF record")
    raw_evidence: Optional[str] = None


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
# DNS-Lookups fuer Detail-Anreicherung der Auth-Checks
# (analog zu mail-tester.com: "What we retained as your current SPF record is")
# ============================================================================


def _resolver():
    import dns.resolver
    r = dns.resolver.Resolver(configure=False)
    r.nameservers = ["1.1.1.1", "8.8.8.8"]
    r.lifetime = 3.0
    r.timeout = 2.5
    return r


def _txt_records(domain: str) -> list[str]:
    try:
        ans = _resolver().resolve(domain, "TXT")
        out = []
        for r in ans:
            chunks = [b.decode("utf-8", errors="replace") for b in r.strings]
            out.append("".join(chunks))
        return out
    except Exception:  # noqa: BLE001
        return []


def _mx_records(domain: str) -> list[tuple[int, str]]:
    try:
        ans = _resolver().resolve(domain, "MX")
        return [(int(r.preference), str(r.exchange).rstrip(".")) for r in ans]
    except Exception:  # noqa: BLE001
        return []


def _a_record(host: str) -> Optional[str]:
    try:
        ans = _resolver().resolve(host, "A")
        return str(ans[0]) if ans else None
    except Exception:  # noqa: BLE001
        return None


def _fetch_spf_record(domain: str) -> Optional[str]:
    for t in _txt_records(domain):
        if t.lower().startswith("v=spf1"):
            return t
    return None


def _fetch_dmarc_record(domain: str) -> Optional[str]:
    for t in _txt_records(f"_dmarc.{domain}"):
        if t.lower().startswith("v=dmarc1"):
            return t
    return None


def _fetch_dkim_record(domain: str, selector: str) -> Optional[str]:
    """DKIM-Selector aus dem DKIM-Signature-Header verwenden."""
    for t in _txt_records(f"{selector}._domainkey.{domain}"):
        if t.lower().startswith("v=dkim1"):
            return t
    return None


_DKIM_SIG_RE = re.compile(r"\bd=([^;\s]+).*?\bs=([^;\s]+)", re.IGNORECASE | re.DOTALL)
_DKIM_KEYSIZE_RE = re.compile(r"\bp=([A-Za-z0-9+/=]+)")


def _parse_dkim_signature(sig: str) -> tuple[Optional[str], Optional[str]]:
    """Aus DKIM-Signature-Header die d= und s= rauslesen."""
    if not sig:
        return None, None
    m = _DKIM_SIG_RE.search(sig)
    return (m.group(1).strip(), m.group(2).strip()) if m else (None, None)


def _estimate_key_size(dkim_record: str) -> Optional[int]:
    """Aus DKIM-DNS-Record die public-key-Length schätzen.

    base64 → bytes → ~bit-count. Strip Whitespace + non-base64 chars."""
    m = _DKIM_KEYSIZE_RE.search(dkim_record or "")
    if not m:
        return None
    p = re.sub(r"[^A-Za-z0-9+/=]", "", m.group(1))
    if not p:
        return None
    try:
        import base64
        decoded = base64.b64decode(p)
        # RSA-Public-Key in DER: typische Längen
        # 1024-bit = ~140 bytes, 2048-bit = ~270 bytes, 4096-bit = ~530 bytes
        b = len(decoded)
        if b > 500:
            return 4096
        if b > 240:
            return 2048
        if b > 120:
            return 1024
        return b * 8  # rough estimate
    except Exception:  # noqa: BLE001
        return None


_HELO_RE = re.compile(r"\bfrom\s+([A-Za-z0-9.\-]+)", re.IGNORECASE)


def _extract_helo(received_headers: list[str]) -> Optional[str]:
    """HELO-Hostname aus dem letzten Received-Header (Sender-Hop)."""
    if not received_headers:
        return None
    last = received_headers[-1]
    m = _HELO_RE.search(last)
    return m.group(1).rstrip(".") if m else None


def _rdns_matches_sender(rdns: Optional[str], sender_domain: Optional[str],
                         helo: Optional[str]) -> tuple[bool, str]:
    """rDNS sollte die Sender-Domain oder HELO-Hostname enthalten.

    z.B. Mail von Mailcow mit Sender-Domain firma.ch:
      - rDNS mail.firma.ch  -> OK (enthält firma.ch)
      - rDNS amazon-ec2.compute -> nicht OK
      - rDNS outbound.protection.outlook.com bei M365-Sender helo
        ZR1P278CU001.outbound.protection.outlook.com -> OK (gleiche Suffix)
    """
    if not rdns:
        return False, "kein PTR"
    rdns_l = rdns.lower()
    sender_d = (sender_domain or "").lower()
    helo_d = (helo or "").lower()
    # Direkter Match auf Sender-Domain
    if sender_d and (rdns_l == sender_d or rdns_l.endswith("." + sender_d)):
        return True, f"rDNS '{rdns}' matcht Sender-Domain '{sender_domain}'"
    # Match auf HELO (z.B. M365: HELO = X.outbound.outlook.com, rDNS auch outlook.com)
    if helo_d:
        parts_helo = helo_d.split(".")
        if len(parts_helo) >= 2:
            helo_apex = ".".join(parts_helo[-2:])
            if rdns_l.endswith(helo_apex):
                return True, f"rDNS '{rdns}' matcht HELO-Domain '{helo_apex}'"
    return False, f"rDNS '{rdns}' passt nicht zu Sender ({sender_domain}) oder HELO ({helo or '?'})"


# ============================================================================
# Score-Engine
# ============================================================================


# Wichtung je Check (Summe ≈ 10.0). Manche Checks haben kleine Gewichte
# aber zeigen wichtige Info im Detail-View (z.B. dangerous_html).
_WEIGHTS = {
    "spf":            1.4,
    "dkim":           1.4,
    "dmarc":          1.4,
    "ptr":            0.7,
    "rdns_match":     0.4,   # rDNS-Domain matcht Sender? (mail-tester macht das)
    "tls":            0.6,
    "dnsbl":          0.8,
    "rspamd":         1.4,
    "list_unsub":     0.4,
    "subject_caps":   0.2,
    "html_text":      0.3,
    "html_dangerous": 0.3,   # JavaScript/iframe/embed in HTML → fail
    "html_alt":       0.2,   # Alle img-Tags haben alt
    "short_urls":     0.2,   # bit.ly / t.co etc → warn
    "sender_mx":      0.2,   # Sender-Domain hat MX
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

    # ============================================================================
    # 1) SPF — Authentication-Results + tatsächlicher DNS-Record
    # ============================================================================
    ar_headers = msg.get_all("Authentication-Results") or []
    ar = _parse_authentication_results(ar_headers)

    spf_record = _fetch_spf_record(breakdown.sender_domain) if breakdown.sender_domain else None
    max_s = _WEIGHTS["spf"]
    v = ar.get("spf", "")
    if v == "pass":
        breakdown.checks.append(CheckResult(
            key="spf", label="SPF-Authentifizierung", status="pass",
            score=max_s, max_score=max_s,
            detail=f"SPF = pass (Sender-IP {breakdown.sender_ip or '?'} ist im Record autorisiert)",
            raw_evidence=spf_record,
        ))
    elif v in ("fail", "softfail", "permerror", "temperror"):
        breakdown.checks.append(CheckResult(
            key="spf", label="SPF-Authentifizierung", status="fail",
            score=0.0, max_score=max_s,
            detail=f"SPF = {v}" + (f" — Sender-IP {breakdown.sender_ip} nicht im Record" if breakdown.sender_ip else ""),
            fix_hint=_FIX_HINTS.get("spf"),
            raw_evidence=spf_record,
        ))
    else:
        breakdown.checks.append(CheckResult(
            key="spf", label="SPF-Authentifizierung", status="warn",
            score=max_s * 0.3, max_score=max_s,
            detail=f"SPF-Status: {v or 'unbekannt'} (Authentication-Results-Header fehlt oder unklar)",
            fix_hint="Der empfangende Server konnte deinen SPF-Record nicht auswerten.",
            raw_evidence=spf_record,
        ))

    # ============================================================================
    # 2) DKIM — Signature-Header + DNS-Record + Key-Size
    # ============================================================================
    dkim_sig_header = _get_first(msg, "DKIM-Signature")
    dkim_d, dkim_s = _parse_dkim_signature(dkim_sig_header)
    dkim_record = None
    dkim_keysize = None
    if dkim_d and dkim_s:
        dkim_record = _fetch_dkim_record(dkim_d, dkim_s)
        if dkim_record:
            dkim_keysize = _estimate_key_size(dkim_record)

    max_s = _WEIGHTS["dkim"]
    v = ar.get("dkim", "")
    detail_parts = []
    if dkim_d and dkim_s:
        detail_parts.append(f"d={dkim_d}, s={dkim_s}")
    if dkim_keysize:
        detail_parts.append(f"{dkim_keysize}-bit RSA")
        if dkim_keysize < 2048:
            detail_parts.append("⚠ <2048-bit, modern empfohlen sind 2048+")

    if v == "pass":
        breakdown.checks.append(CheckResult(
            key="dkim", label="DKIM-Signatur", status="pass",
            score=max_s, max_score=max_s,
            detail="DKIM = pass · " + " · ".join(detail_parts) if detail_parts else "DKIM = pass",
            raw_evidence=dkim_record,
        ))
    elif v in ("fail", "softfail", "permerror", "temperror"):
        breakdown.checks.append(CheckResult(
            key="dkim", label="DKIM-Signatur", status="fail",
            score=0.0, max_score=max_s,
            detail=f"DKIM = {v}" + (" · " + " · ".join(detail_parts) if detail_parts else ""),
            fix_hint=_FIX_HINTS.get("dkim"),
            raw_evidence=dkim_record,
        ))
    elif dkim_sig_header:
        # Header da, aber kein Auth-Result -> wahrscheinlich nicht überprüft
        breakdown.checks.append(CheckResult(
            key="dkim", label="DKIM-Signatur", status="warn",
            score=max_s * 0.5, max_score=max_s,
            detail="DKIM-Signatur vorhanden aber nicht verifiziert · " + " · ".join(detail_parts),
            raw_evidence=dkim_record,
        ))
    else:
        breakdown.checks.append(CheckResult(
            key="dkim", label="DKIM-Signatur", status="fail",
            score=0.0, max_score=max_s,
            detail="Keine DKIM-Signatur in der Mail",
            fix_hint=_FIX_HINTS.get("dkim"),
        ))

    # ============================================================================
    # 3) DMARC — Authentication-Results + tatsächlicher DNS-Record + Policy-Anzeige
    # ============================================================================
    dmarc_record = _fetch_dmarc_record(breakdown.sender_domain) if breakdown.sender_domain else None
    dmarc_policy = None
    if dmarc_record:
        m = re.search(r"\bp=([a-z]+)", dmarc_record, re.IGNORECASE)
        if m:
            dmarc_policy = m.group(1).lower()

    max_s = _WEIGHTS["dmarc"]
    v = ar.get("dmarc", "")
    if v == "pass":
        pol_label = f" (Policy: <code>p={dmarc_policy}</code>)" if dmarc_policy else ""
        breakdown.checks.append(CheckResult(
            key="dmarc", label="DMARC-Policy", status="pass",
            score=max_s, max_score=max_s,
            detail=f"DMARC = pass{pol_label}",
            raw_evidence=dmarc_record,
        ))
    elif v in ("fail", "softfail", "permerror", "temperror"):
        breakdown.checks.append(CheckResult(
            key="dmarc", label="DMARC-Policy", status="fail",
            score=0.0, max_score=max_s,
            detail=f"DMARC = {v}",
            fix_hint=_FIX_HINTS.get("dmarc"),
            raw_evidence=dmarc_record,
        ))
    elif dmarc_record and dmarc_policy == "none":
        breakdown.checks.append(CheckResult(
            key="dmarc", label="DMARC-Policy", status="warn",
            score=max_s * 0.4, max_score=max_s,
            detail="DMARC-Record vorhanden aber Policy <code>p=none</code> — nur Beobachtungs-Modus, kein aktiver Schutz",
            fix_hint="Nach 2-4 Wochen Reports auf <code>p=quarantine</code> wechseln, später <code>p=reject</code>.",
            raw_evidence=dmarc_record,
        ))
    elif dmarc_record:
        breakdown.checks.append(CheckResult(
            key="dmarc", label="DMARC-Policy", status="warn",
            score=max_s * 0.5, max_score=max_s,
            detail=f"DMARC-Record vorhanden (p={dmarc_policy or '?'}) aber Auth-Result fehlt",
            raw_evidence=dmarc_record,
        ))
    else:
        breakdown.checks.append(CheckResult(
            key="dmarc", label="DMARC-Policy", status="fail",
            score=0.0, max_score=max_s,
            detail="Kein DMARC-Record für die Sender-Domain gefunden",
            fix_hint=_FIX_HINTS.get("dmarc"),
        ))

    # ============================================================================
    # 4) Reverse-DNS (PTR) der Sender-IP + Match-Check gegen Sender-Domain
    # ============================================================================
    ptr = None
    helo = _extract_helo(received_headers)
    if breakdown.sender_ip:
        ptr = _reverse_dns(breakdown.sender_ip)
        max_s = _WEIGHTS["ptr"]
        if ptr:
            breakdown.checks.append(CheckResult(
                key="ptr", label="Reverse-DNS (PTR)", status="pass",
                score=max_s, max_score=max_s,
                detail=f"{breakdown.sender_ip} → {ptr}",
                raw_evidence=f"IP: {breakdown.sender_ip}\nPTR: {ptr}\nHELO: {helo or '?'}",
            ))
        else:
            breakdown.checks.append(CheckResult(
                key="ptr", label="Reverse-DNS (PTR)", status="fail",
                score=0.0, max_score=max_s,
                detail=f"{breakdown.sender_ip} hat keinen PTR-Eintrag",
                fix_hint="Bei deinem Hosting-Provider einen PTR-Record (rDNS) auf den Mailserver-Hostname setzen.",
            ))

        # rDNS-Match: PTR sollte zur Sender-Domain oder HELO passen
        # (mail-tester.com warnt explizit wenn das nicht passt)
        max_s = _WEIGHTS["rdns_match"]
        matches, why = _rdns_matches_sender(ptr, breakdown.sender_domain, helo)
        if matches:
            breakdown.checks.append(CheckResult(
                key="rdns_match", label="rDNS-Domain-Match", status="pass",
                score=max_s, max_score=max_s,
                detail=why,
            ))
        elif ptr:
            breakdown.checks.append(CheckResult(
                key="rdns_match", label="rDNS-Domain-Match", status="warn",
                score=max_s * 0.3, max_score=max_s,
                detail=why,
                fix_hint="Sender-IP, PTR und HELO-Hostname sollten zur gleichen Domain gehören — sonst werten viele Filter das als Spoofing-Indiz.",
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

    # 8) HTML/Text-Ratio inkl. konkretem Prozentwert
    max_s = _WEIGHTS["html_text"]
    has_html = False
    has_text = False
    html_body = ""
    text_body = ""
    for part in msg.walk():
        ct = part.get_content_type()
        try:
            payload = part.get_payload(decode=True)
            body = payload.decode(part.get_content_charset() or "utf-8", errors="replace") if payload else ""
        except Exception:  # noqa: BLE001
            body = ""
        if ct == "text/html":
            has_html = True
            html_body += body
        elif ct == "text/plain":
            has_text = True
            text_body += body

    if has_html and has_text:
        # Text-Ratio: text-length / html-length (mail-tester macht das auch)
        ratio_pct = int(round(100 * len(text_body) / max(1, len(html_body))))
        if ratio_pct < 10:
            ratio_status = "warn"
            ratio_detail = f"Nur {ratio_pct}% Text vs HTML — Mailclients ohne HTML-Rendering bekommen fast nichts"
            ratio_score = max_s * 0.5
        else:
            ratio_status = "pass"
            ratio_detail = f"Multipart/Alternative · Text/HTML-Ratio {ratio_pct}%"
            ratio_score = max_s
        breakdown.checks.append(CheckResult(
            key="html_text", label="HTML + Plain-Text-Variante", status=ratio_status,
            score=ratio_score, max_score=max_s, detail=ratio_detail,
        ))
    elif has_text and not has_html:
        breakdown.checks.append(CheckResult(
            key="html_text", label="HTML + Plain-Text-Variante", status="pass",
            score=max_s * 0.8, max_score=max_s,
            detail="Plain-Text-Only — minimalistisch, immer OK",
        ))
    else:
        breakdown.checks.append(CheckResult(
            key="html_text", label="HTML + Plain-Text-Variante", status="warn",
            score=0.0, max_score=max_s,
            detail="Nur HTML, kein Plain-Text-Fallback",
            fix_hint="Sende immer beides: multipart/alternative mit text/plain UND text/html.",
        ))

    # ============================================================================
    # 9-11) HTML-Deep-Inspection: Dangerous-HTML, Image-ALT, Short-URLs
    # ============================================================================
    if html_body:
        # 9) Dangerous HTML: JavaScript, iframe, embed, object, form
        max_s = _WEIGHTS["html_dangerous"]
        dangerous_tags = []
        for pattern, name in [
            (r"<script\b", "script"),
            (r"<iframe\b", "iframe"),
            (r"<embed\b", "embed"),
            (r"<object\b", "object"),
            (r"<form\b", "form"),
            (r"javascript\s*:", "javascript:-URL"),
            (r"\bon(?:click|load|error|mouseover)\s*=", "Inline-Event-Handler"),
        ]:
            if re.search(pattern, html_body, re.IGNORECASE):
                dangerous_tags.append(name)
        if dangerous_tags:
            breakdown.checks.append(CheckResult(
                key="html_dangerous", label="Dangerous HTML", status="fail",
                score=0.0, max_score=max_s,
                detail=f"Gefunden: {', '.join(dangerous_tags)} — viele Mailclients und Filter blockieren das",
                fix_hint="JavaScript, iframes, embeds und form-Tags raus aus HTML-Mails. Nur statisches HTML mit table+img+a verwenden.",
            ))
        else:
            breakdown.checks.append(CheckResult(
                key="html_dangerous", label="Dangerous HTML", status="pass",
                score=max_s, max_score=max_s,
                detail="Kein JavaScript, iframe, embed, object, form, javascript:-URL oder Inline-Handler",
            ))

        # 10) Image ALT-Attribute
        max_s = _WEIGHTS["html_alt"]
        img_tags = re.findall(r"<img\b[^>]*>", html_body, re.IGNORECASE)
        img_without_alt = [t for t in img_tags if not re.search(r"\balt\s*=", t, re.IGNORECASE)]
        if not img_tags:
            breakdown.checks.append(CheckResult(
                key="html_alt", label="Image-ALT-Attribute", status="pass",
                score=max_s, max_score=max_s,
                detail="Keine Bilder in der Mail",
            ))
        elif not img_without_alt:
            breakdown.checks.append(CheckResult(
                key="html_alt", label="Image-ALT-Attribute", status="pass",
                score=max_s, max_score=max_s,
                detail=f"Alle {len(img_tags)} Bilder haben alt-Attribute",
            ))
        else:
            breakdown.checks.append(CheckResult(
                key="html_alt", label="Image-ALT-Attribute", status="warn",
                score=max_s * 0.3, max_score=max_s,
                detail=f"{len(img_without_alt)} von {len(img_tags)} Bildern ohne alt-Attribut",
                fix_hint="<code>&lt;img alt=\"...\"&gt;</code> für jedes Bild — verbessert Accessibility und Spam-Score.",
            ))

        # 11) Short-URLs (bit.ly, t.co, goo.gl, ow.ly, tinyurl)
        max_s = _WEIGHTS["short_urls"]
        short_hosts = ["bit.ly", "t.co", "goo.gl", "ow.ly", "tinyurl.com", "is.gd",
                       "buff.ly", "rebrand.ly", "shorturl.at", "rb.gy", "cutt.ly"]
        found_shorts = []
        for h in short_hosts:
            if re.search(rf"\bhttps?://{re.escape(h)}\b", html_body, re.IGNORECASE):
                found_shorts.append(h)
        if found_shorts:
            breakdown.checks.append(CheckResult(
                key="short_urls", label="Short-URLs", status="warn",
                score=0.0, max_score=max_s,
                detail=f"Gefunden: {', '.join(found_shorts)} — Short-URLs sind Spam-Signal",
                fix_hint="Statt Short-URLs eigene Tracking-Domain nutzen (z.B. links.deine-firma.ch).",
            ))
        else:
            breakdown.checks.append(CheckResult(
                key="short_urls", label="Short-URLs", status="pass",
                score=max_s, max_score=max_s,
                detail="Keine URL-Verkürzer verwendet",
            ))

    # ============================================================================
    # 12) MX-Record der Sender-Domain
    # ============================================================================
    if breakdown.sender_domain:
        max_s = _WEIGHTS["sender_mx"]
        mxs = _mx_records(breakdown.sender_domain)
        if mxs:
            breakdown.checks.append(CheckResult(
                key="sender_mx", label=f"MX-Record für Sender-Domain", status="pass",
                score=max_s, max_score=max_s,
                detail=f"{len(mxs)} MX-Record(s) gefunden",
                raw_evidence="\n".join(f"{p} {h}" for p, h in mxs),
            ))
        else:
            breakdown.checks.append(CheckResult(
                key="sender_mx", label=f"MX-Record für Sender-Domain", status="warn",
                score=max_s * 0.3, max_score=max_s,
                detail=f"Kein MX-Record für '{breakdown.sender_domain}' gefunden — Bounces können nicht zugestellt werden",
                fix_hint="MX-Record auf den Empfangs-Mailserver setzen, sonst kommen Bounces/Replies ins Leere.",
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
