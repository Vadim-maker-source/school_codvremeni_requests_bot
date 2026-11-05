# Backend для сокомандников

Проект: FastAPI + Pydantic + синхронный SQLAlchemy 2 + Alembic. Локальная БД — SQLite `backend/data/requests.db`; PostgreSQL предусмотрен конфигурацией, но не запускался. Готовый frontend Next.js обращается через `/api/*` proxy. Для ручных запросов доступны Burp/Postman/curl/HTTPX. Сегодня источник обращения — web; Telegram ещё не реализован.

## На одном компьютере

Запуск всего проекта из корня: `powershell -NoProfile -ExecutionPolicy Bypass -File scripts/start-local.ps1`.

- Сайт: http://127.0.0.1:3000
- API: http://127.0.0.1:8000
- Swagger/OpenAPI: http://127.0.0.1:8000/docs и `/openapi.json`
- Готовность: `GET /api/health`

Фактические порты смотрите в выводе или `.local/processes.json`. Проверенный пример без авторизации:

```powershell
curl.exe http://127.0.0.1:8000/api/health
```

## С другого ноутбука в одной сети

`localhost` на компьютере сокомандника указывает на **его собственный компьютер**, а не на ноутбук, где запущен backend. Сейчас стандартный скрипт запуска слушает только loopback; с другого компьютера API по умолчанию недоступен. Это не было включено автоматически.

Владелец backend может явно открыть отдельный LAN-экземпляр. Оба компьютера должны быть в одной доверенной Wi-Fi/LAN, без изоляции клиентов. Найдите IPv4 владельца через `ipconfig`. Затем в отдельном PowerShell из `backend/`:

```powershell
.venv/Scripts/python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8001 --no-access-log
```

Порт 8001 нужен, чтобы не конфликтовать со стандартным локальным API на 8000. Этот экземпляр использует ту же конфигурацию и ту же SQLite. Не запускайте два bootstrap одновременно. Остановка отдельного foreground-экземпляра — Ctrl+C в его окне; `stop-local.ps1` управляет только процессами стандартного запуска.

У сокомандника адрес будет, например, `http://192.168.1.50:8001/api/health` (замените IP настоящим). Swagger — `http://192.168.1.50:8001/docs`. В Windows Firewall может понадобиться разрешение Python/выбранного входящего TCP-порта для частной сети; здесь оно не создавалось. Не открывайте этот порт на роутере в интернет.

Для Burp Repeater target — этот IP, port 8001, HTTP. В raw-шаблонах замените Host, используйте свои полученные cookies. Пароли и сессии выдаются владельцем отдельно; не нужно пересылать всей команде `.env` администратора.

Browser fetch с чужого origin сейчас не настроен: ALLOWED_ORIGINS проверяет Origin/CSRF, но сам по себе не включает CORS. Для совместной frontend-разработки требуется согласованный same-origin proxy либо отдельная явная CORS-конфигурация. Для Burp/Postman/CLI, не отправляющих Origin, это не мешает. Запрос login через LAN Swagger отправляет Origin адреса Swagger: владельцу нужно добавить именно `http://<его-LAN-IP>:8001` в ALLOWED_ORIGINS окружения этого API перед запуском и перезапустить; не добавляйте `*`.

## Авторизация

`POST /api/auth/login`, JSON `{ "login": "...", "password": "..." }` → 200 + cookies `shkola_session` и `shkola_csrf`. В ответах нет пароля/хеша. Для дальнейших запросов сохраняйте cookies. Для POST/PUT также нужен `X-CSRF-Token` со значением shkola_csrf.

```http
Cookie: shkola_session=<session>; shkola_csrf=<csrf>
X-CSRF-Token: <csrf>
Content-Type: application/json
```

`GET /api/auth/me` — текущий сотрудник. `POST /api/auth/logout` — отзыв сессии. Вход ограничен 10 попытками / 300 с; сессия живёт 12 ч. В Swagger одного Authorize недостаточно: схема основана на cookies и CSRF. Для изменяющих запросов проще использовать готовые Burp-шаблоны или веб-кабинет, где CSRF выставляется автоматически.

## Основные endpoints

| Метод / путь | Назначение |
|---|---|
| GET /api/categories | Группы и элементы, ID для формы |
| GET /api/staff | Сотрудники; оператору — активные |
| POST /api/staff | Создать сотрудника (admin) |
| PUT /api/staff/{id} | Имя, роль, активность, необязательный новый пароль (admin) |
| GET /api/tickets | Поиск, фильтры, пагинация |
| POST /api/tickets | Создать web-заявку |
| GET /api/tickets/{id} | Карточка и history |
| POST /api/tickets/{id}/actions | take / assign / complete / reject |
| GET /api/stats/summary | Общие реальные счётчики |
| GET /api/stats | Распределения по категориям/исполнителям (admin) |

Полная схема всех операций — в Swagger и `docs/openapi-at-export.json`.

Создание сотрудника: name, login, password (10–128 символов), role=operator/admin. Уникальный login, публичной регистрации нет. `operator` в UI называется исполнителем/оператором; отдельного значения executor нет.

Создание обращения:

```json
{
  "applicant_name": "Анна Петрова",
  "contact": "teacher@example.invalid",
  "group_id": 1,
  "item_id": 1,
  "description": "Не работает проектор в кабинете 204"
}
```

Сначала запросите реальные категории: item должен принадлежать group, обе записи активны. Строки из пробелов запрещены. В ответе 201 вернутся id, number и version. Номер предназначен человеку, id — для URL.

Изменение заявки, примеры отдельных тел:

```json
{"action":"take","version":2}
```

```json
{"action":"assign","assignee_id":3,"version":3}
```

```json
{"action":"complete","comment":"Кабель заменён, работа проверена","version":4}
```

Числа версий здесь иллюстративные. **Всегда брать последнюю version из фактического ответа.** Take из новой назначает текущего сотрудника и ставит in_progress. Assign назначает/переназначает активного сотрудника и не меняет статус. Complete/reject возможны только из in_progress с обязательным comment. Закрытые заявки не изменяются. История и outbox атомарны с заявкой.

Параметры списка: q (номер/описание), status, group_id, assignee_id (`0` — без исполнителя), date_from/date_to (дни Москвы), page ≥1, page_size 1–100. Не загружайте всю базу в браузер.

Ошибки единообразны: `{"error":{"message":"..."}}`; 401 нет сессии, 403 роль/CSRF/Origin, 404 нет объекта, 409 конфликт версии/перехода/уникальности, 422 валидация, 503 временная недоступность БД. При 409 перечитать карточку, показать актуальные данные и повторить осмысленное действие. Не повторять создание вслепую после сетевой ошибки: ключа идемпотентности веб-создания нет.

## Разработка и проверки

Из backend: `.venv/Scripts/python.exe -m pytest tests -q` и `.venv/Scripts/python.exe -m alembic check`. Тесты изолируют рабочую БД. Модели в app/models.py, валидация в schemas.py, бизнес-логика в ticket_service.py. Будущий бот должен вызывать этот сервис, не копировать правила. Поля Telegram относятся к Applicant, не Staff. Не принимать чужие Telegram ID через публичный API.

Текущая проверка: 37 тестов прошли на исходном компьютере. Подробная демонстрация с cookie/CSRF и raw-запросами — `docs/burp-demo.md`.
