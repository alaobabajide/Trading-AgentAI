#!/bin/sh
set -e

# Substitute $PORT into nginx config (only ${PORT} — leaves nginx vars intact)
envsubst '${PORT}' < /tmp/nginx.conf.template > /etc/nginx/conf.d/default.conf
rm -f /etc/nginx/sites-enabled/default

# ── 1. Start brain API (uvicorn) on localhost:8000 ───────────────────────────
echo "[start] Launching uvicorn on 127.0.0.1:8000…"
uvicorn brain.api:app --host 127.0.0.1 --port 8000 --workers 1 &
UVICORN_PID=$!

# Wait for uvicorn to be ready (up to 30s)
echo "[start] Waiting for brain API…"
for i in $(seq 1 30); do
    if wget -q -O- http://127.0.0.1:8000/health > /dev/null 2>&1; then
        echo "[start] Brain API ready."
        break
    fi
    sleep 1
done

# ── 2. Start Telegram bot (if token is set) ───────────────────────────────────
if [ -n "$TELEGRAM_BOT_TOKEN" ]; then
    echo "[start] Launching Telegram bot…"
    python -m telegram_bot.bot &
else
    echo "[start] TELEGRAM_BOT_TOKEN not set — bot disabled."
fi

# ── 3. Start nginx in foreground (keeps container alive) ─────────────────────
echo "[start] Launching nginx on port ${PORT}…"
exec nginx -g 'daemon off;'
