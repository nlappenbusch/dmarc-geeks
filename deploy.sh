#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="/opt/dmarc-geeks"

cd "$REPO_DIR"

# Repo auf neuesten Stand bringen
git fetch origin main
git reset --hard origin/main

# Compose-Variablen aus der Shell-Env loeschen, damit /opt/dmarc-geeks/.env
# nicht von Shell-Vars ueberschrieben wird.
unset \
  APP_PORT \
  POSTGRES_USER POSTGRES_PASSWORD POSTGRES_DB \
  DATABASE_URL \
  SECRET_KEY FERNET_KEY \
  SUPERADMIN_EMAIL SUPERADMIN_PASSWORD DEFAULT_TENANT_NAME \
  IMAP_POLL_INTERVAL_MINUTES RESOLVE_PTR \
  BASE_URL COOKIE_SECURE TRUSTED_PROXIES ALLOW_SIGNUP \
  SMTP_HOST SMTP_PORT SMTP_USER SMTP_PASSWORD \
  SMTP_USE_TLS SMTP_TLS_VERIFY SMTP_FROM \
  SPAMHAUS_DQS_KEY DNSBL_STABILITY_THRESHOLD \
  HETZNER_DNS_TOKEN HETZNER_DNS_ZONE

docker compose pull || true
docker compose build

# Vollstaendiger Teardown: compose down + harter rm aller leftovers
docker compose down --remove-orphans
docker rm -f $(docker ps -aq --filter name=dmarc-geeks) 2>/dev/null || true

# Kernel-Pause damit docker-proxy die Ports wirklich freigibt
sleep 3

docker compose up -d

# Selbst-heilung: in dieser LXC laesst `compose up -d` den App-Container
# manchmal in "Created" haengen. Wenn ja: explicit starten.
sleep 3
if ! docker ps --filter name=dmarc-geeks-app-1 --filter status=running -q | grep -q .; then
  echo "WARN: app container not running after 'compose up -d', forcing start..."
  docker start dmarc-geeks-app-1 || true
  sleep 3
fi

# Final Health-Check, sonst Job rot melden
if ! docker ps --filter name=dmarc-geeks-app-1 --filter status=running -q | grep -q .; then
  echo "ERROR: app container still not running"
  docker logs dmarc-geeks-app-1 --tail=40 || true
  docker inspect dmarc-geeks-app-1 --format 'State.Error: {{.State.Error}} | Exit: {{.State.ExitCode}}' || true
  exit 1
fi

echo "OK: dmarc-geeks-app is running"
docker image prune -f
