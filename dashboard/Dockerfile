FROM node:20-alpine AS builder
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM nginx:1.27-alpine
# Install gettext for envsubst
RUN apk add --no-cache gettext

COPY --from=builder /app/dist /usr/share/nginx/html
# Store config as a template; start.sh will substitute $PORT at runtime
COPY nginx.conf /tmp/nginx.conf.template
COPY start.sh /start.sh
RUN chmod +x /start.sh

# Railway assigns $PORT — default 80 for local docker run
ENV PORT=80
EXPOSE 80

CMD ["/start.sh"]
