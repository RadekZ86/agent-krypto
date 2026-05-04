from __future__ import annotations

from datetime import datetime
import hashlib
import secrets

from django.db import models


class User(models.Model):
    """User account for multi-user support."""

    class Meta:
        db_table = "users"

    email = models.CharField(max_length=255, unique=True, db_index=True)
    username = models.CharField(max_length=64, unique=True, db_index=True)
    password_hash = models.CharField(max_length=128)
    salt = models.CharField(max_length=32)
    is_active = models.BooleanField(default=True)
    trading_mode = models.CharField(max_length=16, default="PAPER")
    agent_mode = models.CharField(max_length=16, default="normal")
    live_alloc_mode = models.CharField(max_length=16, default="percent")
    live_alloc_value = models.FloatField(default=10.0)
    created_at = models.DateTimeField(default=datetime.utcnow)
    last_login = models.DateTimeField(null=True, blank=True)

    def set_password(self, password: str) -> None:
        self.salt = secrets.token_hex(16)
        self.password_hash = hashlib.sha256((password + self.salt).encode()).hexdigest()

    def check_password(self, password: str) -> bool:
        return self.password_hash == hashlib.sha256((password + self.salt).encode()).hexdigest()


class UserAPIKey(models.Model):
    """Binance API keys per user."""

    class Meta:
        db_table = "user_api_keys"

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="api_keys", db_index=True)
    exchange = models.CharField(max_length=32, default="binance")
    label = models.CharField(max_length=64)
    api_key = models.CharField(max_length=128)
    api_secret_encrypted = models.CharField(max_length=256)
    is_active = models.BooleanField(default=True)
    is_testnet = models.BooleanField(default=False)
    permissions = models.CharField(max_length=64, default="read")
    created_at = models.DateTimeField(default=datetime.utcnow)
    last_used = models.DateTimeField(null=True, blank=True)


class UserSession(models.Model):
    """Active user sessions."""

    class Meta:
        db_table = "user_sessions"

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="sessions", db_index=True)
    token = models.CharField(max_length=64, unique=True, db_index=True)
    created_at = models.DateTimeField(default=datetime.utcnow)
    expires_at = models.DateTimeField()
    ip_address = models.CharField(max_length=45, null=True, blank=True)
    user_agent = models.CharField(max_length=256, null=True, blank=True)


class MarketData(models.Model):

    class Meta:
        db_table = "market_data"
        constraints = [
            models.UniqueConstraint(fields=["symbol", "timestamp", "source"], name="uq_market_data_symbol_timestamp_source"),
        ]

    symbol = models.CharField(max_length=16, db_index=True)
    timestamp = models.DateTimeField(db_index=True)
    open = models.FloatField()
    high = models.FloatField()
    low = models.FloatField()
    close = models.FloatField()
    volume = models.FloatField()
    source = models.CharField(max_length=32, default="coingecko")


class FeatureSnapshot(models.Model):

    class Meta:
        db_table = "features"
        constraints = [
            models.UniqueConstraint(fields=["symbol", "timestamp"], name="uq_features_symbol_timestamp"),
        ]

    symbol = models.CharField(max_length=16, db_index=True)
    timestamp = models.DateTimeField(db_index=True)
    rsi = models.FloatField()
    macd = models.FloatField()
    macd_signal = models.FloatField()
    ema20 = models.FloatField()
    ema50 = models.FloatField()
    trend = models.CharField(max_length=16)
    volume_change = models.FloatField()


class Decision(models.Model):

    class Meta:
        db_table = "decisions"

    symbol = models.CharField(max_length=16, db_index=True)
    timestamp = models.DateTimeField(default=datetime.utcnow, db_index=True)
    decision = models.CharField(max_length=16)
    confidence = models.FloatField()
    reason = models.TextField()
    score = models.IntegerField(default=0)
    signals_json = models.TextField(null=True, blank=True)


class SimulatedTrade(models.Model):

    class Meta:
        db_table = "simulated_trades"

    symbol = models.CharField(max_length=16, db_index=True)
    decision = models.ForeignKey(Decision, on_delete=models.SET_NULL, null=True, blank=True, related_name="trades")
    buy_price = models.FloatField()
    sell_price = models.FloatField(null=True, blank=True)
    quantity = models.FloatField()
    buy_value = models.FloatField()
    sell_value = models.FloatField(null=True, blank=True)
    buy_fee = models.FloatField()
    sell_fee = models.FloatField(null=True, blank=True)
    profit = models.FloatField(null=True, blank=True)
    duration_minutes = models.FloatField(null=True, blank=True)
    status = models.CharField(max_length=16, default="OPEN", db_index=True)
    opened_at = models.DateTimeField(default=datetime.utcnow, db_index=True)
    closed_at = models.DateTimeField(null=True, blank=True)


class LearningLog(models.Model):

    class Meta:
        db_table = "learning_log"

    decision_id = models.IntegerField(null=True, blank=True)
    timestamp = models.DateTimeField(default=datetime.utcnow, db_index=True)
    result = models.CharField(max_length=32)
    was_profitable = models.BooleanField()
    market_state = models.CharField(max_length=32)
    notes = models.TextField()
    symbol = models.CharField(max_length=16, null=True, blank=True, db_index=True)
    profit_pct = models.FloatField(null=True, blank=True)
    hold_hours = models.FloatField(null=True, blank=True)
    entry_signals_json = models.TextField(null=True, blank=True)
    entry_rsi = models.FloatField(null=True, blank=True)
    entry_macd_hist = models.FloatField(null=True, blank=True)
    entry_trend = models.CharField(max_length=16, null=True, blank=True)
    entry_up_prob = models.FloatField(null=True, blank=True)
    entry_bb_pos = models.FloatField(null=True, blank=True)
    exit_rsi = models.FloatField(null=True, blank=True)
    exit_macd_hist = models.FloatField(null=True, blank=True)
    exit_trend = models.CharField(max_length=16, null=True, blank=True)
    exit_up_prob = models.FloatField(null=True, blank=True)


class SignalPerformance(models.Model):
    """Tracks win/loss rate per buy signal for learning feedback."""

    class Meta:
        db_table = "signal_performance"

    signal_name = models.CharField(max_length=128, unique=True, db_index=True)
    total_fired = models.IntegerField(default=0)
    wins = models.IntegerField(default=0)
    losses = models.IntegerField(default=0)
    avg_profit_pct = models.FloatField(default=0.0)
    updated_at = models.DateTimeField(auto_now=True)


class WhaleAlert(models.Model):
    """Detected whale/anomaly events for later analysis."""

    class Meta:
        db_table = "whale_alerts"

    created_at = models.DateTimeField(default=datetime.utcnow, db_index=True)
    symbol = models.CharField(max_length=16, db_index=True)
    signal_type = models.CharField(max_length=32)
    whale_score = models.FloatField()
    vol_zscore = models.FloatField(default=0)
    vol_ratio = models.FloatField(default=1)
    price_change_pct = models.FloatField(default=0)
    obv_divergence = models.CharField(max_length=16, null=True, blank=True)
    details = models.TextField(null=True, blank=True)


class RuntimeSetting(models.Model):

    class Meta:
        db_table = "runtime_settings"

    key = models.CharField(max_length=64, unique=True, db_index=True)
    value = models.TextField()
    updated_at = models.DateTimeField(auto_now=True)


class OpenAIUsageLog(models.Model):

    class Meta:
        db_table = "openai_usage_log"

    created_at = models.DateTimeField(default=datetime.utcnow, db_index=True)
    model = models.CharField(max_length=64)
    symbol = models.CharField(max_length=16, null=True, blank=True)
    input_tokens = models.IntegerField(default=0)
    output_tokens = models.IntegerField(default=0)
    total_tokens = models.IntegerField(default=0)
    estimated_cost_usd = models.FloatField(default=0.0)


class LiveOrderLog(models.Model):
    """Log of every LIVE order attempt (success, error, skip)."""

    class Meta:
        db_table = "live_order_log"

    created_at = models.DateTimeField(default=datetime.utcnow, db_index=True)
    username = models.CharField(max_length=64)
    symbol = models.CharField(max_length=32)
    action = models.CharField(max_length=8)
    status = models.CharField(max_length=16)
    detail = models.TextField(null=True, blank=True)
    order_id = models.CharField(max_length=64, null=True, blank=True)
    allocation = models.FloatField(null=True, blank=True)
    quote_currency = models.CharField(max_length=8, null=True, blank=True)
    commission = models.FloatField(null=True, blank=True)
    commission_asset = models.CharField(max_length=16, null=True, blank=True)


class AuditLog(models.Model):
    """Security audit trail for sensitive operations."""

    class Meta:
        db_table = "audit_logs"

    user_id = models.IntegerField(null=True, blank=True, db_index=True)
    action = models.CharField(max_length=64, db_index=True)
    resource = models.CharField(max_length=64, default="")
    details = models.TextField(null=True, blank=True)
    ip_address = models.CharField(max_length=45, null=True, blank=True)
    timestamp = models.DateTimeField(default=datetime.utcnow, db_index=True)


class LeverageSimTrade(models.Model):
    """Paper-traded leverage (perpetual) position for agent learning."""

    class Meta:
        db_table = "leverage_sim_trades"

    symbol = models.CharField(max_length=16, db_index=True)
    side = models.CharField(max_length=8)
    leverage = models.FloatField(default=2.0)
    entry_price = models.FloatField()
    exit_price = models.FloatField(null=True, blank=True)
    quantity = models.FloatField()
    margin_used = models.FloatField()
    liquidation_price = models.FloatField()
    take_profit = models.FloatField(null=True, blank=True)
    stop_loss = models.FloatField(null=True, blank=True)
    funding_fees = models.FloatField(default=0.0)
    pnl = models.FloatField(null=True, blank=True)
    pnl_pct = models.FloatField(null=True, blank=True)
    status = models.CharField(max_length=16, default="OPEN", db_index=True)
    close_reason = models.CharField(max_length=32, null=True, blank=True)
    decision_score = models.IntegerField(default=0)
    decision_reason = models.TextField(null=True, blank=True)
    opened_at = models.DateTimeField(default=datetime.utcnow, db_index=True)
    closed_at = models.DateTimeField(null=True, blank=True)


class FailedLoginAttempt(models.Model):
    """Track failed login attempts for account lockout."""

    class Meta:
        db_table = "failed_login_attempts"

    user_id = models.IntegerField(null=True, blank=True, db_index=True)
    ip_address = models.CharField(max_length=45, null=True, blank=True)
    timestamp = models.DateTimeField(default=datetime.utcnow, db_index=True)