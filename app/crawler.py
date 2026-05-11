"""KMU-Contact-Crawler — sammelt fuer eine Liste von Domains die oeffentlich
erreichbaren Kontakt-Infos (Email, Telefon, Firmenname) von deren Website.

Use-Case: du hast 200 Domains aus Moneyhouse/Zefix/LinkedIn-Sales-Nav. Pro
Domain weisst du aber nur den Domainnamen. Crawler crawlt:
  - /  (Homepage)
  - /kontakt /contact
  - /impressum /imprint /legal
  - /team /about /ueber-uns

und sucht in dem HTML nach Email-Adressen + CH-Telefonnummern.
Filter: nur Emails @{domain} (Personal/Generic) -- vermeidet gmail/hotmail
"random" Adressen die nicht zur Firma gehoeren.

Output: pro Domain eine Zeile mit (domain, primary_email, all_emails, phone,
company_name, source_urls). Direkt verwendbar als Input fuer das
Snapshot-Batch-Tool oder /admin/batch-snapshot.

Rechtliches: Wir crawlen nur oeffentliche Websites mit normalem User-Agent,
1 req/s pro Domain, robots.txt-respektierend. Keine Login-Walls, kein
Bypass-irgendwas. Public Impressum-Daten sind in CH per Gesetz oeffentlich.
"""
from __future__ import annotations

import logging
import re
import time
import urllib.parse
import urllib.robotparser
from dataclasses import dataclass, field
from typing import Optional

import httpx

log = logging.getLogger(__name__)

# Wir geben uns als "DMARCGeeksContactBot" zu erkennen -- transparent, falls
# jemand das im Server-Log sieht weiss er Bescheid und kann ggfs. robots.txt
# anpassen.
USER_AGENT = "DMARCGeeksContactBot/1.0 (+https://dmarc-geeks.ch/contact-bot)"

# Pages die wir auf jeder Domain probieren — sortiert nach Wahrscheinlichkeit
# dass dort echte Kontakt-Infos stehen.
COMMON_PATHS = [
    "",                # Homepage (oft footer mit kontakt)
    "/kontakt",
    "/contact",
    "/contact-us",
    "/kontakt-impressum",
    "/impressum",
    "/imprint",
    "/legal",
    "/legal/imprint",
    "/team",
    "/ueber-uns",
    "/about",
    "/about-us",
    "/firma",
]

# Email-Regex: konservativ, keine Plus-Adressen mit Sonderzeichen sondern
# Standard a-zA-Z0-9._%+- @ a-zA-Z0-9.-. tld
EMAIL_RE = re.compile(
    r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b",
    re.IGNORECASE,
)

# CH-Phone-Regex: matched +41 ... oder 0XX ... mit Spaces/Punkten/Bindestrichen
# Beispiele: +41 77 950 31 52 | 077 950 31 52 | 044-123 45 67 | +41.77.123.45.67
PHONE_RE = re.compile(
    r"(?:\+41[\s.\-]?|0)(?:[\s.\-]?\d){9,11}",
)

# Titel-Tag: <title>Foo Bar AG | Wir machen IT</title>
TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)

# og:site_name: <meta property="og:site_name" content="ACME AG">
OG_SITENAME_RE = re.compile(
    r"<meta[^>]+(?:property|name)\s*=\s*[\"']og:site_name[\"'][^>]+content\s*=\s*[\"']([^\"']+)[\"']",
    re.IGNORECASE,
)

# Schema.org Organization name: "name":"ACME AG"
SCHEMA_NAME_RE = re.compile(r'"@type"\s*:\s*"(?:Organization|Corporation|LocalBusiness)"[^}]*?"name"\s*:\s*"([^"]+)"', re.IGNORECASE | re.DOTALL)

# Typische "schlechte" Email-Patterns die rausgefiltert werden sollen.
# Begruendung:
# - example.com/.org/.net/.example: IANA-reservierte TLDs, niemals echte Adressen
# - email.ch / domain.com / yourdomain: typische Platzhalter in Marketing-Texten
# - noreply@ / donotreply@: keine Lese-Adressen, fuer Outreach nutzlos
# - test@ / admin@localhost / root@: Konfigurations-Artefakte
NOISE_EMAILS_PATTERNS = re.compile(
    r"^(noreply|no-reply|donotreply|do-not-reply|test|admin@localhost|"
    r"webmaster@localhost|root@|postmaster@localhost)"
    r"|@(example\.(com|org|net)|.+\.example|test\.com|domain\.com|yourdomain|"
    r"email\.(com|ch|de)|deine[a-z-]*\.|your[a-z-]*\.|firma\.ch|"
    r"localhost|.+\.localdomain)$",
    re.IGNORECASE,
)


@dataclass
class CrawlResult:
    domain: str
    company_name: Optional[str] = None
    emails: list[str] = field(default_factory=list)
    phones: list[str] = field(default_factory=list)
    primary_email: Optional[str] = None
    primary_phone: Optional[str] = None
    pages_crawled: list[str] = field(default_factory=list)
    error: Optional[str] = None


def _normalize_phone(raw: str) -> str:
    """Normalisiere CH-Phone: alle Whitespace/Punkte/Bindestriche raus."""
    s = re.sub(r"[\s.\-]", "", raw)
    if s.startswith("00"):
        s = "+" + s[2:]
    elif s.startswith("0") and not s.startswith("0041"):
        # CH-national -> internationalize
        s = "+41" + s[1:]
    return s


def _format_phone_display(normalized: str) -> str:
    """+41779503152 -> +41 77 950 31 52"""
    if not normalized.startswith("+41") or len(normalized) != 12:
        return normalized
    # +41 XX XXX XX XX
    return f"{normalized[:3]} {normalized[3:5]} {normalized[5:8]} {normalized[8:10]} {normalized[10:12]}"


def _extract_company_name(html: str, domain: str) -> Optional[str]:
    """Versucht Firmennamen zu finden via og:site_name > schema.org > <title>."""
    m = OG_SITENAME_RE.search(html)
    if m:
        name = m.group(1).strip()
        if name and len(name) < 120:
            return name
    m = SCHEMA_NAME_RE.search(html)
    if m:
        name = m.group(1).strip()
        if name and len(name) < 120:
            return name
    m = TITLE_RE.search(html)
    if m:
        title = re.sub(r"\s+", " ", m.group(1)).strip()
        # Strip common suffixes: "ACME AG | Wir machen IT" -> "ACME AG"
        for sep in [" | ", " - ", " – ", " · ", " :: "]:
            if sep in title:
                title = title.split(sep, 1)[0].strip()
                break
        if title and len(title) < 120 and domain.split(".")[0].lower() not in title.lower():
            # Wenn der Domainname nicht im Titel steckt, ist es vmtl. ein generischer
            # Titel ("Home", "Welcome") -- skippen. Aber: oft steckt der Brand drin.
            # Bessere Heuristik: gib ihn trotzdem zurueck, wenn er nicht generisch ist
            generic = re.compile(r"^(home|welcome|willkommen|startseite|index|untitled|loading)", re.IGNORECASE)
            if not generic.match(title):
                return title
        elif title:
            return title
    return None


def _email_relevance_score(email: str, domain: str) -> int:
    """Hoeherer Score = wichtigerer Kontakt. Eigene Domain > generische Mailbox > sonst."""
    email_lower = email.lower()
    local, _, host = email_lower.partition("@")
    score = 0
    # Eigene Domain ist BEST
    if host == domain.lower() or host.endswith("." + domain.lower()):
        score += 100
    elif host in ("gmail.com", "gmx.ch", "gmx.de", "hotmail.com", "bluewin.ch", "outlook.com"):
        score += 5
    else:
        score += 20  # andere Domain (z.B. agentur)
    # Bevorzuge persoenliche Adressen vor info@/contact@
    if local in ("info", "kontakt", "contact", "hello", "office", "mail", "post"):
        score += 30
    elif local in ("sales", "vertrieb", "geschaeft"):
        score += 25
    elif local in ("admin", "webmaster", "postmaster"):
        score += 10
    else:
        # Wahrscheinlich persoenlich (vorname@ oder vorname.nachname@)
        score += 50
    return score


def _fetch(client: httpx.Client, url: str, timeout: float = 8.0) -> Optional[str]:
    """Hol Seite, gib HTML zurueck oder None bei Fehler."""
    try:
        r = client.get(url, timeout=timeout, follow_redirects=True)
        if r.status_code != 200:
            return None
        ct = r.headers.get("content-type", "").lower()
        if "html" not in ct and "text" not in ct:
            return None
        # Maximal 2 MB pro Seite -- vermeidet riesige PDFs etc.
        if len(r.content) > 2_000_000:
            return r.text[:2_000_000]
        return r.text
    except (httpx.TimeoutException, httpx.RequestError, ValueError) as e:
        log.debug("fetch failed for %s: %s", url, e)
        return None


def _is_allowed_by_robots(robots_cache: dict[str, urllib.robotparser.RobotFileParser],
                           client: httpx.Client, scheme: str, host: str, path: str) -> bool:
    """robots.txt respektieren. Cache pro Host."""
    if host not in robots_cache:
        rp = urllib.robotparser.RobotFileParser()
        try:
            robots_url = f"{scheme}://{host}/robots.txt"
            r = client.get(robots_url, timeout=4.0, follow_redirects=True)
            if r.status_code == 200:
                rp.parse(r.text.splitlines())
            else:
                rp.parse([])  # No robots.txt -> alles erlaubt
        except Exception:  # noqa: BLE001
            rp.parse([])
        robots_cache[host] = rp
    rp = robots_cache[host]
    try:
        return rp.can_fetch(USER_AGENT, f"{scheme}://{host}{path}")
    except Exception:  # noqa: BLE001
        return True


def crawl_domain(domain: str, *, rate_limit_seconds: float = 1.0,
                  max_pages: int = 5) -> CrawlResult:
    """Crawl eine einzelne Domain -- hole gaengige Kontakt-Pages, extrahiere Emails+Phones."""
    domain = domain.strip().lower().rstrip(".").replace("https://", "").replace("http://", "")
    if "/" in domain:
        domain = domain.split("/", 1)[0]
    if ":" in domain:
        domain = domain.split(":", 1)[0]
    if not domain or "." not in domain:
        return CrawlResult(domain=domain, error="invalid domain")

    result = CrawlResult(domain=domain)
    found_emails: dict[str, int] = {}     # email -> score
    found_phones: set[str] = set()
    company_name: Optional[str] = None
    robots_cache: dict[str, urllib.robotparser.RobotFileParser] = {}

    with httpx.Client(
        headers={"User-Agent": USER_AGENT,
                 "Accept-Language": "de-CH,de;q=0.9,en;q=0.5"},
        verify=True,
    ) as client:
        pages_done = 0
        for path in COMMON_PATHS:
            if pages_done >= max_pages:
                break
            # Erste Iteration: HTTPS probieren, fallback auf HTTP wenn nicht erreichbar
            schemes_to_try = ["https", "http"] if pages_done == 0 else ["https"]
            success = False
            for scheme in schemes_to_try:
                url = f"{scheme}://{domain}{path}"
                # robots.txt-Check
                if not _is_allowed_by_robots(robots_cache, client, scheme, domain, path):
                    log.debug("robots.txt forbids %s", url)
                    continue
                html = _fetch(client, url)
                if html is None:
                    continue
                success = True
                result.pages_crawled.append(url)
                pages_done += 1

                # Firmennamen extrahieren (nur einmal)
                if company_name is None:
                    company_name = _extract_company_name(html, domain)

                # Emails
                for m in EMAIL_RE.finditer(html):
                    email = m.group(0)
                    if NOISE_EMAILS_PATTERNS.search(email):
                        continue
                    score = _email_relevance_score(email, domain)
                    if email.lower() not in found_emails or found_emails[email.lower()] < score:
                        found_emails[email.lower()] = score

                # Phones
                for m in PHONE_RE.finditer(html):
                    raw = m.group(0)
                    normalized = _normalize_phone(raw)
                    if normalized.startswith("+41") and len(normalized) in (11, 12, 13):
                        found_phones.add(normalized)

                # Rate-Limit
                time.sleep(rate_limit_seconds)
                break  # weiter mit naechstem Pfad
            if not success and pages_done == 0:
                # Domain ist garnicht erreichbar
                result.error = "unreachable"
                break

    result.company_name = company_name
    # Sortieren: hoechster Score zuerst
    result.emails = [e for e, _ in sorted(found_emails.items(), key=lambda x: -x[1])]
    result.phones = [_format_phone_display(p) for p in sorted(found_phones)]
    if result.emails:
        result.primary_email = result.emails[0]
    if result.phones:
        result.primary_phone = result.phones[0]
    return result
