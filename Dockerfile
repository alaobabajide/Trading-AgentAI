# ── Stage 1: Build React dashboard ────────────────────────────────────────────
FROM node:20-alpine AS frontend
WORKDIR /app
COPY dashboard/package*.json ./
RUN npm ci
COPY dashboard/ .
RUN npm run build

# ── Stage 2: Python API + nginx serving both ───────────────────────────────────
FROM python:3.12-slim

# nginx + envsubst (gettext-base)
RUN apt-get update \
    && apt-get install -y --no-install-recommends nginx gettext-base \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Application code (brain, data, execution, config, etc.)
COPY . .

# React build output → nginx html root
COPY --from=frontend /app/dist /usr/share/nginx/html

# nginx template (PORT substituted at startup)
COPY nginx.combined.conf /tmp/nginx.conf.template

# Startup script
COPY start.sh /start.sh
RUN chmod +x /start.sh

# Railway injects $PORT; default to 80 for local docker run
ENV PORT=80
EXPOSE 80

CMD ["/start.sh"]
