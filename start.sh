#!/bin/sh
set -e

# Substitute $PORT into nginx config (leaves nginx vars like $uri untouched)
envsubst '${PORT}' < /tmp/nginx.conf.template > /etc/nginx/conf.d/default.conf

# Remove the default nginx site if it exists
rm -f /etc/nginx/sites-enabled/default

# Start the Python brain API on localhost:8000 (internal only)
uvicorn brain.api:app --host 127.0.0.1 --port 8000 --workers 1 &

# Wait for uvicorn to be ready before nginx starts accepting /api/ traffic
echo "Waiting for uvicorn to start..."
for i in $(seq 1 30); do
    if wget -q -O- http://127.0.0.1:8000/health > /dev/null 2>&1; then
        echo "Uvicorn ready."
        break
    fi
    sleep 1
done

# Start nginx in foreground (keeps container alive)
exec nginx -g 'daemon off;'
