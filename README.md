# Заявка · Школьный сервис

[Запуск и перезапуск Docker](docs/docker-guide.md) · [Новое развёртывание](deploy/README.md)

Продакшен: https://152.234.209.198 — Docker / PostgreSQL / aiogram / Nginx / HTTPS. [Управление и проверки](docs/production.md). Локальный polling выключен после переноса; одновременно с VPS его не запускать.

Рабочая система приёма и обработки школьных обращений: сотрудники принимают заявки в веб-кабинете, назначают исполнителей, фиксируют результат и видят историю. Telegram-бот на aiogram принимает заявки, проверяет статус и доставляет уведомления через транзакционную очередь. Привязка сотрудников — одноразовой ссылкой из кабинета.

Стек: Next.js 16, React 19, TypeScript, Tailwind CSS 4; FastAPI, Pydantic, SQLAlchemy 2, Alembic, Argon2. Рабочая локальная БД — PostgreSQL через psycopg 3; SQLite используется для изолированных тестов. Python 3.12+, Node.js 22.9+ (проверено на Python 3.12.5 и Node 24.22.2). Docker для локальной работы не нужен.

## Быстрый запуск Windows

Откройте PowerShell в корне проекта.

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/start-local.ps1
```

Скрипт проверяет окружение, при необходимости устанавливает зависимости в `backend/.venv` и `node_modules`, создаёт `backend/.env` из примера, применяет миграции, выполняет безопасную инициализацию, собирает Next.js и запускает скрытые фоновые процессы. По умолчанию сайт: [http://localhost:3000](http://localhost:3000), Swagger: [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs). Если localhost в вашей системе медленно разрешается в IPv6, используйте [http://127.0.0.1:3000](http://127.0.0.1:3000). При занятых портах скрипт выбирает свободные и выводит фактические адреса. Он не останавливает чужие приложения.

Фактические адреса и PID: `.local/processes.json`. Логи: `.local/api.log`, `.local/api-error.log`, `.local/web.log`, `.local/web-error.log`. Повторный запуск уже работающей системы безопасен. Для режима разработки: `scripts/start-local.ps1 -Dev`.

Для локального PostgreSQL укажите `DATABASE_URL=postgresql+psycopg://USER:PASSWORD@127.0.0.1:5432/DB_NAME` в `backend/.env`. База должна быть создана заранее. Если приложение уже запущено, остановите его перед сменой базы.

Учётные записи создаются один раз: `admin` и `operator`. Пароли генерируются либо берутся из `BOOTSTRAP_ADMIN_PASSWORD` / `BOOTSTRAP_OPERATOR_PASSWORD` при первой инициализации. Получить локальные данные:

```powershell
Get-Content backend/data/local_credentials.json
```

Этот файл исключён из Git. Не пересылайте его. Повторная инициализация не меняет пароли, имена, роли или классификаторы. Файл содержит первоначальные пароли; административная смена пароля его не обновляет. Если вы намеренно удалили БД, сначала переместите прежний файл учётных данных в защищённую резервную копию: bootstrap откажется перезаписать существующий файл.

Остановка только процессов этого проекта с проверкой PID и времени запуска:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/stop-local.ps1
```

После изменения исходников остановите приложение, выполните `npm.cmd run build`, затем запустите снова. При изменении API-порта startup сам пересобирает адрес proxy. Нельзя переносить Windows standalone-сборку на Linux: контейнер собирает её заново.

## Структура

```text
app/                   Next.js App Router, стили, metadata
components/            кабинет, формы, карточка, административные разделы
lib/                   API-клиент и типы
public/                локальные статические файлы
backend/app/           настройки, модели, схемы, авторизация, сервисы, маршруты
backend/alembic/       воспроизводимые миграции
backend/tests/         изолированные тесты, HTTP-нагрузка, браузерный запуск
backend/data/          requests.db и локальные учётные данные (вне Git)
scripts/               запуск, остановка, браузерный сценарий
docs/                  инструкции, архитектура, Telegram, измерения
work/original-backend/ сохранённая исходная заготовка backend (вне Git)
```

## Ручная установка и конфигурация

```powershell
python -m venv backend/.venv
backend/.venv/Scripts/python.exe -m pip install -r backend/requirements.txt
npm.cmd ci
Copy-Item backend/.env.example backend/.env
Push-Location backend
.venv/Scripts/python.exe -m app.bootstrap
Pop-Location
```

`requirements.lock.txt` фиксирует фактически установленное окружение Windows; `requirements.txt` содержит совместимые прямые зависимости для Windows/Linux. npm использует `package-lock.json`. Ничего не устанавливается глобально.

Основные настройки backend: `DATABASE_URL`, `ALLOWED_ORIGINS`, `COOKIE_SECURE`, `SESSION_TTL_HOURS`, `LOGIN_MAX_ATTEMPTS`, `LOGIN_WINDOW_SECONDS`. По умолчанию БД находится в `backend/data/requests.db`, независимо от текущей папки процесса. Относительный SQLite-путь считается от `backend/`. Пример: `DATABASE_URL=sqlite:///data/requests.db`. `API_INTERNAL_URL` задаёт backend для Next.js во время сборки. Не меняйте имена cookies без согласованного изменения веб-клиента.

## Правила

Новая → В работе → Выполнена / Отклонена. Назначение и переназначение сохраняют статус; «Взять в работу» назначает текущего сотрудника и меняет статус. Закрытие возможно только из работы с непустым результатом. Закрытые карточки доступны для просмотра. Сервер проверяет права, активность категории и исполнителя, переходы и версию заявки. При конфликте — HTTP 409 и обновление карточки. Номера формируются из атомарного ID базы, без `MAX(id)+1`.

Оператор работает с заявками и общими счётчиками; администратор дополнительно управляет сотрудниками, классификаторами и подробной статистикой. Регистрации извне нет. Деактивация предпочтительнее удаления. Подробности: [руководство оператора](docs/operator-guide.md).

## Проверки

```powershell
Push-Location backend
.venv/Scripts/python.exe -m pytest tests -q
.venv/Scripts/python.exe -m pip check
.venv/Scripts/python.exe -m alembic check
Pop-Location
npm.cmd run typecheck
npm.cmd run build
npm.cmd audit --omit=dev
backend/.venv/Scripts/python.exe backend/tests/test_http_instance.py --seconds 15 --clients 4
backend/.venv/Scripts/python.exe backend/tests/run_browser.py
```

Backend-тесты применяют миграции к временным отдельным БД. HTTP- и браузерный сценарии сами запускают отдельные экземпляры, не трогают рабочие данные и не обращаются в Telegram. Браузерная проверка использует установленный Edge/Chrome; можно задать `BROWSER_EXE`. При их отсутствии установите браузер Playwright командой `npx.cmd playwright install chromium`. Скриншоты и отчёт — `work/browser/`. Если тест прерван извне, проверьте созданные им процессы перед повтором; штатный выход завершает только собственное дерево процессов.

Проверяемый цикл: создать → найти в списке → открыть → взять в работу → переназначить → закрыть с результатом → проверить историю и статистику. Результаты и ограничения: [проверки](docs/verification.md), [нагрузка](docs/performance.md).

## Резервное копирование

Не копируйте один `.db` отдельно от работающего WAL. Используйте SQLite Backup API:

```powershell
Push-Location backend
.venv/Scripts/python.exe -m app.backup
Pop-Location
```

Копия создаётся в `backups/` и исключена из Git. Для восстановления остановите приложение, сохраните текущие `.db`, `.db-wal`, `.db-shm` в отдельной папке, поместите проверенную резервную копию как `backend/data/requests.db` и запустите приложение. Старые WAL/SHM не должны оставаться рядом с восстановленным файлом. Учётные данные храните отдельно и защищённо.

## Будущий production с PostgreSQL

Подготовлены `backend/.env.production.example`, оба Dockerfile и `compose.yml`. Нужны собственные пароли, URL-encoded `DATABASE_URL=postgresql+psycopg://...`, `PUBLIC_ORIGIN=https://...`, HTTPS reverse proxy, `COOKIE_SECURE=true`, закрытый внешний доступ к API/БД. Запуск API в production с `COOKIE_SECURE=false` запрещён конфигурацией. В Compose нет паролей по умолчанию; обязательные переменные задаются снаружи.

Одна смена `DATABASE_URL` **не переносит данные**. Сначала сделайте резервную копию, примените Alembic к новой PostgreSQL, затем перенесите данные с сохранением ID и связей отдельной процедурой. Установите значения PostgreSQL sequences выше перенесённых ID; не переносите действующие сессии. Сверьте количество записей, номера, историю и контрольные сценарии на тестовом стенде. После этого планируйте переключение с остановкой записи и возможностью возврата.

[Архитектура](docs/architecture.md) · [Демонстрация](docs/demo.md) · [Telegram: подача, привязка и уведомления](docs/telegram-next-stage.md).
