#!/bin/sh
# Railway injects $PORT — substitute it into nginx config, leaving nginx
# variables like $uri and $remote_addr intact.
envsubst '${PORT}' < /tmp/nginx.conf.template > /etc/nginx/conf.d/default.conf
exec nginx -g 'daemon off;'
