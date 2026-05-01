#!/bin/sh
set -e

# Wait for postgres (skipped on Railway — it manages the connection)
if [ -z "$DATABASE_URL" ]; then
  echo "Waiting for postgres..."
  until pg_isready -h "${POSTGRES_HOST:-postgres}" -p "${POSTGRES_PORT:-5432}" -U "${POSTGRES_USER:-wattlelink}"; do
    sleep 2
  done
fi

echo "Running migrations..."
python manage.py migrate --noinput

echo "Collecting static files..."
python manage.py collectstatic --noinput

# Railway sets PORT; fall back to 8000 for Docker/local
PORT="${PORT:-8000}"

echo "Starting gunicorn on port $PORT..."
exec gunicorn config.wsgi:application \
  --bind "0.0.0.0:$PORT" \
  --workers 3 \
  --threads 4 \
  --worker-class gthread \
  --worker-tmp-dir /dev/shm \
  --timeout 120 \
  --log-level info \
  --access-logfile -
