FROM python:3.13-slim

# Prevent .pyc files and enable unbuffered stdout/stderr for Railway logs
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install OS-level dependencies needed by psycopg2-binary and cryptography
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy project source
COPY . .

# Collect static files at build time (no-op if STATIC_ROOT isn't configured, harmless)
RUN python manage.py collectstatic --noinput || true

# Default command — Railway overrides this per service (see below)
# Web service:    gunicorn config.wsgi:application --bind 0.0.0.0:$PORT --workers 2
# Worker service: celery -A config worker --loglevel=info --concurrency=2
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "2"]
