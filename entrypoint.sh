#!/bin/sh
set -e

echo "Waiting for postgres..."
until pg_isready -h "${POSTGRES_HOST:-postgres}" -p "${POSTGRES_PORT:-5432}" -U "${POSTGRES_USER:-wattlelink}"; do
  sleep 2
done

echo "Running migrations..."
python manage.py migrate --noinput

echo "Starting gunicorn..."
exec gunicorn config.wsgi:application \
  --bind 0.0.0.0:8000 \
  --workers 3 \
  --threads 4 \
  --worker-class gthread \
  --worker-tmp-dir /dev/shm \
  --timeout 120 \
  --log-level info \
  --access-logfile -
