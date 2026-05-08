# DMARC Aggregator

Selbst-gehosteter, multi-tenant-fähiger DMARC-Aggregate-Report-Aggregator.
Sammelt RUA-Reports per IMAP oder HTTP-Upload, parst sie (XML / `.gz` / `.zip`),
und stellt sie in einem schlanken Web-UI dar — mit Charts, Filtern, Advisor,
Webhooks und allem, was ein modernes Reporting-Tool braucht.

## Highlights

- **Multi-Tenant** — strikte Datentrennung pro Mandant, Superadmin verwaltet Tenants
- **Mehrere Domains pro Tenant**, mit DNS-Verifikation und Tag-Gruppierung
- **Reports automatisch via IMAP** oder per HTTP-Upload-Button oder per Bearer-API
- **Robust** gegen Google/Microsoft/Yahoo-Schemata, akzeptiert `.xml`, `.xml.gz`, `.zip`
- **Fancy Dashboards**: KPI-Kacheln · Tagesverlauf · Sender-Donut · Sender-Stack ·
  Sankey-Flow (Sender → Alignment → Disposition) · Sparklines pro Domain
- **Smart Advisor** — sagt dir, wann du sicher von `p=none` auf `p=quarantine`
  bzw. `p=reject` umstellen kannst
- **DMARC-Generator** — Policy interaktiv zusammenklicken, Live-Vorschau, Validierung
- **IP-Allowlist** für legitime Sender (Mailchimp, eigene Server, …)
- **API-Keys** mit Bearer-Auth, one-time-shown Secret, Revoke
- **Webhooks** mit HMAC-SHA256-Signatur (`report.imported`)
- **CSV-Export** mit Filtern (Domain, Volltextsuche, Status, Zeitraum)
- **Email-Notifications**: wöchentlicher Digest, Spike-Alerts (HTML + Plain-Text)
- **Forgot-Password & Self-Service-Signup** (per Magic-Link)
- **Audit-Log** für alle wichtigen Aktionen
- **Branding** pro Tenant — eigene Akzentfarbe in der UI
- **Dark-Mode** mit OS-Preference-Detection
- **Mobile-Responsive** mit Hamburger-Nav
- **Rate-Limiting** auf Login und Magic-Link-Endpoints
- **Request-ID-Middleware** für Log-Korrelation
- **Health-Check** unter `/healthz`

## Quickstart

### Mit Docker

```bash
# 1) Keys erzeugen
python scripts/generate_keys.py

# 2) .env aus Vorlage anlegen, Keys eintragen
cp .env.example .env
# -> SECRET_KEY und FERNET_KEY einfügen
# -> SUPERADMIN_EMAIL/PASSWORD anpassen

# 3) Hochfahren (Postgres + App)
docker compose up -d --build

# 4) Login: http://localhost:8000  (admin@example.com / changeme)
```

### Lokal mit Python (Dev)

```bash
pip install -r requirements.txt
python scripts/generate_keys.py
# .env: DATABASE_URL=sqlite:///./dmarc.db
python -m uvicorn app.main:app --port 8000

# optional: Demo-Daten generieren
python -m scripts.seed_demo --reset --days 30
```

Beim ersten Start wird automatisch ein Default-Tenant samt Superadmin-User
angelegt (aus den `SUPERADMIN_*` ENVs). Nach Anlage werden diese ENVs ignoriert.

## Konfiguration (.env)

| Variable | Default | Zweck |
|---|---|---|
| `DATABASE_URL` | `sqlite:///./dmarc.db` | Postgres oder SQLite |
| `SECRET_KEY` | (Pflicht) | Sessions & API-Token-HMAC |
| `FERNET_KEY` | (Pflicht) | IMAP-Passwort-Verschlüsselung |
| `SUPERADMIN_EMAIL` | `admin@example.com` | Erster Login |
| `SUPERADMIN_PASSWORD` | `changeme` | Erster Login |
| `DEFAULT_TENANT_NAME` | `Default` | Erster Tenant |
| `IMAP_POLL_INTERVAL_MINUTES` | `15` | IMAP-Polling-Intervall |
| `RESOLVE_PTR` | `true` | Reverse-DNS auf Source-IPs |
| `BASE_URL` | `http://localhost:8000` | Für Magic-Link-URLs in Mails |
| `ALLOW_SIGNUP` | `false` | Self-Service-Tenant-Anlage |
| `COOKIE_SECURE` | `false` | `true` hinter HTTPS |
| `TRUSTED_PROXIES` | `false` | `true` hinter Reverse-Proxy |
| `SMTP_HOST/PORT/USER/PASSWORD/USE_TLS/FROM` | (leer) | Mail-Versand |

Ohne `SMTP_HOST` degradieren Mail-Features still — Reset/Signup-Links erscheinen
stattdessen als Flash-Banner (für lokales Testen).

## Workflows

### Domain einrichten
1. **Domains** → "Neue Domain" → `meinedomain.de`
2. DMARC-DNS-Record mit `rua=mailto:dmarc@meinedomain.de` setzen — oder den
   **Generator** öffnen (`/dmarc-generator?domain=meinedomain.de`) und
   den Record klick-zusammenstellen
3. Optional: Verifikations-TXT setzen und im UI auf "DNS prüfen" klicken
4. Reports einsammeln: Mailbox per IMAP oder Upload

### Reports per IMAP
1. **Mailboxen** → IMAP-Postfach eintragen (Anbieter-Presets für Gmail, M365,
   mailbox.org, Strato, IONOS)
2. **Aktiv** ankreuzen → wird alle 15 Min geholt
3. **jetzt prüfen** für sofortigen Test

### Reports per HTTP-API
```bash
# 1) Im UI: "API-Keys" → Key erzeugen → einmalig kopieren
# 2) Reports posten:
curl -X POST http://localhost:8000/api/v1/reports \
  -H "Authorization: Bearer dmk_PREFIX.SECRET" \
  -F "files=@report.xml.gz"
```

### Webhooks
**Webhooks** → URL eintragen. Bei jedem Import wird `POST` gefeuert mit
`X-DMARC-Signature` (HMAC-SHA256) zur Verifikation.

### Multi-Tenant-Betrieb
Als Superadmin → **Tenants** → "Neuer Tenant" mit eigenem Admin-User. Der
Kunde meldet sich mit dieser Mail/Pass an und sieht **nur** seine Daten. Tenant-
Admins legen weitere User in ihrem Tenant an.

### Self-Service-Signup
`ALLOW_SIGNUP=true` setzen → User registrieren sich unter `/signup` selbst.
Magic-Link via Mail aktiviert Account + Tenant.

## Architektur

```
app/
├── main.py            # FastAPI app + lifespan + error handlers
├── config.py          # Settings via env (pydantic-settings)
├── database.py        # SQLAlchemy engine/session
├── middleware.py      # Request-ID + access logging
├── models.py          # Tenant, User, Domain, Mailbox, Report, Record,
│                      # AuthResult, IngestLog, TenantSettings, ApiKey,
│                      # IpAllowlist, Tag, DomainTag, Webhook, AuditEvent, AuthToken
├── security.py        # bcrypt, Fernet, secrets
├── parser.py          # DMARC XML parsing (zip/gz aware)
├── ingest.py          # Persistenz, Dedup, PTR, Spike-Trigger, Webhook-Emit
├── dns_utils.py       # PTR + TXT-Lookups
├── imap_poller.py     # IMAP fetch + ingest
├── scheduler.py       # APScheduler: IMAP-Poll + Weekly-Digest
├── notifications.py   # Spike-Alerts + Weekly-Digest
├── webhooks.py        # Outbound mit HMAC-Signatur
├── mail.py            # SMTP + HTML-Email-Renderer
├── stats.py           # Aggregations: KPIs, Tagesverlauf, Top-Quellen,
│                      # Sender-Breakdown, Sankey, Sparklines
├── advisor.py         # DMARC-Policy-Empfehlungen
├── audit.py           # Audit-Event-Helper
├── onboarding.py      # Checklist-Computer
├── rate_limit.py      # Token-Bucket pro IP
├── templating.py      # Jinja2 + Brand-Color
├── routers/           # auth, auth_extra, dashboard, domains, reports,
│                      # upload, mailboxes, users, api_keys, webhooks,
│                      # tags, settings, audit, admin, generator, help, api
├── templates/         # Jinja + HTMX + Chart.js (+ chartjs-chart-sankey)
│   └── email/         # HTML-Email-Templates (reset, signup, digest, spike)
└── static/style.css   # Inter-Font, Dark-Mode, Brand-Variablen
```

## Sicherheit / Produktion

- Hinter TLS-Reverse-Proxy stellen (Caddy/Traefik/Nginx).
- `COOKIE_SECURE=true`, `TRUSTED_PROXIES=true` setzen.
- `SECRET_KEY` (Sessions) und `FERNET_KEY` (IMAP-Passwörter) **niemals
  verlieren** — Verlust von `FERNET_KEY` ⇒ alle gespeicherten IMAP-Passwörter
  unbrauchbar.
- Postgres-Volume regelmäßig dumpen.
- Reverse-DNS ist Best-Effort (3 s Timeout, Cache 4096); abschaltbar mit
  `RESOLVE_PTR=false`.
- Reports werden mit Roh-XML gespeichert — wenn DSGVO-Bedenken, in
  `app/ingest.py` das `raw_xml=` weglassen.
- Login + Forgot/Signup sind rate-limited (10 Login-Versuche / 5 min,
  5 Mail-Anfragen / 10 min, pro IP).

## Tests

```bash
# Parser-Smoketest (lokal)
python -m scripts.test_parser

# Demo-Daten generieren (270+ Reports, 3 Domains)
python -m scripts.seed_demo --reset --days 30
```

## Roadmap

Siehe [ROADMAP.md](ROADMAP.md). Prominent: CNAME-Delegation für DMARC via
Hetzner DNS API, sobald der erste Pilotkunde danach fragt.

## Lizenz

Privat / kein Lizenzhinweis — passe nach Bedarf an.
