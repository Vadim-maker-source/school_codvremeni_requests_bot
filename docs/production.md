# Продакшен «Заявка»

Адрес: https://152.234.209.198

Приложение, PostgreSQL и aiogram запущены в Docker Compose на VPS, каталог /opt/requestsbotweb. Перед ними работает Nginx. Существующие домены и сервисы сервера сохранены.

Перенесены 4 заявки, 3 учётные записи, 15 событий истории, 3 группы / 9 элементов и Telegram-привязки. Вход — прежними логинами и паролями. Веб-сессии и одноразовые ссылки привязки сброшены. Локальный бот остановлен и отключён, чтобы не конфликтовать с VPS; локальная база и исходный дамп сохранены.

## Проверки

- 63 теста прошли внутри серверного Docker-образа.
- Совпали количества записей всех переносимых таблиц; активные сессии и попытки входа исключены.
- HTTPS проверен Python-клиентом и браузером с обычной проверкой сертификата, TLS 1.3.
- HTTP перенаправляет на HTTPS. Cookies Secure / HttpOnly / SameSite, проверка CSRF и разграничение администратора/оператора прошли.
- В браузере проверены вход, 4 заявки, статистика, сотрудники, мобильный экран 375px и выход; runtime ошибок нет.
- PostgreSQL, API, web и bot healthy. База и API не публикуют порты наружу; web доступен только на loopback 3080.
- Alembic check и Nginx config test выполняются на VPS.
- Для IP-сертификата настроен отдельный timer проверки продления каждые 6 часов; certbot renew --dry-run с deploy-hook прошёл.
- Ежедневный pg_dump хранится в /opt/requestsbotweb/backups, срок хранения автоматических копий — 14 дней. Исходный дамп переноса сохраняется отдельно. Проверено восстановление автоматической копии в отдельную временную БД; количества заявок, сотрудников, истории и категорий совпали.

## Управление по SSH

Из /opt/requestsbotweb:
- docker compose -f compose.prod.yml ps
- docker compose -f compose.prod.yml logs --tail 100 api bot
- docker compose -f compose.prod.yml restart api bot web
- docker compose -f compose.prod.yml up -d --build --wait
- /opt/requestsbotweb/backup.sh

Timers: requestsbotweb-cert-renew.timer и requestsbotweb-backup.timer. Секреты находятся в /opt/requestsbotweb/.env и не включены в образы/документы.

При переносе обратно сначала остановить серверный бот. Два polling одного Telegram-токена одновременно не запускать.
