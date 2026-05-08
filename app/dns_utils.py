"""Lightweight DNS helpers used during ingest and verification."""
from __future__ import annotations

import ipaddress
import logging
from functools import lru_cache
from typing import Optional

import dns.exception
import dns.resolver
import dns.reversename

log = logging.getLogger(__name__)

_resolver = dns.resolver.Resolver()
_resolver.lifetime = 3.0
_resolver.timeout = 3.0


@lru_cache(maxsize=4096)
def reverse_lookup(ip: str) -> Optional[str]:
    try:
        ipaddress.ip_address(ip)
    except ValueError:
        return None
    try:
        rev = dns.reversename.from_address(ip)
        answers = _resolver.resolve(rev, "PTR", lifetime=3.0)
        for rdata in answers:
            host = str(rdata.target).rstrip(".")
            if host:
                return host
    except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer, dns.resolver.NoNameservers, dns.exception.Timeout):
        return None
    except Exception as e:  # noqa: BLE001
        log.debug("reverse_lookup(%s) failed: %s", ip, e)
    return None


def get_txt_records(name: str) -> list[str]:
    try:
        answers = _resolver.resolve(name, "TXT", lifetime=3.0)
    except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer, dns.resolver.NoNameservers, dns.exception.Timeout):
        return []
    except Exception as e:  # noqa: BLE001
        log.debug("TXT lookup for %s failed: %s", name, e)
        return []
    out: list[str] = []
    for rdata in answers:
        chunks = [b.decode("utf-8", errors="replace") for b in rdata.strings]
        out.append("".join(chunks))
    return out


def has_dmarc_record(domain: str) -> bool:
    txts = get_txt_records(f"_dmarc.{domain}")
    return any(t.lower().startswith("v=dmarc1") for t in txts)


def verification_present(domain: str, token: str) -> bool:
    expected = f"dmarc-aggregator-verify={token}"
    txts = get_txt_records(domain)
    return any(t.strip() == expected for t in txts)


# Common DKIM selectors used by major providers — best-effort discovery
DKIM_SELECTORS = [
    # generic / very common
    "default", "dkim", "mail", "email", "smtp",
    # Google Workspace
    "google", "google2024", "google2023", "20230601", "20240601", "20250101",
    # Microsoft 365 (CNAMEs auf selector1-<domain>-com._domainkey.<tenant>.onmicrosoft.com)
    "selector1", "selector2",
    # generic numbered
    "s1", "s2", "s3", "k1", "k2", "k3", "sm1", "sm2",
    # Mailcow / Postfix common
    "dkim1", "dkim2", "mta1", "mta2",
    # Marketing-Versender
    "mandrill",  # Mailchimp Mandrill
    "mailchimp", "mc1", "mc2",
    "sendgrid", "s1._domainkey",  # SendGrid uses s1, s2
    "amazonses", "ses", "ses1",
    "klaviyo", "klaviyo1", "klaviyo2",
    "mailgun", "mg", "mg1", "mg2", "k1.mailgun",
    "postmark", "pm",
    "sparkpost", "scph0220", "scph1118",
    "everlytic", "everlytic1",
    "sendinblue", "mail._domainkey", "sib",
    "zoho", "zoho1",
    # Hosting-Provider-Defaults
    "mxvault",  # IONOS / 1&1
    "k._domainkey",
    # Datums-Pattern (Microsoft/Google nutzen sowas)
    "202401", "202402", "202403", "202404", "202405", "202406",
    "202407", "202408", "202409", "202410", "202411", "202412",
    "202501", "202502", "202503", "202504", "202505", "202506",
    "202507", "202508", "202509", "202510", "202511", "202512",
    "2024", "2025",
    # Proton, Fastmail, etc.
    "protonmail", "proton",
    "fastmail", "fm1", "fm2", "fm3",
    # Atlassian / HelpScout / Intercom / Customer.io
    "intuit", "helpscout", "intercom", "customerio",
    # Apple iCloud
    "sig1",
    # Hubspot
    "hs1", "hs2", "hs1-domainkey",
    # generic-named selectors people pick
    "primary", "secondary", "main", "pre", "live",
]


# Mail-Provider erkennen anhand MX-Hostnamen
MX_PROVIDERS = [
    # Pattern, Provider-Name, Kategorie ("cloud" | "selfhost" | "small" | "marketing")
    (r".*\.aspmx\.l\.google\.com$", "Google Workspace", "cloud"),
    (r".*aspmx\.googlemail\.com$", "Google (Gmail)", "cloud"),
    (r".*\.google\.com$", "Google", "cloud"),
    (r".*\.mail\.protection\.outlook\.com$", "Microsoft 365 / Exchange Online", "cloud"),
    (r".*\.mail\.eo\.outlook\.com$", "Microsoft Exchange Online Protection", "cloud"),
    (r".*\.outlook\.com$", "Microsoft Outlook.com", "cloud"),
    (r".*\.icloud\.com$", "Apple iCloud Mail", "cloud"),
    (r"mx[0-9]*\.zoho\.com$", "Zoho Mail", "cloud"),
    (r"mx[0-9]*\.zoho\.eu$", "Zoho Mail (EU)", "cloud"),
    (r".*\.mail\.yandex\.net$", "Yandex Mail", "cloud"),
    (r".*\.fastmail\.com$", "Fastmail", "cloud"),
    (r".*\.messagingengine\.com$", "Fastmail (MessagingEngine)", "cloud"),
    (r".*\.protonmail\.ch$", "Proton Mail", "cloud"),
    (r".*\.proton\.me$", "Proton Mail", "cloud"),
    (r".*\.mailbox\.org$", "mailbox.org", "cloud"),
    (r".*\.posteo\.(de|net)$", "Posteo", "cloud"),
    (r".*\.tutanota\.de$", "Tuta Mail", "cloud"),
    (r".*\.kundenserver\.de$", "IONOS / 1&1", "cloud"),
    (r".*\.netcup\.net$", "Netcup", "cloud"),
    (r"mx[0-9]*\.strato\.de$", "Strato Mail", "cloud"),
    (r".*\.hosteurope\.de$", "Host Europe", "cloud"),
    (r".*\.your-server\.de$", "Hetzner (Storage Box)", "cloud"),
    (r".*\.hetzner\.com$", "Hetzner", "cloud"),
    (r"mxext[0-9]*\.your-storagebox\.de$", "Hetzner Storage Box", "cloud"),
    (r".*\.amazonses\.com$", "AWS SES", "marketing"),
    (r".*\.amazonaws\.com$", "AWS (eigener Mailserver)", "selfhost"),
    (r".*\.sendgrid\.net$", "SendGrid", "marketing"),
    (r".*\.mailgun\.org$", "Mailgun", "marketing"),
    (r".*\.cust-spam\.com$", "Mimecast", "cloud"),
    (r".*\.mimecast\.com$", "Mimecast", "cloud"),
    (r".*\.mimecast\.net$", "Mimecast", "cloud"),
    (r".*\.pphosted\.com$", "Proofpoint", "cloud"),
    (r".*\.barracudanetworks\.com$", "Barracuda", "cloud"),
    (r".*\.cloudflareemail\.com$", "Cloudflare Email Routing", "cloud"),
    (r".*\.privateemail\.com$", "Namecheap Private Email", "cloud"),
    (r".*\.gandi\.net$", "Gandi Mail", "cloud"),
    (r".*\.everlytic\.net$", "Everlytic", "marketing"),
    (r".*\.mailcow\..*$", "Mailcow (self-hosted)", "selfhost"),
    (r".*\.greenhost\.net$", "Greenhost", "cloud"),
    (r".*\.runbox\.com$", "Runbox", "cloud"),
]


def lookup_mx(domain: str) -> dict:
    """Return MX records + provider detection."""
    import re as _re
    out: dict = {"present": False, "records": [], "provider": None, "category": None, "issues": []}
    try:
        answers = _resolver.resolve(domain, "MX", lifetime=3.0)
    except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer, dns.resolver.NoNameservers, dns.exception.Timeout):
        return out
    except Exception as e:  # noqa: BLE001
        log.debug("MX lookup for %s failed: %s", domain, e)
        return out
    records: list[dict] = []
    for r in answers:
        host = str(r.exchange).rstrip(".")
        records.append({"priority": int(r.preference), "host": host})
    records.sort(key=lambda x: x["priority"])
    out["records"] = records
    out["present"] = bool(records)
    if records:
        # Provider detection on lowest-priority MX
        primary = records[0]["host"].lower()
        for pattern, name, cat in MX_PROVIDERS:
            if _re.match(pattern, primary):
                out["provider"] = name
                out["category"] = cat
                break
        if not out["provider"]:
            # Fallback: extract second-level domain
            parts = primary.split(".")
            if len(parts) >= 2:
                out["provider"] = ".".join(parts[-2:]) + " (eigener / unbekannt)"
                out["category"] = "selfhost"
        # Sanity-checks
        if any(r["host"].endswith(".local") or r["host"].endswith(".localhost") for r in records):
            out["issues"].append("MX zeigt auf .local-Hostname — falsch konfiguriert.")
        if len(records) == 1 and records[0]["priority"] != 10:
            # nur informativ
            pass
    return out


def lookup_spf(domain: str) -> dict:
    """Return SPF record analysis."""
    out: dict = {"present": False, "valid": False, "raw": None, "issues": []}
    for t in get_txt_records(domain):
        if t.lower().startswith("v=spf1"):
            out["present"] = True
            out["raw"] = t
            # quick checks
            if t.endswith("?all") or "?all" in t:
                out["issues"].append("Soft policy '?all' — kein wirklicher Schutz.")
            if t.endswith("+all") or "+all" in t:
                out["issues"].append("'+all' lässt jeden senden — entspricht keinem Schutz.")
            if not (t.endswith("-all") or t.endswith("~all")):
                out["issues"].append("Kein '-all' oder '~all' am Ende — Policy unklar.")
            # 10-DNS-lookup limit warning (rough heuristic)
            includes = t.lower().count("include:") + t.lower().count("a:") + t.lower().count("mx")
            if includes >= 10:
                out["issues"].append(f"~{includes} DNS-Lookups — RFC-7208-Limit ist 10.")
            out["valid"] = True
            break
    return out


def lookup_dmarc(domain: str) -> dict:
    out: dict = {"present": False, "valid": False, "raw": None, "policy": None,
                  "rua": [], "issues": []}
    for t in get_txt_records(f"_dmarc.{domain}"):
        if t.lower().startswith("v=dmarc1"):
            out["present"] = True
            out["raw"] = t
            for part in t.split(";"):
                k, _, v = part.strip().partition("=")
                k = k.lower().strip(); v = v.strip()
                if k == "p":
                    out["policy"] = v
                elif k == "rua":
                    out["rua"] = [a.strip() for a in v.split(",") if a.strip()]
                elif k == "pct":
                    try: out["pct"] = int(v)
                    except ValueError: pass
            if out["policy"] == "none":
                out["issues"].append("p=none → nur Reporting, kein aktiver Schutz vor Spoofing.")
            if not out["rua"]:
                out["issues"].append("Kein rua= → du bekommst keine Reports.")
            out["valid"] = True
            break
    return out


def lookup_dkim_selectors(domain: str, selectors: Optional[list[str]] = None) -> list[dict]:
    selectors = selectors or DKIM_SELECTORS
    found = []
    for sel in selectors:
        txts = get_txt_records(f"{sel}._domainkey.{domain}")
        for t in txts:
            low = t.lower()
            if "v=dkim1" in low or "k=rsa" in low or "p=" in low:
                found.append({"selector": sel, "raw": t,
                              "valid": "p=" in low and len(t) > 20})
                break
    return found


def parse_dkim_record(raw: str) -> dict:
    """Parse a DKIM TXT record into structured fields with quality assessment.

    Returns dict with: tags{k:v}, key_b64, key_type, key_size_bits, hash_algos,
    flags, valid, issues[], notes[].

    Quoting + multi-string-concat: callers should pass the joined string already.
    """
    out: dict = {
        "raw": raw,
        "tags": {},
        "key_b64": None,
        "key_type": None,
        "key_size_bits": None,
        "hash_algos": [],
        "flags": [],
        "service_types": [],
        "notes": [],
        "issues": [],
        "valid": False,
        "is_revoked": False,
    }
    if not raw:
        out["issues"].append("Leerer Record")
        return out

    # Parse k=v; pairs (DKIM uses semicolons)
    for part in raw.split(";"):
        if "=" not in part:
            continue
        k, _, v = part.strip().partition("=")
        k = k.strip().lower()
        v = v.strip()
        if k:
            out["tags"][k] = v

    tags = out["tags"]

    # v= (version, optional but if present must be DKIM1)
    if "v" in tags and tags["v"] != "DKIM1":
        out["issues"].append(f'v={tags["v"]} ungültig — muss "DKIM1" sein.')

    # k= key type (default rsa)
    out["key_type"] = (tags.get("k") or "rsa").lower()
    if out["key_type"] not in ("rsa", "ed25519"):
        out["issues"].append(f"Unbekannter key-Type: {out['key_type']}")

    # h= hash algorithms (default sha256, optionally sha1)
    if "h" in tags:
        out["hash_algos"] = [a.strip().lower() for a in tags["h"].split(":") if a.strip()]
        for a in out["hash_algos"]:
            if a not in ("sha1", "sha256"):
                out["issues"].append(f"Unbekannter Hash-Algorithmus: {a}")
        if "sha1" in out["hash_algos"] and "sha256" not in out["hash_algos"]:
            out["issues"].append("Nur SHA-1 — Empfänger ignorieren das oft, SHA-256 sollte mindestens auch zugelassen sein.")
    else:
        out["hash_algos"] = ["sha256"]  # default

    # t= flags (y = test mode, s = strict alignment)
    if "t" in tags:
        flags = [f.strip().lower() for f in tags["t"].split(":") if f.strip()]
        out["flags"] = flags
        if "y" in flags:
            out["notes"].append("Test-Modus aktiv (t=y) — Empfänger sollen Auth-Failures NICHT durchsetzen. Beabsichtigt?")
        if "s" in flags:
            out["notes"].append("Strict-Alignment (t=s) — keine Subdomain-Varianten erlaubt.")

    # s= service types (default *)
    if "s" in tags:
        out["service_types"] = [s.strip().lower() for s in tags["s"].split(":") if s.strip()]

    # p= public key (required)
    pub = tags.get("p", "")
    if pub == "":
        out["is_revoked"] = True
        out["issues"].append("REVOZIERT — leerer Public-Key (p=). Selektor ist explizit deaktiviert.")
    elif not pub:
        out["issues"].append("Public-Key fehlt (p=).")
    else:
        out["key_b64"] = pub
        # Estimate key size from base64 length (rough): RSA 1024 ~ 215 chars, 2048 ~ 380, 4096 ~ 720
        try:
            import base64
            der = base64.b64decode(pub + "==", validate=False)
            # ASN.1 DER-encoded public key — extract modulus length heuristically
            # For RSA SubjectPublicKeyInfo, the modulus is buried; we approximate via DER len.
            # Total DER size ~= key_size_bytes + ~30 overhead bytes for OID/headers.
            approx_bits = max(0, (len(der) - 38) * 8)
            # Round to nearest power-of-2-ish standard (1024, 2048, 3072, 4096)
            for std in (1024, 2048, 3072, 4096):
                if abs(approx_bits - std) < 200:
                    out["key_size_bits"] = std
                    break
            else:
                out["key_size_bits"] = approx_bits
        except Exception:  # noqa: BLE001
            pass
        out["valid"] = True

    # Quality issues
    if out["valid"] and out["key_size_bits"]:
        if out["key_size_bits"] < 1024:
            out["issues"].append(f"Schlüssel zu kurz: {out['key_size_bits']} Bit — Mindestempfehlung 1024 Bit, besser 2048.")
        elif out["key_size_bits"] < 2048:
            out["notes"].append(f"Schlüssel ist {out['key_size_bits']} Bit — funktioniert, aber 2048 Bit ist heute Standard.")

    if out["valid"] and out["key_type"] == "rsa" and out["key_size_bits"] and out["key_size_bits"] < 2048:
        out["notes"].append("Empfehlung: bei nächster Rotation auf RSA-2048 oder Ed25519 wechseln.")

    return out


def lookup_dkim_with_details(domain: str, selectors: Optional[list[str]] = None) -> list[dict]:
    """Like lookup_dkim_selectors, but with parsed details per record."""
    selectors = selectors or DKIM_SELECTORS
    found = []
    for sel in selectors:
        txts = get_txt_records(f"{sel}._domainkey.{domain}")
        for t in txts:
            low = t.lower()
            if "v=dkim1" in low or "k=rsa" in low or "k=ed25519" in low or "p=" in low:
                parsed = parse_dkim_record(t)
                parsed["selector"] = sel
                parsed["fqdn"] = f"{sel}._domainkey.{domain}"
                found.append(parsed)
                break
    return found


def lookup_mta_sts(domain: str) -> dict:
    out: dict = {"present": False, "raw": None}
    for t in get_txt_records(f"_mta-sts.{domain}"):
        if t.lower().startswith("v=stsv1"):
            out["present"] = True; out["raw"] = t; break
    return out


def lookup_tls_rpt(domain: str) -> dict:
    out: dict = {"present": False, "raw": None}
    for t in get_txt_records(f"_smtp._tls.{domain}"):
        if t.lower().startswith("v=tlsrptv1"):
            out["present"] = True; out["raw"] = t; break
    return out


def lookup_bimi(domain: str) -> dict:
    out: dict = {"present": False, "raw": None}
    for t in get_txt_records(f"default._bimi.{domain}"):
        if t.lower().startswith("v=bimi1"):
            out["present"] = True; out["raw"] = t; break
    return out


def full_dns_check(domain: str) -> dict:
    """Run all checks. Best-effort — DNS errors silently return absent."""
    return {
        "domain": domain,
        "mx": lookup_mx(domain),
        "spf": lookup_spf(domain),
        "dmarc": lookup_dmarc(domain),
        "dkim": lookup_dkim_selectors(domain),
        "mta_sts": lookup_mta_sts(domain),
        "tls_rpt": lookup_tls_rpt(domain),
        "bimi": lookup_bimi(domain),
    }


def score_check(result: dict) -> dict:
    """Compute 0-100 health score plus per-check status (ok/warn/fail).

    Status pro Check:
      ok   = vorhanden + ohne Issues
      warn = vorhanden, aber Verbesserungspotenzial
      fail = fehlt komplett
      info = optional, nicht gesetzt aber kein Schaden
    """
    sc: dict = {"total": 0, "max": 100, "checks": {}, "summary": []}

    mx = result.get("mx") or {}
    if mx.get("present"):
        sc["checks"]["mx"] = {"status": "ok", "label": "MX-Records gesetzt", "points": 5}
    else:
        sc["checks"]["mx"] = {"status": "fail", "label": "Keine MX-Records — Domain empfängt keine Mails", "points": 0}

    spf = result.get("spf") or {}
    if spf.get("present") and not spf.get("issues"):
        sc["checks"]["spf"] = {"status": "ok", "label": "SPF gesetzt &amp; sauber", "points": 25}
    elif spf.get("present"):
        sc["checks"]["spf"] = {"status": "warn", "label": "SPF gesetzt, aber Probleme erkannt", "points": 15}
    else:
        sc["checks"]["spf"] = {"status": "fail", "label": "SPF fehlt komplett", "points": 0}

    dmarc = result.get("dmarc") or {}
    if dmarc.get("present"):
        pol = (dmarc.get("policy") or "none").lower()
        has_rua = bool(dmarc.get("rua"))
        if pol in ("quarantine", "reject") and has_rua:
            sc["checks"]["dmarc"] = {"status": "ok",
                "label": f"DMARC scharf ({pol}) + Reports konfiguriert", "points": 30}
        elif pol == "none" and has_rua:
            sc["checks"]["dmarc"] = {"status": "warn",
                "label": "DMARC im Beobachtungs-Modus (p=none) — kein Spoofing-Schutz", "points": 18}
        elif pol in ("quarantine", "reject") and not has_rua:
            sc["checks"]["dmarc"] = {"status": "warn",
                "label": f"DMARC scharf ({pol}), aber keine Reports (rua fehlt) — du fliegst blind", "points": 18}
        else:
            sc["checks"]["dmarc"] = {"status": "warn",
                "label": "DMARC vorhanden, aber unvollständig", "points": 10}
    else:
        sc["checks"]["dmarc"] = {"status": "fail", "label": "DMARC fehlt komplett", "points": 0}

    dkim = result.get("dkim") or []
    if dkim:
        sc["checks"]["dkim"] = {"status": "ok",
            "label": f"DKIM gefunden ({len(dkim)} Selektor{'en' if len(dkim) != 1 else ''})", "points": 25}
    else:
        sc["checks"]["dkim"] = {"status": "fail",
            "label": "Keine DKIM-Selektoren gefunden — fehlt oder unbekannter Selektor-Name", "points": 0}

    mta_sts = result.get("mta_sts") or {}
    if mta_sts.get("present"):
        sc["checks"]["mta_sts"] = {"status": "ok", "label": "MTA-STS gesetzt", "points": 5}
    else:
        sc["checks"]["mta_sts"] = {"status": "info", "label": "MTA-STS optional, nicht gesetzt", "points": 0}

    tls_rpt = result.get("tls_rpt") or {}
    if tls_rpt.get("present"):
        sc["checks"]["tls_rpt"] = {"status": "ok", "label": "TLS-RPT gesetzt", "points": 5}
    else:
        sc["checks"]["tls_rpt"] = {"status": "info", "label": "TLS-RPT optional, nicht gesetzt", "points": 0}

    bimi = result.get("bimi") or {}
    if bimi.get("present"):
        sc["checks"]["bimi"] = {"status": "ok", "label": "BIMI gesetzt — Logo neben Mails sichtbar", "points": 5}
    else:
        sc["checks"]["bimi"] = {"status": "info", "label": "BIMI optional, nicht gesetzt", "points": 0}

    sc["total"] = sum(c["points"] for c in sc["checks"].values())

    # Grade
    t = sc["total"]
    if t >= 85:   sc["grade"], sc["grade_label"] = "A", "Exzellent"
    elif t >= 70: sc["grade"], sc["grade_label"] = "B", "Gut, mit Feinschliff"
    elif t >= 50: sc["grade"], sc["grade_label"] = "C", "Solide Basis, Lücken"
    elif t >= 30: sc["grade"], sc["grade_label"] = "D", "Riskant"
    else:         sc["grade"], sc["grade_label"] = "F", "Akut handlungsbedürftig"

    # Headline-Empfehlung (höchste Priorität zuerst)
    actions: list[str] = []
    if sc["checks"]["dmarc"]["status"] == "fail":
        actions.append("DMARC-Record anlegen — sonst kann jeder unter deinem Namen senden.")
    if sc["checks"]["spf"]["status"] == "fail":
        actions.append("SPF-Record anlegen — Voraussetzung für alles weitere.")
    if sc["checks"]["dkim"]["status"] == "fail":
        actions.append("DKIM-Signatur einrichten — Mailserver schickt unsignierte Mails.")
    if sc["checks"]["dmarc"]["status"] == "warn" and (dmarc.get("policy") or "") == "none":
        actions.append("DMARC schärfen: 2-4 Wochen Reports auswerten und auf p=quarantine wechseln.")
    if not actions:
        actions.append("Setup ist solide — optional MTA-STS, TLS-RPT oder BIMI ergänzen.")

    sc["actions"] = actions
    return sc
