#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="/opt/dmarc-geeks"

cd "$REPO_DIR"

# Repo auf neuesten Stand bringen
git fetch origin main
git reset --hard origin/main

# Build + (Re)Start Container
docker compose pull || true
docker compose up -d --build

# Alte Images aufraeumen
docker image prune -f
