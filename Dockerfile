FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# system deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libpq-dev gettext libcairo2 pango1.0-tools libpango-1.0-0 \
    libgdk-pixbuf2.0-0 shared-mime-info curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN chmod +x /app/entrypoint.sh

# Static files collect in image build (optional, yoki entrypointda)
# RUN python manage.py collectstatic --noinput

CMD ["/app/entrypoint.sh"]
