"""Consistent online backup of the local SQLite database, including WAL contents."""
from datetime import datetime, timezone
from pathlib import Path
import sqlite3
from app.database import engine
from app.config import BACKEND_DIR, settings


def main():
    if not settings.is_sqlite:
        raise SystemExit('This command supports SQLite only. Use pg_dump for PostgreSQL.')
    source=Path(engine.url.database).resolve()
    folder=BACKEND_DIR.parent/'backups'
    folder.mkdir(parents=True,exist_ok=True)
    target=folder/f"requests-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')}.db"
    with sqlite3.connect(source.as_uri()+'?mode=ro',uri=True) as src, sqlite3.connect(target) as dst:
        src.backup(dst)
        if dst.execute('PRAGMA integrity_check').fetchone()[0]!='ok':
            raise RuntimeError('Backup integrity check failed')
    print(target)


if __name__=='__main__':main()
