"""Engine + session factory. SQLite by default (OCC_DB_URL can point at
Postgres, e.g. postgresql+psycopg://user:pass@host/occ)."""
import os

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from .config import APP_DATA_DIR

APP_DATA_DIR.mkdir(parents=True, exist_ok=True)

DB_URL = os.environ.get('OCC_DB_URL', f"sqlite:///{APP_DATA_DIR / 'app_data.db'}")

connect_args = {'check_same_thread': False} if DB_URL.startswith('sqlite') else {}
engine = create_engine(DB_URL, connect_args=connect_args, future=True)

if DB_URL.startswith('sqlite'):
    @event.listens_for(engine, 'connect')
    def _set_sqlite_pragma(dbapi_conn, _):
        cur = dbapi_conn.cursor()
        cur.execute('PRAGMA foreign_keys=ON')
        cur.execute('PRAGMA journal_mode=WAL')
        cur.close()

SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, future=True)


def init_db():
    from .models import Base  # noqa: circular-safe
    Base.metadata.create_all(engine)


def get_db():
    """FastAPI dependency."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
