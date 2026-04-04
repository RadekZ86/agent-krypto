from __future__ import annotations

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from sqlalchemy.pool import NullPool

from app.config import settings


connect_args = {"check_same_thread": False, "timeout": 30} if settings.database_url.startswith("sqlite") else {}
engine_options = {"future": True, "connect_args": connect_args}
if settings.database_url.startswith("sqlite"):
    engine_options["poolclass"] = NullPool

engine = create_engine(settings.database_url, **engine_options)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


if settings.database_url.startswith("sqlite"):
    @event.listens_for(engine, "connect")
    def _set_sqlite_pragmas(dbapi_connection, connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


class Base(DeclarativeBase):
    pass


def init_db() -> None:
    from app import models

    Base.metadata.create_all(bind=engine)

    # Lightweight column migrations for SQLite
    import sqlalchemy

    with engine.connect() as conn:
        inspector = sqlalchemy.inspect(engine)
        if "users" in inspector.get_table_names():
            columns = [col["name"] for col in inspector.get_columns("users")]
            if "trading_mode" not in columns:
                conn.execute(sqlalchemy.text("ALTER TABLE users ADD COLUMN trading_mode VARCHAR(16) DEFAULT 'PAPER'"))
                conn.commit()
            if "agent_mode" not in columns:
                conn.execute(sqlalchemy.text("ALTER TABLE users ADD COLUMN agent_mode VARCHAR(16) DEFAULT 'normal'"))
                conn.commit()