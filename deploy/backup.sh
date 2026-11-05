#!/bin/sh
set -eu
umask 077
cd /opt/requestsbotweb
target="/opt/requestsbotweb/backups/requests-$(date -u +%Y%m%dT%H%M%SZ).dump"
docker compose -f compose.prod.yml exec -T db pg_dump -U requests -d requestsbotweb -Fc > "$target"
test -s "$target"
find /opt/requestsbotweb/backups -maxdepth 1 -type f -name 'requests-*.dump' -mtime +14 -delete
