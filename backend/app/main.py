import logging
import time
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm.exc import StaleDataError
from app.config import settings
from app.database import engine
from app import auth, tickets, staff, categories, stats, telegram_link

if settings.environment == 'production' and not settings.cookie_secure:
    raise RuntimeError('Production requires COOKIE_SECURE=true')

app = FastAPI(title='Заявка · Школьный сервис', version='1.0.0')
for router in (auth.router, tickets.router, staff.router, categories.router, stats.router, telegram_link.router):
    app.include_router(router)


@app.middleware('http')
async def security(request: Request, call_next):
    if request.method not in ('GET', 'HEAD', 'OPTIONS'):
        origin = request.headers.get('origin')
        if (origin and origin not in settings.allowed_origins_list) or request.headers.get('sec-fetch-site') == 'cross-site':
            return JSONResponse({'error': {'message': 'Источник запроса не разрешён'}}, status_code=403)
        # Login has no existing session: browser requests must pass origin verification.
        if request.url.path == '/api/auth/login' and request.headers.get('sec-fetch-site') and not origin:
            return JSONResponse({'error': {'message': 'Источник запроса не определён'}}, status_code=403)
    response = await call_next(request)
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['Cache-Control'] = 'no-store'
    return response


@app.exception_handler(HTTPException)
async def http_error(request, exc):
    return JSONResponse({'error': {'message': str(exc.detail)}}, status_code=exc.status_code, headers=exc.headers)


@app.exception_handler(RequestValidationError)
async def validation_error(request, exc):
    fields = ['.'.join(map(str, error['loc'][1:])) for error in exc.errors()]
    return JSONResponse({'error': {'message': 'Проверьте обязательные поля, длину и формат значений', 'fields': fields}}, status_code=422)


@app.exception_handler(StaleDataError)
async def stale_error(request, exc):
    return JSONResponse({'error': {'message': 'Заявка уже изменена другим сотрудником. Обновите данные и повторите действие'}}, status_code=409)


@app.exception_handler(IntegrityError)
async def integrity_error(request, exc):
    return JSONResponse({'error': {'message': 'Запись конфликтует с существующими данными'}}, status_code=409)


@app.exception_handler(OperationalError)
async def database_error(request, exc):
    return JSONResponse({'error': {'message': 'База временно занята или недоступна. Повторите запрос'}}, status_code=503)


@app.exception_handler(Exception)
async def internal_error(request, exc):
    # Never log request payloads, credentials, SQL parameters or exception text.
    logging.getLogger('app').error('Unhandled error type: %s', type(exc).__name__)
    return JSONResponse({'error': {'message': 'Не удалось выполнить запрос. Попробуйте ещё раз'}}, status_code=500)


@app.get('/api/health', tags=['Готовность'])
def health():
    with engine.connect() as connection:
        connection.execute(text('SELECT 1'))
        connection.execute(text('SELECT id FROM staff LIMIT 1'))
        heartbeat = connection.execute(text("SELECT value FROM system_state WHERE key='telegram_heartbeat'")).scalar()
    active = heartbeat and time.time() - heartbeat < 30
    return {'status': 'ok', 'database': 'ok',
            'bot': 'running' if active else 'stopped',
            'notifications': ('running' if active else 'waiting_for_bot') if settings.notifications_enabled else 'disabled'}
