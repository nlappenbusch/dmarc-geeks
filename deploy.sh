#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="/opt/dmarc-geeks"

cd "$REPO_DIR"

# Repo auf neuesten Stand bringen
git fetch origin main
git reset --hard origin/main

# WICHTIG: Compose-Variablen aus der Shell-Env loeschen.
# docker compose's Variablen-Resolution gibt Shell-Env Vorrang vor .env-File.
# Ohne diesen unset koennen Reste aus anderen Runner-Jobs oder system-weiten
# Configs die .env ueberschreiben (kostete uns einen Abend Port-8085-Konflikte).
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

# Image bauen waehrend alter Container weiterlaeuft
docker compose pull || true
docker compose build

# Sauber stoppen, kurz warten bis docker-proxy die Ports freigibt, dann hoch
docker compose down --remove-orphans
sleep 3
docker compose up -d

# Alte Images aufraeumen
docker image prune -f
