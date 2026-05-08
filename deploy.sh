#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="/opt/dmarc-geeks"

cd "$REPO_DIR"

# Repo auf neuesten Stand bringen
git fetch origin main
git reset --hard origin/main

# Image bauen, danach sauber down + up. Trennen verhindert Port-Bind-Konflikte
# wenn der alte Container die Ports noch nicht freigegeben hat.
docker compose pull || true
docker compose build
docker compose down --remove-orphans
docker compose up -d

# Alte Images aufraeumen
docker image prune -f
