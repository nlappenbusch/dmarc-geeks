"""Prospect-Discovery via Certificate-Transparency-Logs (crt.sh).

Idee: jede TLS-Zertifikat-Ausstellung wird in oeffentliche CT-Logs geschrieben.
crt.sh aggregiert das und ist kostenlos durchsuchbar per HTTP-API. Damit
finden wir aktive Schweizer Domains pro Keyword/Branche.

Workflow:
  1. User gibt Keyword (z.B. "treuhand") + TLD (".ch") ein
  2. Wir queryen crt.sh fuer alle Zertifikate die das Pattern matchen
  3. Aus den SAN-Listen extrahieren wir Root-Domains, deduplizieren
  4. Optional: DMARC-Check pro Root-Domain -> filter "ohne DMARC"
  5. Ergebnis-Liste -> direkt in den Crawler einspielbar

Rechtliches: CT-Logs sind per RFC 6962 explizit oeffentlich. Wir nutzen die
oeffentliche crt.sh-API mit moderatem Rate-Limit und identifizieren uns als
"DMARCGeeksProspectBot" im User-Agent.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Optional

import httpx

from .dns_utils import has_dmarc_record

log = logging.getLogger(__name__)

CRT_SH_API = "https://crt.sh/"
USER_AGENT = "DMARCGeeksProspectBot/1.0 (+https://dmarc-geeks.ch)"


# Branchen-Presets fuer "ich weiss nicht welches Keyword" --
# Schweizer KMU-Branchen die fuer Mail-Security besonders relevant sind.
BRANCH_PRESETS = [
    {"label": "Treuhand / Buchhaltung", "icon": "📊", "keyword": "treuhand",
     "rationale": "Sensible Finanzdaten · Compliance-getrieben · Rechnungsversand"},
    {"label": "Anwaltskanzleien", "icon": "⚖️", "keyword": "kanzlei",
     "rationale": "Mandantengeheimnis · CEO-Fraud-Ziel · viele Mailgespräche"},
    {"label": "Advokatur / Recht", "icon": "📜", "keyword": "advokat",
     "rationale": "Wie Anwälte, alternative Schreibweise"},
    {"label": "Versicherungs-Broker", "icon": "🛡️", "keyword": "broker",
     "rationale": "Kundenrisiken · sensible Daten · regulatorische Pflicht"},
    {"label": "Versicherungen", "icon": "📋", "keyword": "versicher",
     "rationale": "FINMA-Aufsicht · Compliance · große Mailvolumen"},
    {"label": "Arzt- & Zahnarzt-Praxen", "icon": "⚕️", "keyword": "praxis",
     "rationale": "Patientendaten · HIN-Anschluss · DSG sensitive Branche"},
    {"label": "Kliniken / Spitäler", "icon": "🏥", "keyword": "klinik",
     "rationale": "DSG · BIMI sinnvoll · viele Schnittstellen"},
    {"label": "IT-Dienstleister", "icon": "💻", "keyword": "informatik",
     "rationale": "Selbst Anbieter — peinlich wenn Mail-Setup schlecht"},
    {"label": "Architekturbüros", "icon": "📐", "keyword": "architekt",
     "rationale": "Familienbetriebe · Rechnungsversand · oft Outsourcing-IT"},
    {"label": "Immobilien-Verwaltung", "icon": "🏘️", "keyword": "immobil",
     "rationale": "Mietverträge per Mail · Rechnungen · große Kundenbasis"},
    {"label": "Treuhand (alt. Schreibweise)", "icon": "📊", "keyword": "fiduciary",
     "rationale": "Romandie/Englisch — fiduciary statt treuhand"},
    {"label": "Spedition / Logistik", "icon": "🚚", "keyword": "spedition",
     "rationale": "Internationale Mails · Spoofing-Ziel · oft alte Mailsetups"},
]


@dataclass
class ProspectResult:
    domain: str
    has_dmarc: Optional[bool] = None
    cert_count: int = 0           # wie viele Zertifikate fuer diese Domain in den letzten CT-Logs
    seen_sans: list[str] = field(default_factory=list)  # ein paar Sample-SANs zur Verifikation
    error: Optional[str] = None


def _extract_root(host: str, expected_tld: str = "") -> Optional[str]:
    """Aus einem (m)SAN-Hostname die Root-Domain ableiten.
    'mail.example.ch' -> 'example.ch'.   '*.example.ch' -> 'example.ch'.
    Filtert offensichtliche Cloud-Provider/Shared-Hosting raus.
    """
    h = host.strip().lower().rstrip(".")
    if h.startswith("*."):
        h = h[2:]
    if not h or h.startswith("-") or h.endswith("-"):
        return None
    if "/" in h or ":" in h or " " in h:
        return None

    # Provider-/Shared-Hosting-Domains ausfiltern (false positives)
    NOISE_DOMAINS = (
        "cloudfront.net", "azurewebsites.net", "azureedge.net",
        "amazonaws.com", "cloudapp.net", "elasticbeanstalk.com",
        "herokuapp.com", "github.io", "vercel.app", "netlify.app",
        "sharepoint.com", "onmicrosoft.com", "googleusercontent.com",
        "wpengine.com", "myshopify.com", "wixsite.com", "weebly.com",
        "squarespace.com", "rackspace.com", "fastly.net",
        "shopifycdn.com", "fastlylb.net", "edgekey.net",
        "lvh.me", "localhost", "internal", "local",
        "cdn.cloudflare.net", "cdn.shopify.com",
    )
    for n in NOISE_DOMAINS:
        if h == n or h.endswith("." + n):
            return None

    parts = h.split(".")
    if len(parts) < 2:
        return None

    # Bei mehrstufigem TLD wie .co.uk / .com.de / .ch (1-Level) hier vereinfachen:
    # Wir nehmen die letzten 2 Labels und akzeptieren das fuer .ch / .de / .com.
    # Fuer SLD-TLDs (.co.uk) gibt's edge cases die wir bewusst nicht handhaben --
    # User filtert sowieso auf .ch in der UI.
    root = ".".join(parts[-2:])

    if expected_tld:
        tld_clean = expected_tld.lstrip(".")
        if not root.endswith("." + tld_clean):
            return None

    return root


class DiscoveryError(Exception):
    """Discovery-Source ist temporaer down oder Query liefert keine Daten."""


def fetch_prospects(keyword: str, tld: str = "ch", *, limit: int = 100,
                    timeout: float = 30.0, retries: int = 2) -> list[ProspectResult]:
    """Frag crt.sh fuer Zertifikate die das Keyword + TLD matchen.
    Returns dedupe-d Root-Domain-Liste (max `limit`).

    Pattern wird gebaut als '%KEYWORD%.TLD' -- damit matched z.B. 'treuhand'
    sowohl 'meier-treuhand.ch' als auch 'treuhand-bern.ch'.

    crt.sh ist regelmaessig ueberlastet (502 / 504) -- wir retryen ein paar
    Mal mit kurzem Sleep. Wenn nach `retries+1` Versuchen immer noch nichts:
    DiscoveryError, damit der Caller das dem User klar zeigen kann.
    """
    import time

    keyword = (keyword or "").strip().lower()
    tld = (tld or "ch").strip().lower().lstrip(".")
    if not keyword:
        return []
    if not re.match(r"^[a-z0-9.\-]+$", keyword):
        log.warning("invalid keyword %r", keyword)
        return []
    if not re.match(r"^[a-z0-9]+$", tld):
        log.warning("invalid tld %r", tld)
        return []

    pattern = f"%{keyword}%.{tld}"
    params = {"q": pattern, "output": "json"}

    last_err: Optional[Exception] = None
    entries: list = []
    for attempt in range(retries + 1):
        try:
            with httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=timeout) as c:
                r = c.get(CRT_SH_API, params=params)
                if r.status_code in (502, 503, 504):
                    # Gateway-Fehler -> warten und retry
                    last_err = DiscoveryError(
                        f"crt.sh HTTP {r.status_code} (Server überlastet) — "
                        "passiert leider regelmäßig, einfach in 1-2 Minuten nochmal."
                    )
                    log.info("crt.sh returned %s, attempt %d/%d", r.status_code, attempt+1, retries+1)
                    time.sleep(2.0 * (attempt + 1))
                    continue
                if r.status_code == 404:
                    last_err = DiscoveryError(
                        "crt.sh HTTP 404 — Endpoint nicht erreichbar oder Query-Syntax abgelehnt."
                    )
                    time.sleep(1.0)
                    continue
                r.raise_for_status()
                entries = r.json()
                break  # success
        except DiscoveryError:
            raise
        except Exception as e:  # noqa: BLE001
            last_err = e
            log.warning("crt.sh query failed for %r (attempt %d): %s",
                        pattern, attempt + 1, e)
            time.sleep(1.0 * (attempt + 1))

    if not entries and last_err:
        raise DiscoveryError(str(last_err))

    # Aggregation: pro Root-Domain {cert_count, sans}
    roots: dict[str, ProspectResult] = {}
    for entry in entries:
        name_val = entry.get("name_value", "")
        # name_value kann mehrere SANs per Newline enthalten
        for raw in name_val.replace("\\n", "\n").splitlines():
            root = _extract_root(raw, expected_tld=tld)
            if not root:
                continue
            # Schreibweise muss das Keyword beinhalten (sonst zu viel rauschen)
            if keyword not in root:
                continue
            if root not in roots:
                roots[root] = ProspectResult(domain=root)
            roots[root].cert_count += 1
            if raw and raw not in roots[root].seen_sans and len(roots[root].seen_sans) < 3:
                roots[root].seen_sans.append(raw.strip())
            if len(roots) >= limit:
                break
        if len(roots) >= limit:
            break

    # Sortieren: meiste Zertifikate zuerst (aktive Domains zeigen oft mehr)
    return sorted(roots.values(), key=lambda r: -r.cert_count)[:limit]


def check_dmarc_for_prospects(prospects: list[ProspectResult]) -> None:
    """Mutiert die Liste: setzt has_dmarc pro Domain."""
    for p in prospects:
        try:
            p.has_dmarc = has_dmarc_record(p.domain)
        except Exception:  # noqa: BLE001
            p.has_dmarc = None
