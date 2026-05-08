# dmarc-geeks.ch – Deployment Pipeline Doku

## Ziel

Lokale Entwicklung auf dem PC, Code zentral in GitHub, Deployment passiert
automatisch auf einem internen Docker-Server, obwohl der Server nicht direkt
aus dem Internet erreichbar ist.

- **Trigger:** `git push` auf Branch `main`
- **Resultat:** Container (FastAPI + Postgres) wird auf dem internen Server neu
  gebaut und neu gestartet. NPM liefert danach den neuen Stand unter
  `https://dmarc-geeks.ch` aus.

## Architektur

### Komponenten

1. **GitHub Repo** – `nlappenbusch/dmarc-geeks`
   App-Code + `Dockerfile` + `docker-compose.yml` + `deploy.sh` + GitHub Workflow.

2. **Docker-Server (intern)**
   - Repo unter `/opt/dmarc-geeks`
   - Deployment Script: `/opt/dmarc-geeks/deploy.sh`
   - `.env` liegt **nur auf dem Server** (nicht im Repo)
   - Stack: App-Container + Postgres-Container via `docker compose`
   - App ist intern erreichbar auf Port **8086** (`8086:8000` im Compose, gesteuert ueber `APP_PORT` in `.env`)

3. **GitHub Actions Self-hosted Runner (intern)**
   - Laeuft als systemd service
   - Holt Jobs von GitHub ab (outbound), kein inbound SSH noetig
   - Fuehrt Deploy-Script lokal aus

4. **Nginx Proxy Manager (separate VM)**
   - Forward `dmarc-geeks.ch` -> Docker-Server-IP:8086
   - TLS via Let's Encrypt
   - Wichtig: in NPM "Websockets Support" anhaken (HTMX schadet's nicht, kostet
     nichts; FastAPI selbst nutzt's nicht zwingend).

### Deployment Flow

1. Aenderung lokal (z.B. `app/...` oder `app/templates/...`)
2. Commit + Push:
   ```powershell
   git add .
   git commit -m "..."
   git push
   ```
3. GitHub Actions startet Workflow `Deploy`
4. Self-hosted Runner nimmt den Job an
5. Runner fuehrt `/opt/dmarc-geeks/deploy.sh` aus:
   - `git fetch` + `git reset --hard origin/main`
   - `docker compose up -d --build`
6. Container wird aktualisiert, NPM liefert neue Version aus

## Server Setup (One-Time)

### 1) Verzeichnisse & Repo auschecken

```bash
sudo mkdir -p /opt/dmarc-geeks
sudo chown actions:actions /opt/dmarc-geeks
sudo -u actions git clone https://github.com/nlappenbusch/dmarc-geeks.git /opt/dmarc-geeks
sudo -u actions git config --global --add safe.directory /opt/dmarc-geeks
sudo chmod +x /opt/dmarc-geeks/deploy.sh
```

### 2) `.env` auf dem Server einrichten

```bash
sudo -u actions cp /opt/dmarc-geeks/.env.example /opt/dmarc-geeks/.env
sudo -u actions nano /opt/dmarc-geeks/.env
```

Pflicht-Felder fuer Produktion:

```env
POSTGRES_USER=dmarc
POSTGRES_PASSWORD=<starkes-passwort>
POSTGRES_DB=dmarc

APP_PORT=8086

SECRET_KEY=<via: python -c "import secrets; print(secrets.token_urlsafe(64))">
FERNET_KEY=<via: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())">

SUPERADMIN_EMAIL=admin@dmarc-geeks.ch
SUPERADMIN_PASSWORD=<einmaliges-startpasswort-sofort-aendern>
DEFAULT_TENANT_NAME=dmarc-geeks

BASE_URL=https://dmarc-geeks.ch
COOKIE_SECURE=true
TRUSTED_PROXIES=true

# SMTP fuer Mail-Features (sonst still degradieren)
SMTP_HOST=...
SMTP_PORT=587
SMTP_USER=...
SMTP_PASSWORD=...
SMTP_USE_TLS=true
SMTP_FROM=dmarc@dmarc-geeks.ch
```

> `.env` darf NIE ins Repo. Liegt nur auf dem Server.
> Verlust von `FERNET_KEY` = alle gespeicherten IMAP-Passwoerter unbrauchbar.

### 3) Self-hosted Runner registrieren

Auf GitHub: `Settings` -> `Actions` -> `Runners` -> `New self-hosted runner`
(Linux x64). Den Hinweisen folgen, dabei Label setzen:

```bash
./config.sh --url https://github.com/nlappenbusch/dmarc-geeks \
            --token <REGISTRATION-TOKEN> \
            --name dmarc-prod-01 \
            --labels dmarc-prod-01 \
            --unattended
```

Als systemd-Service installieren:

```bash
sudo ./svc.sh install actions
sudo ./svc.sh start
sudo systemctl status actions.runner.nlappenbusch-dmarc-geeks.dmarc-prod-01.service
```

User `actions` muss in der `docker`-Gruppe sein:

```bash
sudo usermod -aG docker actions
sudo systemctl restart actions.runner.nlappenbusch-dmarc-geeks.dmarc-prod-01.service
```

### 4) Erster Start

Einmal manuell hochziehen, damit Postgres-Volume + Superadmin angelegt werden:

```bash
sudo -u actions bash /opt/dmarc-geeks/deploy.sh
```

Direkt-Test auf dem Server:

```bash
curl -i http://127.0.0.1:8086/healthz
```

### 5) NPM-Forward

In Nginx Proxy Manager neuen Proxy Host:

- Domain Names: `dmarc-geeks.ch`, ggf. `www.dmarc-geeks.ch`
- Scheme: `http`
- Forward Hostname / IP: `<Docker-Server-IP>`
- Forward Port: `8086`
- "Block Common Exploits" + "Websockets Support" an
- SSL: Let's Encrypt fuer beide Domains
- "Force SSL" + "HTTP/2 Support" an

### 6) DNS

Bei deinem DNS-Provider:

- `dmarc-geeks.ch` A-Record -> Public-IP der NPM-VM
- `www.dmarc-geeks.ch` CNAME -> `dmarc-geeks.ch` (oder gleicher A-Record)

## Betrieb / Was beachten

### A) Deployment passiert nur, wenn wirklich gepusht wird

Stolperstein: Datei geaendert, aber nicht commited. `git push` sagt dann
"Everything up-to-date" -> nichts deployed.

```powershell
git add .
git commit -m "..."
git push
```

### B) Runner muss laufen

```bash
systemctl status actions.runner.nlappenbusch-dmarc-geeks.dmarc-prod-01.service
sudo systemctl restart actions.runner.nlappenbusch-dmarc-geeks.dmarc-prod-01.service
journalctl -u actions.runner.nlappenbusch-dmarc-geeks.dmarc-prod-01 -n 200 --no-pager
```

### C) Docker-Rechte

User `actions` in Gruppe `docker` (sonst kein `docker compose`):

```bash
id actions
```

### D) Repo Pull / Credentials

Wenn das Repo private wird: Deploy Key oder PAT auf dem Server hinterlegen,
sonst scheitert `git fetch`.

### E) NPM Forward Port

App haengt auf **8086** auf dem Docker-Host. NPM muss dorthin forwarden.

### F) Secrets niemals ins Repo

`.env`, FERNET_KEY, SECRET_KEY, SMTP-Passwoerter -> immer nur auf Server.
`.gitignore` schliesst `.env` + `*.db` + `*.log` aus.

### G) Postgres-Volume

Liegt im Docker-Volume `dmarc_geeks_dmarc_db` (Compose haengt es als
`dmarc_db` ein, prefixt mit Compose-Project-Name). Regelmaessig dumpen:

```bash
docker exec -t $(docker ps -qf "name=db") \
  pg_dump -U dmarc dmarc > /backup/dmarc-$(date +%F).sql
```

### H) Rollback

- GitHub: letzten guten Commit raussuchen
- `git revert <bad-sha>` oder `git reset <good-sha>` + `git push --force-with-lease`
- Pipeline deployed automatisch den alten Stand

## Troubleshooting Cheatsheet

**Aenderung nicht sichtbar:**
1. Lief der GitHub Actions Run durch?
2. Runner-Logs zeigen "Succeeded"?
3. Server: `sudo -u actions git -C /opt/dmarc-geeks log -1 --oneline`
4. `curl http://127.0.0.1:8086/healthz`
5. NPM zeigt auf richtigen Port?

**Container nicht erreichbar:**
```bash
docker ps
docker compose -f /opt/dmarc-geeks/docker-compose.yml logs --tail=200
```

**App startet, aber 500er:**
```bash
docker compose -f /opt/dmarc-geeks/docker-compose.yml logs app --tail=200
```
Meist: SECRET_KEY oder FERNET_KEY fehlt in `.env`, oder DB nicht erreichbar.

**Postgres-Reset (NUR wenn man die Daten weghaben will):**
```bash
cd /opt/dmarc-geeks
docker compose down
docker volume rm dmarc-geeks_dmarc_db
docker compose up -d --build
```
