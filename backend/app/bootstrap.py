"""python -m app.bootstrap: migrations and idempotent first-run initialization."""
import json
import secrets
from pathlib import Path
from alembic import command
from alembic.config import Config
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.config import settings, BACKEND_DIR, DATA_DIR
from app.database import engine
from app.models import CategoryGroup, CategoryItem, Staff, SystemState
from app.auth import hasher


def migrate():
    command.upgrade(Config(str(BACKEND_DIR / 'alembic.ini')), 'head')


def seed(db: Session):
    for key in ('staff_guard', 'login_guard'):
        if not db.get(SystemState, key):
            db.add(SystemState(key=key, value=0))
    db.flush()
    if not db.get(SystemState, 'classifiers_initialized'):
        definitions = [('equipment', 'Оборудование', ['Проектор', 'Принтер', 'Компьютерный класс']),
                       ('rooms', 'Помещение', ['Кабинет', 'Коридор', 'Столовая']),
                       ('service', 'Обслуживание', ['Wi-Fi', 'Электрика', 'Мебель'])]
        for order, (key, name, children) in enumerate(definitions):
            group = CategoryGroup(seed_key=key, name=name, sort_order=order)
            db.add(group)
            db.flush()
            for pos, item_name in enumerate(children):
                db.add(CategoryItem(seed_key=f'{key}_{pos}', group_id=group.id, name=item_name, sort_order=pos))
        db.add(SystemState(key='classifiers_initialized', value=1))
    credentials = {}
    if not db.get(SystemState, 'staff_initialized'):
        for role, name, login, supplied in (
            ('admin', 'Администратор', settings.bootstrap_admin_login, settings.bootstrap_admin_password),
            ('operator', 'Оператор', settings.bootstrap_operator_login, settings.bootstrap_operator_password),
        ):
            if db.scalar(select(Staff).where(Staff.login == login)):
                continue
            password = supplied or secrets.token_urlsafe(18)
            db.add(Staff(name=name, login=login, password_hash=hasher.hash(password), role=role))
            credentials[role] = {'login': login, 'password': password}
        db.add(SystemState(key='staff_initialized', value=1))
    db.flush()
    return credentials


def main():
    migrate()
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    credentials_path = DATA_DIR / 'local_credentials.json'
    with Session(engine) as db:
        credentials = seed(db)
        if credentials:
            # Keep credentials before commit so a disk failure cannot silently lose generated passwords.
            with credentials_path.open('x', encoding='utf-8') as handle:
                json.dump(credentials, handle, ensure_ascii=False, indent=2)
            try:
                db.commit()
            except Exception:
                credentials_path.unlink(missing_ok=True)
                raise
        else:
            db.commit()
    print('Initialization complete. Local credentials: backend/data/local_credentials.json')


if __name__ == '__main__':
    main()
