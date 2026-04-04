from __future__ import annotations

from datetime import datetime
import hashlib
import secrets

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class User(Base):
    """User account for multi-user support."""
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(128))
    salt: Mapped[str] = mapped_column(String(32))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    last_login: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    
    api_keys: Mapped[list[UserAPIKey]] = relationship(back_populates="user", cascade="all, delete-orphan")
    sessions: Mapped[list[UserSession]] = relationship(back_populates="user", cascade="all, delete-orphan")

    def set_password(self, password: str) -> None:
        self.salt = secrets.token_hex(16)
        self.password_hash = hashlib.sha256((password + self.salt).encode()).hexdigest()
    
    def check_password(self, password: str) -> bool:
        return self.password_hash == hashlib.sha256((password + self.salt).encode()).hexdigest()


class UserAPIKey(Base):
    """Binance API keys per user."""
    __tablename__ = "user_api_keys"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    exchange: Mapped[str] = mapped_column(String(32), default="binance")
    label: Mapped[str] = mapped_column(String(64))  # e.g. "Main Account", "Trading Bot"
    api_key: Mapped[str] = mapped_column(String(128))
    api_secret_encrypted: Mapped[str] = mapped_column(String(256))  # Encrypted
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_testnet: Mapped[bool] = mapped_column(Boolean, default=False)
    permissions: Mapped[str] = mapped_column(String(64), default="read")  # read, trade, withdraw
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    last_used: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    
    user: Mapped[User] = relationship(back_populates="api_keys")


class UserSession(Base):
    """Active user sessions."""
    __tablename__ = "user_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    token: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(256), nullable=True)
    
    user: Mapped[User] = relationship(back_populates="sessions")


class MarketData(Base):
    __tablename__ = "market_data"
    __table_args__ = (UniqueConstraint("symbol", "timestamp", "source", name="uq_market_data_symbol_timestamp_source"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    symbol: Mapped[str] = mapped_column(String(16), index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, index=True)
    open: Mapped[float] = mapped_column(Float)
    high: Mapped[float] = mapped_column(Float)
    low: Mapped[float] = mapped_column(Float)
    close: Mapped[float] = mapped_column(Float)
    volume: Mapped[float] = mapped_column(Float)
    source: Mapped[str] = mapped_column(String(32), default="coingecko")


class FeatureSnapshot(Base):
    __tablename__ = "features"
    __table_args__ = (UniqueConstraint("symbol", "timestamp", name="uq_features_symbol_timestamp"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    symbol: Mapped[str] = mapped_column(String(16), index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, index=True)
    rsi: Mapped[float] = mapped_column(Float)
    macd: Mapped[float] = mapped_column(Float)
    macd_signal: Mapped[float] = mapped_column(Float)
    ema20: Mapped[float] = mapped_column(Float)
    ema50: Mapped[float] = mapped_column(Float)
    trend: Mapped[str] = mapped_column(String(16))
    volume_change: Mapped[float] = mapped_column(Float)


class Decision(Base):
    __tablename__ = "decisions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    symbol: Mapped[str] = mapped_column(String(16), index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, index=True, default=datetime.utcnow)
    decision: Mapped[str] = mapped_column(String(16))
    confidence: Mapped[float] = mapped_column(Float)
    reason: Mapped[str] = mapped_column(Text)
    score: Mapped[int] = mapped_column(Integer, default=0)

    trades: Mapped[list[SimulatedTrade]] = relationship(back_populates="decision")


class SimulatedTrade(Base):
    __tablename__ = "simulated_trades"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    symbol: Mapped[str] = mapped_column(String(16), index=True)
    decision_id: Mapped[int | None] = mapped_column(ForeignKey("decisions.id"), nullable=True)
    buy_price: Mapped[float] = mapped_column(Float)
    sell_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    quantity: Mapped[float] = mapped_column(Float)
    buy_value: Mapped[float] = mapped_column(Float)
    sell_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    buy_fee: Mapped[float] = mapped_column(Float)
    sell_fee: Mapped[float | None] = mapped_column(Float, nullable=True)
    profit: Mapped[float | None] = mapped_column(Float, nullable=True)
    duration_minutes: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="OPEN", index=True)
    opened_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    decision: Mapped[Decision | None] = relationship(back_populates="trades")


class LearningLog(Base):
    __tablename__ = "learning_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    decision_id: Mapped[int | None] = mapped_column(ForeignKey("decisions.id"), nullable=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    result: Mapped[str] = mapped_column(String(32))
    was_profitable: Mapped[bool] = mapped_column()
    market_state: Mapped[str] = mapped_column(String(32))
    notes: Mapped[str] = mapped_column(Text)


class RuntimeSetting(Base):
    __tablename__ = "runtime_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    value: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class OpenAIUsageLog(Base):
    __tablename__ = "openai_usage_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    model: Mapped[str] = mapped_column(String(64))
    symbol: Mapped[str | None] = mapped_column(String(16), nullable=True)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0)
    estimated_cost_usd: Mapped[float] = mapped_column(Float, default=0.0)