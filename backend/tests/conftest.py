import os
import tempfile
from pathlib import Path

# Set BEFORE importing app modules: tests can never connect to the working database.
_test_root = tempfile.TemporaryDirectory(prefix='requests-tests-')
os.environ['DATABASE_URL'] = f"sqlite:///{(Path(_test_root.name) / 'bootstrap.db').as_posix()}"
os.environ['BOOTSTRAP_ADMIN_PASSWORD'] = 'TestAdmin_456!'
os.environ['BOOTSTRAP_OPERATOR_PASSWORD'] = 'TestOperator_456!'
os.environ['LOGIN_MAX_ATTEMPTS'] = '10'
os.environ['TELEGRAM_BOT_TOKEN'] = '123456:OFFLINE_ONLY_TEST_TOKEN'
os.environ['TELEGRAM_BOT_USERNAME'] = 'offline_test_bot'
os.environ['NOTIFICATIONS_ENABLED'] = 'false'

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from alembic import command
from alembic.config import Config
from app.config import BACKEND_DIR, settings
from app.database import get_db, _set_sqlite_pragmas
from app.bootstrap import seed
from app.main import app
from app import main


@pytest.fixture
def context(tmp_path, monkeypatch):
    url = f"sqlite:///{(tmp_path / 'test.db').as_posix()}"
    monkeypatch.setattr(settings, 'database_url', url)
    command.upgrade(Config(str(BACKEND_DIR / 'alembic.ini')), 'head')
    engine = create_engine(url, connect_args={'check_same_thread': False, 'timeout': 15})
    event.listen(engine, 'connect', _set_sqlite_pragmas)
    factory = sessionmaker(engine, expire_on_commit=False, autoflush=False)
    with factory() as db:
        seed(db)
        db.commit()
    def override():
        with factory() as db:
            yield db
    app.dependency_overrides[get_db] = override
    monkeypatch.setattr(main, 'engine', engine)
    clients = []
    def client(role='operator'):
        c = TestClient(app)
        clients.append(c)
        response = c.post('/api/auth/login', json={'login': role, 'password': 'TestAdmin_456!' if role == 'admin' else 'TestOperator_456!'})
        assert response.status_code == 200, response.text
        c.headers['X-CSRF-Token'] = c.cookies['shkola_csrf']
        return c
    yield {'client': client, 'factory': factory, 'anon': TestClient(app), 'engine': engine}
    for c in clients:
        c.close()
    app.dependency_overrides.clear()
    engine.dispose()
