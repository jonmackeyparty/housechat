# Deploying `slackers` with Docker (quickstart)

This document explains a minimal, safe path to run the app in Docker locally or on a single remote host.

Prerequisites
- Docker installed on the host
- (Optional) Docker Compose if you want to use `docker-compose.yml`

Build the image

```bash
# from repo root
docker build -t slackers-app:latest .
```

Run the container (simple)

```bash
mkdir -p data/uploads
docker run --rm -it \
  -p 5000:5000 \
  -v "$PWD/data":/data \
  -v "$PWD/static/uploads":/app/static/uploads \
  -e CHANNELS_FILE=/data/channels.json \
  -e AVATARS_FILE=/data/avatars.json \
  -e UPLOAD_FOLDER=/data/uploads \
  -e SECRET_KEY='change-me' \
  slackers-app:latest
```

Run with `docker-compose` (includes Redis for Socket.IO message queue)

```bash
docker compose up --build
```

Important production notes
- Worker: `gunicorn` + `eventlet` is used to support Socket.IO. Ensure `eventlet` is installed.
- Persistence: the app currently stores `channels.json` and `avatars.json` on disk. Mount a host volume (see above) or migrate to a DB (SQLite/Postgres) for reliability.
- Scaling: when running >1 replica, set `MESSAGE_QUEUE` to a Redis URL and use the same Redis for all replicas.
- TLS: terminate TLS at a reverse proxy (Nginx / cloud LB). Configure proxy to forward websocket upgrades (set `Upgrade` and `Connection` headers).
- Secrets: do NOT embed `SECRET_KEY` in the image. Pass it via env vars or a secret manager.
- Backups: schedule periodic backups of your persistent `data` directory.

Next steps
- Update `app.py` to read `CHANNELS_FILE`, `AVATARS_FILE`, `UPLOAD_FOLDER`, and `MESSAGE_QUEUE` from env vars (if you want to change file locations via env).
- Add a lightweight health endpoint (`/healthz`) for container health checks.
- Add CI to build and push images to a registry.
