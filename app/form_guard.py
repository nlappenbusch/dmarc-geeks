"""Bot-Schutz fuer oeffentliche Formulare (Kontakt, Snapshot).

Honeypot und IP-Rate-Limit allein reichen nicht: Bots rotieren IPs, lassen das
Honeypot-Feld leer und tragen fremde Adressen ein -- die App verschickt dann
Mails an Leute, die nie etwas angefragt haben (Backscatter, Spam-Ruf der IP).

Darum zusaetzlich:
- Zeitfalle: Das Formular traegt einen signierten Zeitstempel. Wer schneller als
  MIN_AGE abschickt, ohne gueltigen Stempel kommt oder einen alten Stempel
  wiederverwendet, ist ein Bot.
- Globale Obergrenze fuer Mails an vom Besucher eingegebene Adressen, egal von
  welcher IP.
"""
from __future__ import annotations

from fastapi import Request
from itsdangerous import BadSignature, SignatureExpired, TimestampSigner

from .config import get_settings
from .rate_limit import TokenBucket

MIN_AGE = 3          # Sekunden -- Menschen brauchen laenger zum Ausfuellen
MAX_AGE = 2 * 3600   # Formular darf zwei Stunden offen bleiben

# Hoechstens 20 Mails pro Stunde an eingegebene Adressen, ueber alle IPs.
outbound_limiter = TokenBucket(capacity=20, refill_per_second=20 / 3600)


def _signer() -> TimestampSigner:
    return TimestampSigner(get_settings().secret_key, salt="form-guard")


def form_token() -> str:
    """Signierter Zeitstempel fuer das versteckte Feld `ft`."""
    return _signer().sign(b"f").decode()


def token_ok(token: str | None) -> bool:
    if not token:
        return False
    signer = _signer()
    try:
        signer.unsign(token, max_age=MAX_AGE)
    except (BadSignature, SignatureExpired):
        return False
    try:
        signer.unsign(token, max_age=MIN_AGE)
    except SignatureExpired:
        return True   # aelter als MIN_AGE -- so soll es sein
    except BadSignature:
        return False
    return False      # juenger als MIN_AGE -- zu schnell fuer einen Menschen


def client_ip(request: Request) -> str:
    """Echte Besucher-IP hinter NPM/Reverse-Proxy."""
    xff = request.headers.get("x-forwarded-for", "")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else "-"
