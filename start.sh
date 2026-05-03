#!/bin/bash
set -e
echo "=== PORT is: ${PORT} ==="
echo "=== Running migrations ==="
python manage.py migrate --noinput
echo "=== Testing Django WSGI import ==="
python -c "import config.wsgi; print('WSGI import OK')"
echo "=== Starting gunicorn on port ${PORT:-8000} ==="
exec gunicorn config.wsgi:application \
    --bind "0.0.0.0:${PORT:-8000}" \
    --workers 2 \
    --timeout 120 \
    --log-level debug \
    --access-logfile - \
    --error-logfile -
