#!/usr/bin/env bash
set -e

# Wait for Postgres if enabled
if [ "${USE_POSTGRESQL}" = "True" ] || [ "${USE_POSTGRESQL}" = "true" ]; then
  echo "Waiting for PostgreSQL at ${POSTGRES_HOST:-db}:${POSTGRES_PORT:-5432}..."
  while ! /usr/bin/env bash -c "</dev/tcp/${POSTGRES_HOST:-db}/${POSTGRES_PORT:-5432}"; do
    sleep 1
  done
fi

python manage.py migrate --noinput
python manage.py collectstatic --noinput
python manage.py compilemessages || true

# Django health endpoint exists at /health/
exec gunicorn config.wsgi:application --config gunicorn.conf.py
