#!/bin/sh
# No set -e — nginx must always start even if uvicorn or the bot fail

# ── 0. Expand $PORT in nginx template ────────────────────────────────────────
envsubst '${PORT}' < /tmp/nginx.conf.template > /etc/nginx/conf.d/default.conf
rm -f /etc/nginx/sites-enabled/default 2>/dev/null || true

# ── 1. Start brain API (uvicorn) on 127.0.0.1:8000 in the background ─────────
echo "[start] Launching uvicorn on 127.0.0.1:8000…"
cd /app
uvicorn brain.api:app --host 127.0.0.1 --port 8000 --workers 1 &
echo "[start] Uvicorn PID=$! (nginx will proxy to it; returns 502 until ready)"

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
