#!/bin/sh
set -eu

if [ ! -f .env ]; then
  echo "Missing .env. Copy .env.example to .env and edit it."
  exit 1
fi

if grep -q "replace-with-a-long-random-value" .env; then
  echo "SECRET_KEY still uses the placeholder value."
  exit 1
fi

if ! grep -q "^DOMAIN=." .env; then
  echo "DOMAIN is missing in .env."
  exit 1
fi

python -m py_compile weight_app.py wsgi.py
docker compose config >/dev/null

echo "Preflight checks passed."
