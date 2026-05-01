#!/bin/bash
# Run from /opt/wattlelink to pull latest code and redeploy.
set -e

COMPOSE="docker compose -f docker-compose.prod.yml"

echo "=== Pulling latest code ==="
git pull

echo "=== Building new image ==="
$COMPOSE build web celery

echo "=== Restarting services (zero-downtime swap) ==="
$COMPOSE up -d --no-deps web celery

echo "=== Cleaning up old images ==="
docker image prune -f

echo "=== Done. ==="
$COMPOSE ps
