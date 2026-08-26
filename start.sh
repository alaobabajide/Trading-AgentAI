#!/bin/sh
# No set -e — nginx must always start even if uvicorn or the bot fail

# ── 0. Expand env vars in nginx template ─────────────────────────────────────
envsubst '${PORT}' < /tmp/nginx.conf.template > /etc/nginx/conf.d/default.conf
rm -f /etc/nginx/sites-enabled/default 2>/dev/null || true

# Guard: BRAIN_API_KEY is required — the API is fail-closed without it.
if [ -z "$BRAIN_API_KEY" ]; then
    echo "[start] FATAL: BRAIN_API_KEY is not set. The brain API will reject all requests until this is configured in Railway env vars."
fi

# Guard: GRAFANA_ADMIN_PASSWORD must be changed from the placeholder default.
if [ "${GRAFANA_ADMIN_PASSWORD:-}" = "CHANGE_ME_REQUIRED" ]; then
    echo "[start] FATAL: GRAFANA_ADMIN_PASSWORD is still set to the default value. Change it in Railway env vars before deploying."
    exit 1
fi

# ── 0b. Inject runtime config for the dashboard ──────────────────────────────
# BRAIN_API_KEY is intentionally excluded — browser clients authenticate via
# Supabase JWT (Bearer token). The master API key must never be served to browsers.
printf 'window.__TA_CONFIG__ = { supabaseUrl: "%s", supabaseAnonKey: "%s", ownerUserId: "%s", demoUserId: "%s" };\n' \
    "$SUPABASE_URL" "$SUPABASE_ANON_KEY" "$OWNER_USER_ID" "$DEMO_USER_ID" \
    > /usr/share/nginx/html/runtime-config.js

# ── 1. Start brain API (uvicorn) with automatic restart supervisor ────────────
echo "[start] Launching uvicorn supervisor on 127.0.0.1:8000…"
cd /app
(
    while true; do
        echo "[uvicorn] Starting…"
        uvicorn brain.api:app --host 127.0.0.1 --port 8000 --workers 1
        EXIT=$?
        echo "[uvicorn] Exited with code $EXIT — restarting in 5s…"
        sleep 5
    done
) &
UVICORN_SUPERVISOR_PID=$!
echo "[start] Uvicorn supervisor PID=$UVICORN_SUPERVISOR_PID"

# Wait for uvicorn to be ready before continuing (nginx will 502 until it is)
echo "[start] Waiting for uvicorn to be ready…"
_uvicorn_ready=0
for _i in $(seq 1 30); do
    if wget -q -O /dev/null http://127.0.0.1:8000/health 2>/dev/null; then
        _uvicorn_ready=1
        echo "[start] Uvicorn ready after ${_i}s"
        break
    fi
    sleep 1
done
if [ "$_uvicorn_ready" = "0" ]; then
    echo "[start] WARNING: Uvicorn did not respond within 30s — nginx may 502 initially"
fi

# ── 2. Start Telegram bot (if token is set) ───────────────────────────────────
if [ -n "$TELEGRAM_BOT_TOKEN" ]; then
    echo "[start] Launching Telegram bot…"
    python -m telegram_bot.bot &
else
    echo "[start] TELEGRAM_BOT_TOKEN not set — bot disabled."
fi

# ── 2b. Start auto-trading orchestrator with automatic restart ────────────────
# Runs by default. Set AUTO_TRADE=false in Railway env vars to disable.
if [ "${AUTO_TRADE:-true}" != "false" ]; then
    echo "[start] Launching orchestrator supervisor (set AUTO_TRADE=false to disable)…"
    # Supervisor loop: restart orchestrator if it exits for any reason
    (
        while true; do
            echo "[orchestrator] Starting…"
            python -m monitoring.orchestrator
            EXIT=$?
            echo "[orchestrator] Exited with code $EXIT — restarting in 15s…"
            sleep 15
        done
    ) &
    echo "[start] Orchestrator supervisor running in background."
else
    echo "[start] AUTO_TRADE=false — orchestrator disabled."
fi

# ── 3. Start nginx in foreground (keeps container alive) ─────────────────────
echo "[start] Launching nginx on port ${PORT}…"
exec nginx -g 'daemon off;'
