#!/usr/bin/env bash
# entrypoint.sh - Production Entry Point
set -e

echo "========================================="
echo "Starting Phone Magazine System..."
echo "========================================="

# Wait for PostgreSQL
if [ "$USE_POSTGRESQL" = "True" ]; then
    echo "Waiting for PostgreSQL..."
    while ! nc -z $POSTGRES_HOST $POSTGRES_PORT; do
        sleep 0.5
    done
    echo "PostgreSQL started!"
fi

# Wait for Redis
if [ "$USE_REDIS" = "True" ]; then
    echo "Waiting for Redis..."
    while ! nc -z redis 6379; do
        sleep 0.5
    done
    echo "Redis started!"
fi

echo ""
echo "Running database migrations..."
python manage.py migrate --noinput

echo ""
echo "Collecting static files..."
python manage.py collectstatic --noinput --clear

echo ""
echo "Compiling translations..."
python manage.py compilemessages

# Create superuser if credentials provided
if [ -n "$DJANGO_SUPERUSER_USERNAME" ]; then
    echo ""
    echo "Checking for superuser..."
    python manage.py shell <<EOF
from django.contrib.auth import get_user_model
import os

User = get_user_model()
username = os.environ.get("DJANGO_SUPERUSER_USERNAME")
email = os.environ.get("DJANGO_SUPERUSER_EMAIL", "")
password = os.environ.get("DJANGO_SUPERUSER_PASSWORD")

if username and password:
    if not User.objects.filter(username=username).exists():
        User.objects.create_superuser(
            username=username,
            email=email,
            password=password
        )
        print(f"✓ Superuser '{username}' created successfully!")
    else:
        print(f"✓ Superuser '{username}' already exists.")
EOF
fi

echo ""
echo "========================================="
echo "Starting Gunicorn server..."
echo "========================================="

# Start Gunicorn
exec gunicorn config.wsgi:application \
    --bind 0.0.0.0:8000 \
    --workers ${GUNICORN_WORKERS:-4} \
    --threads ${GUNICORN_THREADS:-2} \
    --worker-class ${GUNICORN_WORKER_CLASS:-sync} \
    --worker-tmp-dir /dev/shm \
    --max-requests ${GUNICORN_MAX_REQUESTS:-1000} \
    --max-requests-jitter ${GUNICORN_MAX_REQUESTS_JITTER:-50} \
    --timeout ${GUNICORN_TIMEOUT:-120} \
    --graceful-timeout ${GUNICORN_GRACEFUL_TIMEOUT:-30} \
    --keep-alive ${GUNICORN_KEEPALIVE:-5} \
    --access-logfile - \
    --error-logfile - \
    --log-level ${GUNICORN_LOG_LEVEL:-info}