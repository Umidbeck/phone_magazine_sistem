#!/usr/bin/env bash
set -e

# Migrations
python manage.py migrate --noinput

# Collect static
python manage.py collectstatic --noinput

# Superuser (agar mavjud bo'lmasa)
if [ -n "$DJANGO_SUPERUSER_USERNAME" ]; then
  python - <<'PY'
import os, django
os.environ.setdefault("DJANGO_SETTINGS_MODULE","config.settings")
django.setup()
from django.contrib.auth import get_user_model
User = get_user_model()
u = os.environ.get("DJANGO_SUPERUSER_USERNAME")
e = os.environ.get("DJANGO_SUPERUSER_EMAIL")
p = os.environ.get("DJANGO_SUPERUSER_PASSWORD")
if u and p and not User.objects.filter(username=u).exists():
    User.objects.create_superuser(username=u, email=e, password=p)
PY
fi

# Gunicorn
exec gunicorn config.wsgi:application \
  --config /app/gunicorn.conf.py
