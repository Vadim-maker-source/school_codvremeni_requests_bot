from datetime import timedelta
from hashlib import sha256
import secrets
from argon2 import PasswordHasher
from argon2.exceptions import VerificationError, InvalidHashError
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import select, func, delete, update
from sqlalchemy.orm import Session
from app.config import settings
from app.database import get_db
from app.models import Staff, ServerSession, LoginAttempt, SystemState, now
from app.schemas import LoginInput, StaffOut

router = APIRouter(prefix='/api/auth', tags=['Авторизация'])
hasher = PasswordHasher()
dummy_hash = hasher.hash(secrets.token_urlsafe(24))


def digest(value: str):
    return sha256(value.encode()).hexdigest()


def current_user(request: Request, db: Session = Depends(get_db)) -> Staff:
    token = request.cookies.get(settings.cookie_name, '')
    session = db.scalar(select(ServerSession).where(ServerSession.token_hash == digest(token), ServerSession.revoked.is_(False), ServerSession.expires_at > now()))
    user = db.get(Staff, session.staff_id) if session else None
    if not user or not user.active:
        raise HTTPException(401, 'Войдите в систему')
    if request.method not in ('GET', 'HEAD', 'OPTIONS'):
        csrf = request.headers.get('x-csrf-token', '')
        if not csrf or not secrets.compare_digest(digest(csrf), session.csrf_hash):
            raise HTTPException(403, 'Проверка безопасности не пройдена. Обновите страницу')
    request.state.session_id = session.id
    return user


def admin_user(user: Staff = Depends(current_user)):
    if user.role != 'admin':
        raise HTTPException(403, 'Доступно только администратору')
    return user


@router.post('/login', response_model=StaffOut)
def login(data: LoginInput, request: Request, response: Response, db: Session = Depends(get_db)):
    # All workers share the rate-limit log. The IP is hashed and proxy headers are not trusted.
    bucket = digest(request.client.host if request.client else 'local')
    db.execute(update(SystemState).where(SystemState.key == 'login_guard').values(value=SystemState.value + 1))
    cutoff = now() - timedelta(seconds=settings.login_window_seconds)
    db.execute(delete(LoginAttempt).where(LoginAttempt.created_at < cutoff))
    count = db.scalar(select(func.count()).select_from(LoginAttempt).where(LoginAttempt.bucket == bucket))
    if count >= settings.login_max_attempts:
        db.commit()
        raise HTTPException(429, 'Слишком много попыток. Повторите через несколько минут', headers={'Retry-After': str(settings.login_window_seconds)})
    db.add(LoginAttempt(bucket=bucket))
    db.commit()
    user = db.scalar(select(Staff).where(Staff.login == data.login.strip().lower()))
    valid = False
    try:
        valid = hasher.verify(user.password_hash if user else dummy_hash, data.password)
    except (VerificationError, InvalidHashError):
        pass
    if not user or not user.active or not valid:
        raise HTTPException(401, 'Неверный логин или пароль')
    token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    ttl = settings.session_ttl_hours * 3600
    db.add(ServerSession(staff_id=user.id, token_hash=digest(token), csrf_hash=digest(csrf), expires_at=now() + timedelta(seconds=ttl)))
    db.commit()
    response.set_cookie(settings.cookie_name, token, httponly=True, secure=settings.cookie_secure, samesite='lax', max_age=ttl, path='/')
    response.set_cookie(settings.csrf_cookie_name, csrf, httponly=False, secure=settings.cookie_secure, samesite='lax', max_age=ttl, path='/')
    response.headers['Cache-Control'] = 'no-store'
    return user


@router.get('/me', response_model=StaffOut)
def me(user: Staff = Depends(current_user)):
    return user


@router.post('/logout')
def logout(request: Request, response: Response, user: Staff = Depends(current_user), db: Session = Depends(get_db)):
    db.get(ServerSession, request.state.session_id).revoked = True
    db.commit()
    response.delete_cookie(settings.cookie_name, path='/')
    response.delete_cookie(settings.csrf_cookie_name, path='/')
    return {'message': 'Вы вышли из системы'}
