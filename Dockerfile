# Python slim + system deps (WeasyPrint, Postgres)
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PATH="/usr/local/bin:${PATH}"

# System deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential gcc \
    libpq-dev \
    # WeasyPrint deps:
    libcairo2 pango-graphite libpango-1.0-0 libpangocairo-1.0-0 \
    libgdk-pixbuf-2.0-0 shared-mime-info fonts-dejavu-core \
    libffi-dev libxml2 libxslt1.1 \
    curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Workdir
WORKDIR /app

# Requirements first (better caching)
COPY requirements.txt /app/
RUN pip install --upgrade pip wheel && pip install -r requirements.txt

# App code
COPY . /app

# Ensure runtime dirs exist
RUN mkdir -p /app/staticfiles /app/media /app/logs

# Permissions (simplify)
RUN useradd -m appuser && chown -R appuser:appuser /app
USER appuser

# Gunicorn config is in repo as gunicorn.conf.py
EXPOSE 8000

# Entrypoint runs migrations, collectstatic, then gunicorn
ENTRYPOINT ["/app/entrypoint.sh"]
