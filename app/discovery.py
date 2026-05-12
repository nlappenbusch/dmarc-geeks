"""Prospect-Discovery — Schweizer KMU finden über mehrere Quellen.

Primäre Quelle: OpenStreetMap Overpass API.
- Strukturiert: Firmenname + Website + Telefon + Stadt + Kanton
- Kostenlos, keine API-Keys, stabil (im Vergleich zu crt.sh)
- Branchen-Tagging über OSM-Tags (office=accountant, healthcare=doctor, …)

Fallback-Quelle: crt.sh (Certificate-Transparency-Logs).
- Für Custom-Keyword-Suchen wenn OSM nicht greift
- Notorisch flaky (502/504), aber breite Abdeckung wenn's läuft

Beide Quellen können sich gegenseitig ergänzen. Default ist OSM.
"""
from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from typing import Optional

import httpx

from .dns_utils import has_dmarc_record

log = logging.getLogger(__name__)

OVERPASS_API = "https://overpass-api.de/api/interpreter"
CRT_SH_API = "https://crt.sh/"
USER_AGENT = "DMARCGeeksProspectBot/1.0 (+https://dmarc-geeks.ch)"


class DiscoveryError(Exception):
    """Discovery-Source ist temporär down oder Query liefert keine Daten."""


# ============================================================================
# Branchen-Presets — primär OSM-basiert (zuverlässig + strukturierte Daten)
# ============================================================================
#
# osm_filter ist eine OSM-Tag-Spezifikation in Overpass-Syntax. Mehrere Tags
# in einem Preset werden als Union (OR) ausgewertet — z.B. "office=accountant"
# OR "office=tax_advisor" für Treuhänder.
#
# crt_keyword ist der Fallback wenn OSM keine Treffer hat (Custom-Domains
# ohne OSM-Eintrag finden).

BRANCH_PRESETS = [
    {
        "key": "treuhand",
        "label": "Treuhand / Buchhaltung",
        "icon": "📊",
        "osm_filter": ['office="accountant"', 'office="tax_advisor"', 'office="financial"'],
        "crt_keyword": "treuhand",
        "rationale": "Sensible Finanzdaten · Compliance-getrieben · Rechnungsversand",
    },
    {
        "key": "anwalt",
        "label": "Anwaltskanzleien",
        "icon": "⚖️",
        "osm_filter": ['office="lawyer"', 'office="notary"'],
        "crt_keyword": "kanzlei",
        "rationale": "Mandantengeheimnis · CEO-Fraud-Ziel · viele Mailgespräche",
    },
    {
        "key": "versicherung",
        "label": "Versicherungs-Broker",
        "icon": "🛡️",
        "osm_filter": ['office="insurance"'],
        "crt_keyword": "versicher",
        "rationale": "Kundenrisiken · sensible Daten · regulatorische Pflicht",
    },
    {
        "key": "arzt",
        "label": "Arzt-Praxen",
        "icon": "⚕️",
        "osm_filter": ['healthcare="doctor"', 'amenity="doctors"'],
        "crt_keyword": "praxis",
        "rationale": "Patientendaten · HIN-Anschluss · DSG sensible Branche",
    },
    {
        "key": "zahnarzt",
        "label": "Zahnarzt-Praxen",
        "icon": "🦷",
        "osm_filter": ['healthcare="dentist"', 'amenity="dentist"'],
        "crt_keyword": "zahnarzt",
        "rationale": "Patientendaten · viele Termin-Mails · oft kleine Teams",
    },
    {
        "key": "klinik",
        "label": "Kliniken / Spitäler",
        "icon": "🏥",
        "osm_filter": ['amenity="hospital"', 'amenity="clinic"', 'healthcare="hospital"', 'healthcare="clinic"'],
        "crt_keyword": "klinik",
        "rationale": "DSG · BIMI sinnvoll · viele Schnittstellen",
    },
    {
        "key": "physio",
        "label": "Physiotherapie",
        "icon": "🩹",
        "osm_filter": ['healthcare="physiotherapist"', 'healthcare="physiotherapy"'],
        "crt_keyword": "physio",
        "rationale": "Patientendaten · oft Kleinstpraxen mit IT-Hosting beim Webdesigner",
    },
    {
        "key": "it",
        "label": "IT-Dienstleister",
        "icon": "💻",
        "osm_filter": ['office="it"', 'office="telecommunication"'],
        "crt_keyword": "informatik",
        "rationale": "Selbst Anbieter — peinlich wenn Mail-Setup schlecht",
    },
    {
        "key": "architekt",
        "label": "Architekturbüros",
        "icon": "📐",
        "osm_filter": ['office="architect"'],
        "crt_keyword": "architekt",
        "rationale": "Familienbetriebe · Rechnungsversand · oft Outsourcing-IT",
    },
    {
        "key": "immobilien",
        "label": "Immobilien-Verwaltung",
        "icon": "🏘️",
        "osm_filter": ['office="estate_agent"', 'office="real_estate_agent"'],
        "crt_keyword": "immobil",
        "rationale": "Mietverträge per Mail · Rechnungen · große Kundenbasis",
    },
    {
        "key": "berater",
        "label": "Unternehmens-Berater",
        "icon": "🧠",
        "osm_filter": ['office="consulting"', 'office="company"'],
        "crt_keyword": "consulting",
        "rationale": "Sales-getrieben · viel Kalt-Outreach · Spoofing-Ziel",
    },
    {
        "key": "spedition",
        "label": "Spedition / Logistik",
        "icon": "🚚",
        "osm_filter": ['office="logistician"', 'industrial="logistics"'],
        "crt_keyword": "spedition",
        "rationale": "Internationale Mails · oft alte Mailsetups",
    },
]


# Schweizer Kantone für Region-Filter
SWISS_CANTONS = [
    ("", "Ganze Schweiz"),
    ("CH-ZH", "Zürich"),
    ("CH-BE", "Bern"),
    ("CH-LU", "Luzern"),
    ("CH-UR", "Uri"),
    ("CH-SZ", "Schwyz"),
    ("CH-OW", "Obwalden"),
    ("CH-NW", "Nidwalden"),
    ("CH-GL", "Glarus"),
    ("CH-ZG", "Zug"),
    ("CH-FR", "Fribourg"),
    ("CH-SO", "Solothurn"),
    ("CH-BS", "Basel-Stadt"),
    ("CH-BL", "Basel-Landschaft"),
    ("CH-SH", "Schaffhausen"),
    ("CH-AR", "Appenzell A.Rh."),
    ("CH-AI", "Appenzell I.Rh."),
    ("CH-SG", "St. Gallen"),
    ("CH-GR", "Graubünden"),
    ("CH-AG", "Aargau"),
    ("CH-TG", "Thurgau"),
    ("CH-TI", "Ticino"),
    ("CH-VD", "Vaud"),
    ("CH-VS", "Valais"),
    ("CH-NE", "Neuchâtel"),
    ("CH-GE", "Geneva"),
    ("CH-JU", "Jura"),
]


@dataclass
class ProspectResult:
    domain: str
    company_name: Optional[str] = None
    website: Optional[str] = None
    phone: Optional[str] = None
    city: Optional[str] = None
    canton: Optional[str] = None
    osm_type: Optional[str] = None    # node/way/relation
    osm_id: Optional[int] = None
    has_dmarc: Optional[bool] = None
    # Legacy crt.sh-Felder
    cert_count: int = 0
    seen_sans: list[str] = field(default_factory=list)
    error: Optional[str] = None


# ============================================================================
# OpenStreetMap / Overpass — primäre Quelle
# ============================================================================

def _domain_from_url(url: str) -> Optional[str]:
    """Aus 'https://www.example.ch/path' -> 'example.ch'."""
    if not url:
        return None
    u = url.strip().lower()
    if u.startswith("//"):
        u = "https:" + u
    if not u.startswith(("http://", "https://")):
        u = "http://" + u
    # einfach genug: schneide schema + ggf. www. + path/query
    u = re.sub(r"^https?://", "", u)
    u = u.split("/", 1)[0].split("?", 1)[0].split("#", 1)[0]
    if u.startswith("www."):
        u = u[4:]
    if ":" in u:
        u = u.split(":", 1)[0]
    if not u or "." not in u or " " in u:
        return None
    return u


def _normalize_phone_ch(raw: str) -> Optional[str]:
    """OSM-Phone -> +41 XX XXX XX XX wo möglich."""
    if not raw:
        return None
    s = re.sub(r"[\s\-./()]+", "", raw)
    if s.startswith("00"):
        s = "+" + s[2:]
    if s.startswith("0") and not s.startswith("00"):
        s = "+41" + s[1:]
    if not s.startswith("+"):
        s = "+" + s
    if not re.match(r"^\+\d{8,15}$", s):
        return raw  # nichts erkannt -> Rohwert
    # Pretty-print für +41-Nummern
    if s.startswith("+41") and len(s) == 12:
        return f"{s[:3]} {s[3:5]} {s[5:8]} {s[8:10]} {s[10:12]}"
    return s


def _build_overpass_query(osm_filters: list[str], canton: str = "",
                          limit: int = 200, timeout: int = 25) -> str:
    """Baue eine Overpass-QL-Query für eine Liste von OSM-Tag-Filtern.

    Mehrere Filter werden als Union (OR) ausgewertet. Wenn canton gesetzt,
    Suche nur in diesem Bundesland (ISO3166-2). Sonst ganze Schweiz."""
    if canton:
        area_clause = f'area["ISO3166-2"="{canton}"]->.s;'
    else:
        area_clause = 'area["ISO3166-1"="CH"]->.s;'
    union = "\n  ".join(f'nwr[{f}](area.s);' for f in osm_filters)
    return (
        f'[out:json][timeout:{timeout}];\n'
        f'{area_clause}\n'
        f'(\n  {union}\n);\n'
        f'out tags {limit};\n'
    )


def fetch_osm_prospects(osm_filters: list[str], *, canton: str = "",
                        limit: int = 200, timeout: float = 35.0,
                        retries: int = 2) -> list[ProspectResult]:
    """Frag OSM-Overpass nach allen POIs die einen der osm_filters matchen.

    Filtert + dedupliziert pro Root-Domain. Gibt Einträge OHNE Website
    nicht zurück (für unseren Mail-Workflow nutzlos)."""
    if not osm_filters:
        return []

    query = _build_overpass_query(osm_filters, canton=canton, limit=min(limit * 2, 500))
    last_err: Optional[Exception] = None
    data: Optional[dict] = None

    for attempt in range(retries + 1):
        try:
            with httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=timeout) as c:
                r = c.post(OVERPASS_API, data={"data": query})
                if r.status_code == 429:
                    last_err = DiscoveryError("Overpass rate-limit (429) — kurz warten.")
                    time.sleep(3.0 * (attempt + 1))
                    continue
                if r.status_code in (502, 503, 504):
                    last_err = DiscoveryError(
                        f"Overpass HTTP {r.status_code} — Server überlastet, retry läuft …"
                    )
                    time.sleep(2.0 * (attempt + 1))
                    continue
                r.raise_for_status()
                data = r.json()
                break
        except DiscoveryError:
            raise
        except Exception as e:  # noqa: BLE001
            last_err = e
            log.warning("overpass query failed (attempt %d): %s", attempt + 1, e)
            time.sleep(1.5 * (attempt + 1))

    if not data:
        raise DiscoveryError(str(last_err) if last_err else "Overpass keine Antwort")

    elements = data.get("elements", []) or []
    by_domain: dict[str, ProspectResult] = {}

    for el in elements:
        tags = el.get("tags") or {}
        # Website prio: website > contact:website > url
        website = (tags.get("website") or tags.get("contact:website")
                    or tags.get("url") or "")
        domain = _domain_from_url(website)
        if not domain:
            continue
        # Schweizer Domain bevorzugen (.ch / .li) — andere TLDs (.com etc)
        # akzeptieren wir auch, sind oft Schweizer Firmen mit globaler Domain
        if domain in by_domain:
            continue  # erster Eintrag gewinnt

        name = (tags.get("name") or tags.get("operator")
                 or tags.get("brand") or domain)
        phone = (tags.get("phone") or tags.get("contact:phone")
                  or tags.get("contact:mobile") or "")
        city = (tags.get("addr:city") or tags.get("addr:place") or "")

        # ISO3166-2 aus Tags ableiten (selten direkt vorhanden)
        canton_tag = (tags.get("addr:state") or tags.get("addr:province") or "")

        by_domain[domain] = ProspectResult(
            domain=domain,
            company_name=name.strip()[:200] if name else None,
            website=website.strip()[:300] if website else None,
            phone=_normalize_phone_ch(phone) if phone else None,
            city=city.strip()[:120] if city else None,
            canton=canton_tag.strip()[:80] if canton_tag else (canton or None),
            osm_type=el.get("type"),
            osm_id=el.get("id"),
        )
        if len(by_domain) >= limit:
            break

    return list(by_domain.values())


# ============================================================================
# crt.sh — Fallback für Custom-Keyword-Suche
# ============================================================================

def _extract_root(host: str, expected_tld: str = "") -> Optional[str]:
    """Aus einem SAN-Hostname die Root-Domain ableiten."""
    h = host.strip().lower().rstrip(".")
    if h.startswith("*."):
        h = h[2:]
    if not h or h.startswith("-") or h.endswith("-"):
        return None
    if "/" in h or ":" in h or " " in h:
        return None
    NOISE = (
        "cloudfront.net", "azurewebsites.net", "azureedge.net",
        "amazonaws.com", "cloudapp.net", "elasticbeanstalk.com",
        "herokuapp.com", "github.io", "vercel.app", "netlify.app",
        "sharepoint.com", "onmicrosoft.com", "googleusercontent.com",
        "wpengine.com", "myshopify.com", "wixsite.com", "weebly.com",
        "squarespace.com", "rackspace.com", "fastly.net",
    )
    for n in NOISE:
        if h == n or h.endswith("." + n):
            return None
    parts = h.split(".")
    if len(parts) < 2:
        return None
    root = ".".join(parts[-2:])
    if expected_tld and not root.endswith("." + expected_tld.lstrip(".")):
        return None
    return root


def fetch_crtsh_prospects(keyword: str, tld: str = "ch", *, limit: int = 100,
                          timeout: float = 30.0,
                          retries: int = 2) -> list[ProspectResult]:
    """Fallback: crt.sh für freie Keyword-Suche."""
    keyword = (keyword or "").strip().lower()
    tld = (tld or "ch").strip().lower().lstrip(".")
    if not keyword or not re.match(r"^[a-z0-9.\-]+$", keyword):
        return []
    if not re.match(r"^[a-z0-9]+$", tld):
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
                    last_err = DiscoveryError(
                        f"crt.sh HTTP {r.status_code} (Server überlastet) — "
                        "passiert leider regelmäßig."
                    )
                    time.sleep(2.0 * (attempt + 1))
                    continue
                if r.status_code == 404:
                    last_err = DiscoveryError("crt.sh HTTP 404 — Endpoint down.")
                    time.sleep(1.0)
                    continue
                r.raise_for_status()
                entries = r.json()
                break
        except DiscoveryError:
            raise
        except Exception as e:  # noqa: BLE001
            last_err = e
            time.sleep(1.0 * (attempt + 1))

    if not entries and last_err:
        raise DiscoveryError(str(last_err))

    roots: dict[str, ProspectResult] = {}
    for entry in entries:
        name_val = entry.get("name_value", "")
        for raw in name_val.replace("\\n", "\n").splitlines():
            root = _extract_root(raw, expected_tld=tld)
            if not root or keyword not in root:
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

    return sorted(roots.values(), key=lambda r: -r.cert_count)[:limit]


# Legacy-Alias damit alte Aufrufer nicht brechen
def fetch_prospects(keyword: str, tld: str = "ch", *, limit: int = 100,
                    timeout: float = 30.0, retries: int = 2) -> list[ProspectResult]:
    return fetch_crtsh_prospects(keyword, tld, limit=limit, timeout=timeout, retries=retries)


def check_dmarc_for_prospects(prospects: list[ProspectResult]) -> None:
    for p in prospects:
        try:
            p.has_dmarc = has_dmarc_record(p.domain)
        except Exception:  # noqa: BLE001
            p.has_dmarc = None


def get_preset(key: str) -> Optional[dict]:
    for p in BRANCH_PRESETS:
        if p["key"] == key:
            return p
    return None
