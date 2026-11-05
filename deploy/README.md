# Развёртывание на новом сервере

Текущая рабочая установка: /opt/requestsbotweb на 152.234.209.198. Для обычного запуска и перезапуска используйте [руководство](../docs/docker-guide.md).

## Содержимое передачи

- Приватный ZIP содержит исходники, compose.prod.yml, рабочий .env, дамп backups/production.dump и эти конфигурации.
- GitHub содержит исходники и .env.example. В нём нет рабочего .env, дампов, SSH-ключей и истории чата.
- Зависимости устанавливаются при сборке. node_modules, .venv и готовая Windows-сборка в ZIP не входят.

## Docker и данные

Установите Docker Engine и Compose из официального репозитория: https://docs.docker.com/engine/install/ubuntu/. Нужны также Nginx и python3-venv.

Распакуйте приватный ZIP в /opt/requestsbotweb, проверьте .env и ограничьте доступ:

```bash
cd /opt/requestsbotweb
chmod 700 /opt/requestsbotweb
chmod 600 .env
docker compose -f compose.prod.yml build api web
docker compose -f compose.prod.yml up -d db --wait
```

Если переносите существующую систему, восстановите дамп до первого запуска API, пока БД пустая:

```bash
docker compose -f compose.prod.yml exec -T db \
  pg_restore --exit-on-error --no-owner --no-acl -U requests -d requestsbotweb \
  < backups/production.dump
```

При создании новой пустой системы этот шаг пропускается: API сам применит миграции и создаст учётные записи по BOOTSTRAP_* в .env. Рабочие старые пароли сохраняются только при восстановлении БД.

## Сертификат IP и Nginx

Если IP меняется, обновите PUBLIC_ORIGIN и ALLOWED_ORIGINS в .env, server_name/redirect в конфигурациях и IP в команде выпуска сертификата.

Сначала настройте HTTP-01, без HTTPS:

```bash
install -d /var/www/requestsbotweb-acme/.well-known/acme-challenge
cp deploy/nginx/requestsbotweb-http.conf /etc/nginx/conf.d/requestsbotweb.conf
nginx -t && systemctl reload nginx
python3 -m venv /opt/requestsbotweb/certbot
/opt/requestsbotweb/certbot/bin/pip install 'certbot>=5.4,<6'
/opt/requestsbotweb/certbot/bin/certbot certonly --non-interactive \
  --agree-tos --register-unsafely-without-email \
  --preferred-profile shortlived --webroot \
  --webroot-path /var/www/requestsbotweb-acme \
  --ip-address 152.234.209.198 --cert-name requestsbotweb-ip \
  --config-dir /opt/requestsbotweb/tls \
  --work-dir /opt/requestsbotweb/tls-work \
  --logs-dir /opt/requestsbotweb/tls-logs
```

На новом сервере со свободным 443 используйте requestsbotweb-standalone.conf. На текущем VPS 443 занят существующим Nginx stream: там установлен requestsbotweb.conf с loopback 38443, а в существующую SNI-map добавлены две записи из stream-map-entries.conf. Не устанавливайте обе HTTPS-конфигурации одновременно и не заменяйте чужие маршруты.

```bash
# Для нового сервера со свободным портом 443
cp deploy/nginx/requestsbotweb-standalone.conf /etc/nginx/conf.d/requestsbotweb.conf
nginx -t && systemctl reload nginx

cp deploy/systemd/requestsbotweb-* /etc/systemd/system/
cp deploy/backup.sh /opt/requestsbotweb/backup.sh
chmod 700 /opt/requestsbotweb/backup.sh
install -d -m 700 /opt/requestsbotweb/backups
systemctl daemon-reload
systemctl enable --now requestsbotweb-cert-renew.timer requestsbotweb-backup.timer
docker compose -f compose.prod.yml up -d --wait
curl --fail https://152.234.209.198/api/health
```

Перед запуском bot остановите прежний экземпляр с тем же Telegram-токеном. После восстановления проверьте вход, 3×3 категории, количество заявок, привязки сотрудников, очередь и доставку сообщений.
