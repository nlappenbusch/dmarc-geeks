# Roadmap

Sammlung von Erweiterungen, die später kommen sollen — bewusst noch nicht gebaut, weil sie Infrastruktur oder Aufwand erfordern, der jetzt nicht gerechtfertigt ist.

## CNAME-Delegation für DMARC (managed records via Hetzner DNS API)

**Wann:** Sobald ≥10 zahlende Kunden absehbar oder ein Pilotkunde danach fragt.

**Idee:** Statt jedem Kunden zu sagen *"Trag diesen TXT-Record bei dir ein und ändere ihn jedes Mal, wenn du `p=` ändern willst"*, hostet der Aggregator den eigentlichen TXT selbst. Kunde setzt einmalig:

```
_dmarc.kunde.de.   IN CNAME _kunde-de.dmarc.deine-firma.de.
```

Wir hosten unter `_kunde-de.dmarc.deine-firma.de` den echten DMARC-Record und können ihn jederzeit aus der UI ändern (z.&nbsp;B. `p=none` → `p=quarantine`).

### Architektur

**Backend-Auswahl: Hetzner DNS API.** Begründung:
- Kostenlos für Hetzner-Kunden, einfache REST-API (`https://dns.hetzner.com/api/v1/`)
- Token-Auth, gute Latenzen aus EU
- Native authoritative DNS (zwei Nameserver redundant)
- Keine Bindung an Cloudflare-Stack

**Komponenten:**
1. **DNS-Zone anlegen** — eine Subdomain unter eigener Domain, z.&nbsp;B. `dmarc.deine-firma.de`. Bei Hetzner als eigene Zone, oder als Subzone-Delegation der bestehenden Hauptzone.
2. **Service-Layer in der App** (`app/dns_backend.py`):
   ```python
   class DnsBackend(Protocol):
       def upsert_txt(self, name: str, value: str, ttl: int = 300) -> None: ...
       def delete_txt(self, name: str) -> None: ...
       def list_records(self, name: str) -> list[Record]: ...

   class HetznerDns(DnsBackend):
       def __init__(self, api_token: str, zone_id: str): ...
   ```
3. **Trigger:** Bei Domain-Anlage → CNAME-Anweisung dem Kunden zeigen. Bei Policy-Änderung in UI → `backend.upsert_txt(...)`. Bei Domain-Löschung → cleanup.
4. **Health-Check-Job (APScheduler, stündlich):** Für jede delegierte Domain prüfen:
   - Löst der CNAME beim Kunden korrekt auf?
   - Ist der TXT bei uns noch da und korrekt?
   - Bei Drift: Mail an Kunde + roter Banner in UI

### Neue Datenbank-Felder
- `domains.delegation_mode` — `none` (Default), `cname`
- `domains.dns_record_value` — der aktuelle TXT, wie er bei uns gehostet wird
- `domains.dns_last_check_at`, `dns_last_status`

### Risiken / Was vorher zu klären ist
- **Backup-Nameserver:** Hetzner liefert zwei eigene NS — ausreichend.
- **DNSSEC:** Hetzner unterstützt DNSSEC, aber der Kunde signiert sein Parent nicht — DNSSEC für die Delegation lässt sich erst dann abschließen, wenn der Kunde mitwirkt. Erstes Release: ohne DNSSEC, später nachziehen.
- **Rate-Limits der API:** Hetzner DNS-API hat Limits, die in der Doku stehen — bei vielen Domains batchen.
- **Operations-Pflicht:** Du wirst zu Mail-kritischer Infrastruktur. Ausfall deiner Hetzner-Zone = Kunde DMARC-broken. Monitoring + Notfall-Runbook **vorher** schreiben.
- **Schlüssel-Rotation:** Nicht relevant (DMARC ist nur TXT, keine Crypto).

### Aufwand-Schätzung
- Hetzner-Backend + Service-Layer: ~1 Tag
- UI für Policy-Wechsel + CNAME-Anleitung: ~0.5 Tag
- Health-Check-Job: ~0.5 Tag
- Tests + Doku: ~0.5 Tag
- **Total: ~2.5 Personentage** für eine erste lauffähige Version

## Was bewusst NICHT auf der Roadmap steht

- **DKIM-Schlüssel-Hosting:** Nur sinnvoll, wenn du selbst Mail-Relay bist. Ist eine andere Firma.
- **SPF-Delegation:** SPF unterstützt CNAMEs nicht sauber, und `include:` setzt sich beim 10-DNS-Lookup-Limit schnell durch. Mehr Schaden als Nutzen.
- **Stripe-Billing:** Erst, wenn echte Tarife stehen.
- **SAML/SSO:** Magic-Link reicht für 95 % der Use-Cases. SSO wenn Enterprise-Kunde danach fragt.
- **Subdomains pro Tenant** (`kunde.dmarc.deine-firma.de`): Hübsch, aber DNS-Wildcard + Reverse-Proxy + TLS-Cert-Automation ist Aufwand. Erst, wenn Whitelabeling Geld bringt.

## Andere "später"-Ideen

- **Welt-Karte für Source-IPs** mit GeoIP — braucht MaxMind-GeoLite2-Lizenz, einen lokalen mmdb-Download und einen Sync-Job. Lohnt sich erst, wenn jemand danach fragt.
- **Slack/Teams-Integration** für Spike-Alerts — erweiterbar über Webhooks (haben wir).
- **PDF-Export wöchentlicher Report** — Reports als PDF an Stakeholder.
- **TLS-RPT (RFC 8460)** — TLS-Reporting parallel zu DMARC. Komplett anderes Schema.
- **Per-Tenant-API-Quotas / Rate-Limiting** — wenn jemand die API exzessiv nutzt.
- **Bulk-Domain-Import** (CSV) — wenn ein Kunde 200 Domains bringt.
