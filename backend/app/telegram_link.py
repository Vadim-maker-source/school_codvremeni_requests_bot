"""An authenticated employee grants a short-lived, single-use binding."""
import secrets
from datetime import timedelta
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, update
from sqlalchemy.orm import Session
from app.auth import current_user, digest
from app.config import settings
from app.database import get_db
from app.models import Staff, SystemState, now

router = APIRouter(prefix='/api/me/telegram', tags=['Telegram'])


@router.get('')
def status(user: Staff = Depends(current_user)):
    return {'linked': bool(user.telegram_id), 'bot_username': settings.telegram_bot_username}


@router.post('')
def link(user: Staff = Depends(current_user), db: Session = Depends(get_db)):
    if not settings.telegram_configured or not settings.telegram_bot_username:
        raise HTTPException(503, 'Бот ещё не настроен')
    lock(db)
    token = secrets.token_urlsafe(24)
    user.telegram_link_hash = digest(token)
    user.telegram_link_expires = now() + timedelta(minutes=10)
    db.commit()
    return {'url': f'https://t.me/{settings.telegram_bot_username}?start=link_{token}', 'expires_in': 600}


@router.delete('')
def unlink(user: Staff = Depends(current_user), db: Session = Depends(get_db)):
    lock(db)
    user.telegram_id = user.telegram_link_hash = user.telegram_link_expires = None
    db.commit()
    return {'linked': False}


def lock(db):
    # Reuse the administration lock: bindings serialize in PostgreSQL and SQLite.
    db.execute(update(SystemState).where(SystemState.key == 'staff_guard').values(value=SystemState.value + 1))
    db.expire_all()


def bind(db: Session, token: str, user_id: str):
    lock(db)
    employee = db.scalar(select(Staff).where(Staff.telegram_link_hash == digest(token),
        Staff.telegram_link_expires > now(), Staff.active.is_(True)))
    if not employee:
        return 'Ссылка использована или истекла. Получите новую в кабинете.'
    existing = db.scalar(select(Staff).where(Staff.telegram_id == user_id))
    if existing and existing.id != employee.id:
        return 'Этот Telegram уже связан с другой учётной записью. Сначала отвяжите её в кабинете.'
    employee.telegram_id = user_id
    employee.telegram_link_hash = employee.telegram_link_expires = None
    db.commit()
    role = 'Администратор' if employee.role == 'admin' else 'Оператор'
    return f'Telegram подключён: {employee.name} · {role}. Уведомления включены.'
