"""Hetzner Cloud DNS API client (api.hetzner.cloud/v1, RRSet-based).

Used for two purposes:

1. **External-Destination-Authorization records** — per kunden-Domain auto-create
   `<kunde-domain>._report._dmarc.<our-zone>` so receiving MTAs know we're
   authorized to receive RUA reports for that domain.

2. **CNAME-Delegation managed-DMARC** — per kunden-Domain we create a TXT record
   under our zone with the actual DMARC policy. The kunden-Domain just needs
   one CNAME pointing at our managed name; we change the policy without
   touching the customer's DNS.

API docs: https://docs.hetzner.cloud/reference/cloud — see "Zones" section.
Auth: Bearer token from https://console.hetzner.cloud (Project → Security → API Tokens).
"""
from __future__ import annotations

import logging
from typing import Optional

import httpx

log = logging.getLogger(__name__)

API_BASE = "https://api.hetzner.cloud/v1"
DEFAULT_TTL = 3600


class HetznerDNSError(Exception):
    pass


class HetznerDNS:
    """Wrapper for Hetzner Cloud DNS (RRSet-based API).

    Note: zones are addressed by `name` (or numeric `id`). RRSets are addressed
    by `(zone, name, type)` — the API auto-merges multiple records with the
    same (name, type) into one set.
    """

    def __init__(self, token: str, *, timeout: float = 10.0):
        if not token:
            raise HetznerDNSError("API token is empty")
        self._client = httpx.Client(
            base_url=API_BASE,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            timeout=timeout,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    # --- Zones ----------------------------------------------------------------

    def list_zones(self) -> list[dict]:
        r = self._client.get("/zones", params={"per_page": 50})
        if r.status_code != 200:
            raise HetznerDNSError(f"list_zones {r.status_code}: {r.text[:200]}")
        return r.json().get("zones", [])

    def find_zone(self, name: str) -> Optional[dict]:
        """Find a zone by exact apex-name (e.g. 'dmarc-geeks.ch'). Uses GET /zones/{name}."""
        name = name.strip(".").lower()
        r = self._client.get(f"/zones/{name}")
        if r.status_code == 200:
            return r.json().get("zone")
        if r.status_code == 404:
            return None
        # Fall back to list-and-search for unexpected status codes
        try:
            for z in self.list_zones():
                if z.get("name", "").lower() == name:
                    return z
        except HetznerDNSError:
            pass
        return None

    # --- RRSets (Records) -----------------------------------------------------

    def list_rrsets(self, zone_name: str, *, name_filter: Optional[str] = None,
                    type_filter: Optional[str] = None) -> list[dict]:
        params: dict = {"per_page": 200}
        if name_filter:
            params["name"] = name_filter
        if type_filter:
            params["type"] = type_filter
        r = self._client.get(f"/zones/{zone_name}/rrsets", params=params)
        if r.status_code != 200:
            raise HetznerDNSError(f"list_rrsets {r.status_code}: {r.text[:200]}")
        return r.json().get("rrsets", [])

    def get_rrset(self, zone_name: str, rr_name: str, rr_type: str) -> Optional[dict]:
        r = self._client.get(f"/zones/{zone_name}/rrsets/{rr_name}/{rr_type}")
        if r.status_code == 200:
            return r.json().get("rrset")
        if r.status_code == 404:
            return None
        raise HetznerDNSError(f"get_rrset {r.status_code}: {r.text[:200]}")

    def upsert_record(self, zone_name: str, name: str, rtype: str, value: str,
                      ttl: int = DEFAULT_TTL) -> dict:
        """Idempotent create-or-update for a single-value rrset.

        Hetzner Cloud DNS unterscheidet harsch:
        - existiert NICHT → POST /zones/{zone}/rrsets   (create)
        - existiert SCHON → POST /zones/{zone}/rrsets/{name}/{type}/actions/set_records  (replace)
        Ein generisches PUT geht nur für TTL/Labels-Edits, nicht für Records.

        Wir prüfen erst per GET ob der RRSet existiert, dann den richtigen Pfad.
        """
        # TXT values must be RFC1035-quoted ("...")
        if rtype.upper() == "TXT" and not (value.startswith('"') and value.endswith('"')):
            wire_value = f'"{value}"'
        else:
            wire_value = value

        existing = self.get_rrset(zone_name, name, rtype)

        if existing is None:
            # Create new
            body = {
                "name": name,
                "type": rtype,
                "ttl": ttl,
                "records": [{"value": wire_value}],
            }
            r = self._client.post(f"/zones/{zone_name}/rrsets", json=body)
            if r.status_code not in (200, 201):
                raise HetznerDNSError(f"create_rrset {r.status_code}: {r.text[:300]}")
            return r.json().get("rrset", {})

        # Replace records on existing rrset
        body = {"records": [{"value": wire_value}]}
        r = self._client.post(
            f"/zones/{zone_name}/rrsets/{name}/{rtype}/actions/set_records",
            json=body,
        )
        if r.status_code not in (200, 201):
            raise HetznerDNSError(f"set_records {r.status_code}: {r.text[:300]}")
        return r.json().get("rrset", existing)

    def delete_record_by_name(self, zone_name: str, name: str, rtype: str) -> bool:
        r = self._client.delete(f"/zones/{zone_name}/rrsets/{name}/{rtype}")
        return r.status_code in (200, 201, 204)


# --- Convenience helpers for our DMARC use-cases ------------------------------

def authorization_record_name(customer_domain: str, our_zone: str) -> str:
    """Compose the external-destination-authorization record name.

    Hetzner Cloud DNS expects names *relative to the zone* (e.g.
    `kundedomain.ch._report._dmarc`).
    """
    cust = customer_domain.strip(".").lower()
    return f"{cust}._report._dmarc"


def delegation_record_name(customer_domain: str, our_zone: str) -> str:
    """Composes the relative name where we host the customer's DMARC policy.

    For `kundedomain.ch` under our zone `dmarc-geeks.ch`, returns
    `kundedomain-ch.dmarc` (relative name) — the customer points
    `_dmarc.kundedomain.ch CNAME kundedomain-ch.dmarc.dmarc-geeks.ch.`.
    """
    cust = customer_domain.strip(".").lower().replace(".", "-")
    return f"{cust}.dmarc"


def delegation_target_fqdn(customer_domain: str, our_zone: str) -> str:
    """The FQDN the customer's CNAME should point at."""
    return f"{delegation_record_name(customer_domain, our_zone)}.{our_zone.strip('.')}"


def configured() -> bool:
    """Return True iff Hetzner DNS is fully configured (token + zone)."""
    from .config import get_settings
    s = get_settings()
    return bool((s.hetzner_dns_token or "").strip() and (s.hetzner_dns_zone or "").strip())


def get_client() -> Optional[HetznerDNS]:
    """Return a ready client, or None if not configured."""
    from .config import get_settings
    s = get_settings()
    token = (s.hetzner_dns_token or "").strip()
    if not token:
        return None
    return HetznerDNS(token)


def get_managed_zone_name() -> str:
    """Return the configured zone name (e.g. 'dmarc-geeks.ch'), or empty string."""
    from .config import get_settings
    return (get_settings().hetzner_dns_zone or "").strip(".").lower()
