#!/bin/sh
# No set -e — nginx must always start even if uvicorn or the bot fail

# ── 0. Expand env vars in nginx template ─────────────────────────────────────
envsubst '${PORT}' < /tmp/nginx.conf.template > /etc/nginx/conf.d/default.conf
rm -f /etc/nginx/sites-enabled/default 2>/dev/null || true

# Warn loudly if BRAIN_API_KEY is not set — API will be unauthenticated
if [ -z "$BRAIN_API_KEY" ]; then
    echo "[start] WARNING: BRAIN_API_KEY is not set. All /api/* routes are UNAUTHENTICATED. Set it in Railway env vars."
fi

# ── 0b. Inject runtime config for the dashboard (API key delivered at startup) ─
printf 'window.__TA_CONFIG__ = { apiKey: "%s" };\n' "$BRAIN_API_KEY" \
    > /usr/share/nginx/html/runtime-config.js

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

# ── 2b. Start auto-trading orchestrator (if AUTO_TRADE=true) ─────────────────
if [ "$AUTO_TRADE" = "true" ]; then
    echo "[start] AUTO_TRADE=true — launching orchestrator…"
    # Orchestrator polls /health internally and waits up to 90s for uvicorn
    python -m monitoring.orchestrator &
    echo "[start] Orchestrator PID=$!"
else
    echo "[start] AUTO_TRADE not set — orchestrator disabled (set AUTO_TRADE=true in Railway to enable)."
fi

# ── 3. Start nginx in foreground (keeps container alive) ─────────────────────
echo "[start] Launching nginx on port ${PORT}…"
exec nginx -g 'daemon off;'
