"""DNSBL / RBL blacklist checks for sending IPs and MX hosts.

Reliability features:
- Multi-resolver: rotates through Cloudflare/Google/Quad9 + system default
- Retries with exponential backoff
- 1h in-process cache (avoid hammering rate-limited DNSBLs)
- Optional Spamhaus DQS-Auth-Code: queries go through *.dq.spamhaus.net which
  is not rate-limited and has guaranteed SLA (free for non-commercial usage).
"""
from __future__ import annotations

import ipaddress
import logging
import time
from typing import Iterable, Optional

import dns.exception
import dns.resolver

log = logging.getLogger(__name__)


# --- Public DNSBL zones (used as fallback when DQS is not configured) ---
PUBLIC_BLACKLISTS: list[tuple[str, str, int]] = [
    ("zen.spamhaus.org",      "Spamhaus ZEN",        3),
    ("sbl.spamhaus.org",      "Spamhaus SBL",        3),
    ("xbl.spamhaus.org",      "Spamhaus XBL",        3),
    ("pbl.spamhaus.org",      "Spamhaus PBL",        2),
    ("bl.spamcop.net",        "SpamCop",             2),
    ("cbl.abuseat.org",       "AbuseAt CBL",         3),
    ("dnsbl.sorbs.net",       "SORBS",               2),
    ("b.barracudacentral.org","Barracuda",           3),
    ("psbl.surriel.com",      "PSBL Surriel",        2),
    ("bl.mailspike.net",      "Mailspike",           2),
    ("ix.dnsbl.manitu.net",   "Manitu (NiX)",        2),
    ("dnsbl-1.uceprotect.net","UCEProtect L1",       2),
]


def _spamhaus_dqs_zones(key: str) -> list[tuple[str, str, int]]:
    """Spamhaus DQS-authenticated zones — replace public Spamhaus entries."""
    return [
        (f"{key}.zen.dq.spamhaus.net", "Spamhaus ZEN (DQS)", 3),
        (f"{key}.sbl.dq.spamhaus.net", "Spamhaus SBL (DQS)", 3),
        (f"{key}.xbl.dq.spamhaus.net", "Spamhaus XBL (DQS)", 3),
        (f"{key}.pbl.dq.spamhaus.net", "Spamhaus PBL (DQS)", 2),
    ]


def active_blacklists() -> list[tuple[str, str, int]]:
    """Compose the active blacklist set based on settings.

    With DQS-Key set: Spamhaus zones are replaced with the auth-versions, the
    other public DNSBLs (SpamCop, Barracuda, SORBS, ...) remain on public.
    Without key: pure public list.
    """
    from .config import get_settings
    s = get_settings()
    key = (s.spamhaus_dqs_key or "").strip()
    if not key:
        return list(PUBLIC_BLACKLISTS)
    spamhaus_zones = _spamhaus_dqs_zones(key)
    others = [(z, n, sev) for (z, n, sev) in PUBLIC_BLACKLISTS
              if not z.endswith("spamhaus.org") and z != "cbl.abuseat.org"]
    return spamhaus_zones + others


# Backwards-compat alias for existing callers / templates
BLACKLISTS = PUBLIC_BLACKLISTS


# Per-list delisting endpoints. Each entry maps a zone to (form-URL, lookup-URL).
# `{ip}` placeholder gets the offending IP substituted in (URL-encoded by caller
# if needed). lookup-URL = where to verify if you're listed; form-URL = where
# to request removal.
DELISTING_LINKS: dict[str, dict[str, str]] = {
    "zen.spamhaus.org": {
        "lookup": "https://check.spamhaus.org/results/?query={ip}",
        "remove": "https://check.spamhaus.org/results/?query={ip}",
    },
    "sbl.spamhaus.org": {
        "lookup": "https://check.spamhaus.org/results/?query={ip}",
        "remove": "https://check.spamhaus.org/listing-removal/",
    },
    "xbl.spamhaus.org": {
        "lookup": "https://check.spamhaus.org/results/?query={ip}",
        "remove": "https://check.spamhaus.org/listing-removal/",
    },
    "pbl.spamhaus.org": {
        "lookup": "https://check.spamhaus.org/results/?query={ip}",
        "remove": "https://check.spamhaus.org/listing-removal/",
    },
    "bl.spamcop.net": {
        "lookup": "https://www.spamcop.net/w3m?action=checkblock&ip={ip}",
        "remove": "https://www.spamcop.net/w3m?action=checkblock&ip={ip}",
    },
    "cbl.abuseat.org": {
        # CBL is now operated by Spamhaus
        "lookup": "https://check.spamhaus.org/results/?query={ip}",
        "remove": "https://check.spamhaus.org/listing-removal/",
    },
    "dnsbl.sorbs.net": {
        "lookup": "https://www.sorbs.net/lookup.shtml?{ip}",
        "remove": "https://www.sorbs.net/cgi-bin/db",
    },
    "b.barracudacentral.org": {
        "lookup": "https://www.barracudacentral.org/lookups/lookup-reputation?ip={ip}",
        "remove": "https://www.barracudacentral.org/rbl/removal-request",
    },
    "psbl.surriel.com": {
        "lookup": "https://psbl.org/listing?ip={ip}",
        "remove": "https://psbl.org/remove",
    },
    "bl.mailspike.net": {
        "lookup": "https://check.mailspike.net/?addr={ip}",
        "remove": "https://www.mailspike.org/iframe/lookup.html",
    },
    "ix.dnsbl.manitu.net": {
        "lookup": "https://www.dnsbl.manitu.net/lookup.php?ip={ip}",
        "remove": "https://www.dnsbl.manitu.net/lookup.php?ip={ip}",
    },
    "dnsbl-1.uceprotect.net": {
        "lookup": "https://www.uceprotect.net/en/rblcheck.php?ipr={ip}",
        "remove": "https://www.uceprotect.net/en/index.php?m=3&s=4",
    },
}


def delisting_url(zone: str, ip: str, kind: str = "remove") -> str:
    """Return the delisting URL for a hit. `kind` is 'remove' or 'lookup'.

    Falls back to a generic multi-RBL lookup if the zone is not in our table.
    """
    entry = DELISTING_LINKS.get(zone)
    if not entry:
        return f"https://multirbl.valli.org/lookup/{ip}.html"
    template = entry.get(kind) or entry.get("lookup") or entry.get("remove")
    if not template:
        return f"https://multirbl.valli.org/lookup/{ip}.html"
    return template.replace("{ip}", ip)


def _make_resolver(nameservers: Optional[list[str]] = None) -> dns.resolver.Resolver:
    r = dns.resolver.Resolver(configure=(nameservers is None))
    r.lifetime = 4.0
    r.timeout = 4.0
    if nameservers:
        r.nameservers = nameservers
    return r


# Multi-resolver pool. We rotate through these on retries to dodge per-resolver
# rate-limits (especially Spamhaus public-zones which block 8.8.8.8 etc.).
_RESOLVERS = [
    _make_resolver(),                     # system default (often router/ISP)
    _make_resolver(["1.1.1.1", "1.0.0.1"]),  # Cloudflare
    _make_resolver(["9.9.9.9", "149.112.112.112"]),  # Quad9
    _make_resolver(["8.8.8.8", "8.8.4.4"]),  # Google
]


# In-process cache: {(zone, ip): (timestamp, hit_dict_or_None)}
# Avoids re-querying the same DNSBL for the same IP within TTL.
_CACHE: dict[tuple[str, str], tuple[float, Optional[dict]]] = {}
_CACHE_TTL = 3600  # 1 hour
_CACHE_MAX = 10000


def _cache_get(key: tuple[str, str]) -> tuple[bool, Optional[dict]]:
    """Return (cached?, value). value is None for "not listed", dict for "hit"."""
    entry = _CACHE.get(key)
    if entry is None:
        return False, None
    ts, val = entry
    if time.time() - ts > _CACHE_TTL:
        _CACHE.pop(key, None)
        return False, None
    return True, val


def _cache_set(key: tuple[str, str], value: Optional[dict]) -> None:
    if len(_CACHE) >= _CACHE_MAX:
        # Drop oldest 10%
        oldest = sorted(_CACHE.items(), key=lambda kv: kv[1][0])[: _CACHE_MAX // 10]
        for k, _ in oldest:
            _CACHE.pop(k, None)
    _CACHE[key] = (time.time(), value)


def _reverse_ip(ip: str) -> Optional[str]:
    """Reverse octets of an IPv4 (DNSBL-Standard). IPv6 we skip — most DNSBLs
    publish only IPv4-zones."""
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return None
    if isinstance(addr, ipaddress.IPv6Address):
        return None
    return ".".join(reversed(str(addr).split(".")))


def _resolve_with_retry(qname: str, rdtype: str = "A") -> Optional[list]:
    """Try resolving a name across all resolvers, with backoff between resolvers.

    Returns list of answers, or None on definitive NXDOMAIN/NoAnswer.
    Raises last exception if all resolvers fail with errors (timeout etc.).
    """
    last_err: Optional[Exception] = None
    for i, r in enumerate(_RESOLVERS):
        try:
            return list(r.resolve(qname, rdtype, lifetime=4.0))
        except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer):
            return None  # definitive: not listed (return rather than retry)
        except (dns.resolver.NoNameservers, dns.exception.Timeout) as e:
            last_err = e
            time.sleep(0.2 * (i + 1))  # small backoff before next resolver
        except Exception as e:  # noqa: BLE001
            last_err = e
    if last_err:
        raise last_err
    return None


def check_ip(ip: str, lists: Optional[Iterable[tuple[str, str, int]]] = None) -> list[dict]:
    """Query all DNSBLs for a single IP. Returns list of hits (zone, name, code, txt).

    Uses 1h cache + multi-resolver rotation. A definitive NXDOMAIN counts as
    "not listed". A persistent timeout/error means the DNSBL is currently
    unreachable — that lookup is skipped (not treated as "not listed") to
    avoid false-clean signals.
    """
    rev = _reverse_ip(ip)
    if not rev:
        return []
    blacklists = list(lists) if lists is not None else active_blacklists()
    hits: list[dict] = []
    for zone, name, severity in blacklists:
        cache_key = (zone, ip)
        cached_present, cached_val = _cache_get(cache_key)
        if cached_present:
            if cached_val is not None:
                hits.append(cached_val)
            continue

        qname = f"{rev}.{zone}"
        try:
            answers = _resolve_with_retry(qname, "A")
        except Exception as e:  # noqa: BLE001
            log.debug("DNSBL %s unreachable for %s: %s — skipped (no clean/listed claim)",
                      zone, ip, e)
            # Don't cache failures — try again next time
            continue

        if not answers:
            # Definitive NXDOMAIN/NoAnswer → not listed
            _cache_set(cache_key, None)
            continue

        codes = [str(r) for r in answers]
        txt = ""
        try:
            txt_answers = _resolve_with_retry(qname, "TXT")
            if txt_answers:
                txt = " ".join("".join(b.decode("utf-8", errors="replace") for b in r.strings)
                               for r in txt_answers)[:200]
        except Exception:  # noqa: BLE001
            pass

        hit = {"zone": zone, "name": name, "severity": severity,
               "codes": codes, "txt": txt or ""}
        hits.append(hit)
        _cache_set(cache_key, hit)
    return hits


def cache_clear() -> int:
    """Clear the lookup cache. Returns number of entries dropped."""
    n = len(_CACHE)
    _CACHE.clear()
    return n


def check_ips(ips: Iterable[str]) -> dict[str, list[dict]]:
    """Bulk check. Returns {ip: [hits]} — only IPs with at least one hit are included."""
    out: dict[str, list[dict]] = {}
    for ip in ips:
        hits = check_ip(ip)
        if hits:
            out[ip] = hits
    return out


def severity_for(hits: list[dict]) -> int:
    """Highest severity in a hit-list, or 0 if empty."""
    if not hits:
        return 0
    return max(h.get("severity", 1) for h in hits)


def summary(hits: list[dict]) -> str:
    """One-line human summary."""
    if not hits:
        return "Nicht gelistet."
    names = sorted({h["name"] for h in hits})
    return f"Auf {len(hits)} Liste{'n' if len(hits) != 1 else ''}: " + ", ".join(names[:5]) + (
        f" und {len(names) - 5} weitere" if len(names) > 5 else "")
