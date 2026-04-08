# Public Deploy

This app can be deployed as a single-container Flask service.

## Important constraint

The app uses SQLite:

- good for one small public instance
- not good for multiple replicas
- not good for horizontal scaling
- keep Gunicorn at one worker unless you move to a database server

If traffic grows, move to PostgreSQL later.

## Required env vars

- `SECRET_KEY`: strong random string. The app will not start without it.
- `PORT`: runtime port, default `5000`
- `WEIGHT_DB_PATH`: optional database path, default `/data/weight_records.db` in Docker
- `REGISTRATION_ENABLED`: set `true` only when you want users to create accounts
- `REGISTER_INVITE_CODE`: optional invite code required during registration
- `SESSION_COOKIE_SECURE`: keep `true` when served over HTTPS

## Security defaults

- POST forms use CSRF tokens.
- Login and registration have a small in-memory rate limit.
- Registration is disabled by default.
- Session cookies are `HttpOnly`, `SameSite=Lax`, and secure by default.
- The Docker image does not include the local SQLite database.

## Local production-style run

```bash
cd /Users/a1050/PyCharmMiscProject
/Users/a1050/PyCharmMiscProject/.venv/bin/pip install -r requirements.txt
SECRET_KEY='replace-with-a-long-random-value' \
REGISTRATION_ENABLED=true \
REGISTER_INVITE_CODE='replace-with-an-invite-code' \
/Users/a1050/PyCharmMiscProject/.venv/bin/gunicorn -w 1 -b 0.0.0.0:5000 wsgi:app
```

## Docker build

```bash
cd /Users/a1050/PyCharmMiscProject
docker build -t weight-app .
```

## Docker run

```bash
docker run -d \
  --name weight-app \
  -p 80:5000 \
  -e SECRET_KEY='replace-with-a-long-random-value' \
  -e REGISTRATION_ENABLED=false \
  -v weight-app-data:/data \
  weight-app
```

## Docker Compose + Caddy

1. Copy `.env.example` to `.env` and edit the values.
2. Point your domain A record to the server IP.
3. Start the stack:

```bash
docker compose up -d --build
```

Caddy listens on ports 80 and 443 and proxies to the Flask container.

## Server reverse proxy

If you deploy behind Nginx/Caddy:

- proxy pass to `127.0.0.1:5000`
- keep only one app instance because of SQLite
- terminate HTTPS at the reverse proxy

## Domain connection

1. Buy or use an existing domain.
2. Add an `A` record to your server IP.
3. Put Nginx or Caddy in front of the container.
4. Enable HTTPS.

## Preflight check

```bash
./scripts/deploy_check.sh
```
