#!/bin/sh
set -e

# Production entrypoint for the Django app container.
# Waits for the database to be ready, runs migrations, and starts Gunicorn.

python manage.py collectstatic --noinput
python manage.py migrate --noinput

exec "$@"
