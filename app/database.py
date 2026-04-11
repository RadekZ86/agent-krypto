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
            if "live_alloc_mode" not in columns:
                conn.execute(sqlalchemy.text("ALTER TABLE users ADD COLUMN live_alloc_mode VARCHAR(16) DEFAULT 'percent'"))
                conn.commit()
            if "live_alloc_value" not in columns:
                conn.execute(sqlalchemy.text("ALTER TABLE users ADD COLUMN live_alloc_value REAL DEFAULT 10.0"))
                conn.commit()
        if "live_order_log" in inspector.get_table_names():
            cols = [col["name"] for col in inspector.get_columns("live_order_log")]
            if "commission" not in cols:
                conn.execute(sqlalchemy.text("ALTER TABLE live_order_log ADD COLUMN commission REAL"))
                conn.commit()
            if "commission_asset" not in cols:
                conn.execute(sqlalchemy.text("ALTER TABLE live_order_log ADD COLUMN commission_asset VARCHAR(16)"))
                conn.commit()
        # Decision: store entry signals/indicators snapshot
        if "decisions" in inspector.get_table_names():
            cols = [col["name"] for col in inspector.get_columns("decisions")]
            if "signals_json" not in cols:
                conn.execute(sqlalchemy.text("ALTER TABLE decisions ADD COLUMN signals_json TEXT"))
                conn.commit()
        # LearningLog: rich indicator snapshots + signal tracking
        if "learning_log" in inspector.get_table_names():
            cols = [col["name"] for col in inspector.get_columns("learning_log")]
            _ll_migrations = {
                "symbol": "VARCHAR(16)",
                "profit_pct": "REAL",
                "hold_hours": "REAL",
                "entry_signals_json": "TEXT",
                "entry_rsi": "REAL",
                "entry_macd_hist": "REAL",
                "entry_trend": "VARCHAR(16)",
                "entry_up_prob": "REAL",
                "entry_bb_pos": "REAL",
                "exit_rsi": "REAL",
                "exit_macd_hist": "REAL",
                "exit_trend": "VARCHAR(16)",
                "exit_up_prob": "REAL",
            }
            for col_name, col_type in _ll_migrations.items():
                if col_name not in cols:
                    conn.execute(sqlalchemy.text(f"ALTER TABLE learning_log ADD COLUMN {col_name} {col_type}"))
                    conn.commit()