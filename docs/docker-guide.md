# Запуск и управление «Заявкой»

Сайт: https://152.234.209.198. Бот: https://t.me/school_codvremeni_requests_bot.

## Подключение к серверу

Распакуйте архив SSH-ключей. В PowerShell выполните, указав свой путь к файлу без расширения:

```powershell
ssh -i "C:\путь\carambola_vps_ed25519" root@152.234.209.198
```

При первом подключении SSH покажет отпечаток сервера. Эталонный отпечаток находится в файле SSH_HOST_FINGERPRINT.txt рядом с этим руководством в архиве передачи. Сверьте его перед подтверждением.

После входа:

```bash
cd /opt/requestsbotweb
```

Все следующие команды выполняются в этой папке на сервере. Не запускайте второй экземпляр бота на компьютере с тем же токеном.

## Запуск, проверка и перезапуск

```bash
# Запустить уже собранные контейнеры и дождаться готовности
docker compose -f compose.prod.yml up -d --wait

# Статус: у всех четырёх сервисов должно быть healthy
docker compose -f compose.prod.yml ps

# Перезапустить сайт, API и бота, сохранив БД
docker compose -f compose.prod.yml restart api bot web

# Перезапустить только бота
docker compose -f compose.prod.yml restart bot

# Последние сообщения сервера и бота
docker compose -f compose.prod.yml logs --tail 100 api bot

# Смотреть новые сообщения; Ctrl+C завершает просмотр логов
docker compose -f compose.prod.yml logs -f --tail 50 bot
```

Сервисы: db — PostgreSQL, api — FastAPI, web — Next.js, bot — aiogram и отправитель очереди. Бот получает сообщения через long polling; входящего Nginx/webhook для него нет.

## Остановка

```bash
# Остановить всё, сохранив контейнеры и данные
docker compose -f compose.prod.yml stop

# Остановить и удалить контейнеры; именованные тома БД сохранятся
docker compose -f compose.prod.yml down
```

Не добавляйте флаг -v к down: он удаляет тома с базой. Не выполняйте docker system prune --volumes для очистки сервера. Данные БД находятся в Docker volume requestsbotweb_pgdata, а не в папке исходников.

## После изменения кода или .env

Сначала создайте резервную копию:

```bash
/opt/requestsbotweb/backup.sh
```

После изменения Python-кода пересоберите API-образ и пересоздайте также контейнер бота:

```bash
docker compose -f compose.prod.yml build api
docker compose -f compose.prod.yml up -d --force-recreate api bot --wait
```

После изменения интерфейса:

```bash
docker compose -f compose.prod.yml build web
docker compose -f compose.prod.yml up -d web --wait
```

После изменения .env нужен пересозданный контейнер — обычный restart не перечитывает его:

```bash
docker compose -f compose.prod.yml up -d --force-recreate api bot --wait
```

DATABASE_URL и POSTGRES_PASSWORD должны соответствовать друг другу. Смена POSTGRES_PASSWORD в .env не меняет пароль уже созданной PostgreSQL: для этого требуется отдельная команда ALTER ROLE и согласованное обновление DATABASE_URL. Не меняйте эти значения для обычного перезапуска.

Миграции API выполняет при старте. Для проверки:

```bash
docker compose -f compose.prod.yml exec api python -m alembic current
docker compose -f compose.prod.yml exec api python -m alembic check
curl --fail https://152.234.209.198/api/health
```

## Nginx и HTTPS

```bash
# Проверить конфигурацию перед применением
nginx -t

# Применить настройки без остановки существующих соединений
systemctl reload nginx

# Проверить автоматическое продление и резервное копирование
systemctl list-timers 'requestsbotweb-*'

# Посмотреть журнал продления
journalctl -u requestsbotweb-cert-renew.service --no-pager -n 50

# Тест продления сертификата
/opt/requestsbotweb/certbot/bin/certbot renew --dry-run \
  --config-dir /opt/requestsbotweb/tls \
  --work-dir /opt/requestsbotweb/tls-work \
  --logs-dir /opt/requestsbotweb/tls-logs
```

На VPS уже есть другие сервисы. Основной порт 443 обслуживает существующий Nginx stream: запросы приложения передаются на 127.0.0.1:38443, затем на web 127.0.0.1:3080. Сохраняйте существующие маршруты. Файлы этого проекта находятся в deploy/nginx и deploy/systemd. Сертификаты — /opt/requestsbotweb/tls; в GitHub приватные ключи сертификатов не входят.

## Резервная копия и восстановление

```bash
/opt/requestsbotweb/backup.sh
ls -lh /opt/requestsbotweb/backups
```

Копии создаются ежедневно и хранятся 14 дней. Для восстановления сначала сохраните текущую БД и остановите запись:

```bash
/opt/requestsbotweb/backup.sh
docker compose -f compose.prod.yml stop api bot web
```

Проверьте выбранный дамп восстановлением в отдельную БД. Следующие команды заменяют рабочую БД — выполняйте их только после проверки имени и наличия резервной копии:

```bash
docker compose -f compose.prod.yml exec -T db \
  dropdb -U requests requestsbotweb
docker compose -f compose.prod.yml exec -T db \
  createdb -U requests requestsbotweb
docker compose -f compose.prod.yml exec -T db \
  pg_restore --exit-on-error --no-owner --no-acl -U requests -d requestsbotweb \
  < /opt/requestsbotweb/backups/ИМЯ_ПРОВЕРЕННОЙ_КОПИИ.dump
docker compose -f compose.prod.yml up -d --wait
```

Для нового сервера используйте приватный ZIP с кодом и .env либо создайте .env по .env.example. Сначала запустите только db, восстановите приложенный дамп в пустую requestsbotweb, затем запускайте остальные сервисы. Копию ключей держите отдельно. Подробные шаги нового развёртывания находятся в deploy/README.md.
