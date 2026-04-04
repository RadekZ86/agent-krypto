from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


DEFAULT_SYMBOLS = [
    "BTC",
    "ETH",
    "BNB",
    "SOL",
    "XRP",
    "ADA",
    "DOGE",
    "TRX",
    "AVAX",
    "DOT",
    "LINK",
    "TON",
    "SUI",
    "LTC",
    "BCH",
    "ATOM",
    "UNI",
    "NEAR",
    "APT",
    "ETC",
    "XLM",
    "HBAR",
    "FIL",
    "ARB",
    "AAVE",
    "OP",
    "INJ",
    "ICP",
    "VET",
    "ALGO",
    "SHIB",
    "PEPE",
    "SEI",
    "MKR",
    "EOS",
    "CRO",
    "KAS",
    "MNT",
    "PYTH",
    "RUNE",
]


DEFAULT_ALLOCATION_QUOTE = {
    "BTC": 140.0,
    "ETH": 120.0,
    "BNB": 85.0,
    "SOL": 85.0,
    "XRP": 65.0,
    "ADA": 55.0,
    "DOGE": 45.0,
    "TRX": 40.0,
    "AVAX": 50.0,
    "DOT": 45.0,
    "LINK": 45.0,
    "TON": 45.0,
    "SUI": 40.0,
    "LTC": 40.0,
    "BCH": 40.0,
    "ATOM": 35.0,
    "UNI": 35.0,
    "NEAR": 35.0,
    "APT": 35.0,
    "ETC": 35.0,
    "XLM": 30.0,
    "HBAR": 30.0,
    "FIL": 30.0,
    "ARB": 30.0,
    "AAVE": 30.0,
    "OP": 25.0,
    "INJ": 25.0,
    "ICP": 25.0,
    "VET": 25.0,
    "ALGO": 25.0,
    "SHIB": 20.0,
    "PEPE": 20.0,
    "SEI": 25.0,
    "MKR": 25.0,
    "EOS": 20.0,
    "CRO": 20.0,
    "KAS": 20.0,
    "MNT": 20.0,
    "PYTH": 20.0,
    "RUNE": 25.0,
}


COINGECKO_IDS = {
    "BTC": "bitcoin",
    "ETH": "ethereum",
    "BNB": "binancecoin",
    "SOL": "solana",
    "XRP": "ripple",
    "ADA": "cardano",
    "DOGE": "dogecoin",
    "TRX": "tron",
    "AVAX": "avalanche-2",
    "DOT": "polkadot",
    "LINK": "chainlink",
    "TON": "the-open-network",
    "SUI": "sui",
    "LTC": "litecoin",
    "BCH": "bitcoin-cash",
    "ATOM": "cosmos",
    "UNI": "uniswap",
    "NEAR": "near",
    "APT": "aptos",
    "ETC": "ethereum-classic",
    "XLM": "stellar",
    "HBAR": "hedera-hashgraph",
    "FIL": "filecoin",
    "ARB": "arbitrum",
    "AAVE": "aave",
    "OP": "optimism",
    "INJ": "injective-protocol",
    "ICP": "internet-computer",
    "VET": "vechain",
    "ALGO": "algorand",
    "SHIB": "shiba-inu",
    "PEPE": "pepe",
    "SEI": "sei-network",
    "MKR": "maker",
    "EOS": "eos",
    "CRO": "cronos",
    "KAS": "kaspa",
    "MNT": "mantle",
    "PYTH": "pyth-network",
    "RUNE": "thorchain",
}


BINANCE_SYMBOLS = {symbol: f"{symbol}USDT" for symbol in DEFAULT_SYMBOLS}


COINBASE_PRODUCTS = {
    "BTC": "BTC-USD",
    "ETH": "ETH-USD",
    "SOL": "SOL-USD",
    "XRP": "XRP-USD",
    "ADA": "ADA-USD",
    "DOGE": "DOGE-USD",
    "AVAX": "AVAX-USD",
    "LINK": "LINK-USD",
    "LTC": "LTC-USD",
    "BCH": "BCH-USD",
    "ATOM": "ATOM-USD",
    "UNI": "UNI-USD",
    "AAVE": "AAVE-USD",
}


SYMBOL_GROUPS = {
    "Majors": ["BTC", "ETH", "BNB", "SOL", "XRP", "ADA", "DOGE", "TON"],
    "Layer1": ["AVAX", "DOT", "ATOM", "NEAR", "APT", "SUI", "ALGO", "ICP", "SEI", "KAS", "MNT", "ETC"],
    "DeFi": ["LINK", "UNI", "AAVE", "MKR", "RUNE", "INJ"],
    "Infra": ["ARB", "OP", "FIL", "HBAR", "PYTH"],
    "Payments": ["TRX", "XLM", "LTC", "BCH", "VET", "EOS", "CRO"],
    "Memes": ["DOGE", "SHIB", "PEPE"],
}


AGENT_MODE_PROFILES = {
    "cautious": {
        "label": "Ostrozny",
        "description": "Malo eksperymentow, twardsze wejscia i mniejsza ekspozycja.",
        "buy_score_threshold": 6,
        "exploration_rate": 0.05,
        "profit_target": 0.04,
        "stop_loss": 0.025,
        "max_hold_hours": 30,
        "max_trades_per_day": 8,
        "max_open_positions": 6,
        "allocation_scale": 0.75,
    },
    "normal": {
        "label": "Normalny",
        "description": "Wywazony kompromis miedzy jakoscia wejsc a liczba probek do nauki.",
        "buy_score_threshold": 5,
        "exploration_rate": 0.12,
        "profit_target": 0.03,
        "stop_loss": 0.035,
        "max_hold_hours": 24,
        "max_trades_per_day": 12,
        "max_open_positions": 10,
        "allocation_scale": 1.0,
    },
    "risky": {
        "label": "Ryzykowny",
        "description": "Wiecej eksperymentow i szybsze zbieranie bledow na wirtualnym kapitalie. Brak limitow transakcji.",
        "buy_score_threshold": 4,
        "exploration_rate": 0.22,
        "profit_target": 0.025,
        "stop_loss": 0.05,
        "max_hold_hours": 18,
        "max_trades_per_day": 9999,
        "max_open_positions": 999,
        "allocation_scale": 1.2,
    },
}


HISTORY_START_FLOORS = {
    "BTC": "2018-01-01",
    "ETH": "2018-01-01",
}


@dataclass(slots=True)
class Settings:
    app_name: str = "Agent Krypto"
    database_url: str = os.getenv("DATABASE_URL", f"sqlite:///{(BASE_DIR / 'agent_krypto.db').as_posix()}")
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")
    openai_model: str = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
    openai_input_cost_per_million: float = float(os.getenv("OPENAI_INPUT_COST_PER_MILLION", "0.4"))
    openai_output_cost_per_million: float = float(os.getenv("OPENAI_OUTPUT_COST_PER_MILLION", "1.6"))
    starting_balance_quote: float = float(os.getenv("AGENT_KRYPTO_START_BALANCE", os.getenv("AGENT_KRYPTO_START_BALANCE_PLN", "1000")))
    starting_balance_display_pln: float = float(os.getenv("AGENT_KRYPTO_START_BALANCE_PLN", "1000"))
    fee_rate: float = float(os.getenv("AGENT_KRYPTO_FEE_RATE", "0.001"))
    slippage: float = float(os.getenv("AGENT_KRYPTO_SLIPPAGE", "0.0005"))
    history_days: int = int(os.getenv("AGENT_KRYPTO_HISTORY_DAYS", "90"))
    history_bars: int = int(os.getenv("AGENT_KRYPTO_HISTORY_BARS", "500"))
    market_interval: str = os.getenv("AGENT_KRYPTO_MARKET_INTERVAL", "1h")
    cycle_interval_seconds: int = int(os.getenv("AGENT_KRYPTO_CYCLE_INTERVAL_SECONDS", "300"))
    dashboard_refresh_seconds: int = int(os.getenv("AGENT_KRYPTO_DASHBOARD_REFRESH_SECONDS", "10"))
    live_quote_cache_seconds: int = int(os.getenv("AGENT_KRYPTO_LIVE_QUOTE_CACHE_SECONDS", "5"))
    scheduler_enabled: bool = _env_bool("AGENT_KRYPTO_SCHEDULER_ENABLED", True)
    trading_mode: str = os.getenv("AGENT_KRYPTO_TRADING_MODE", "PAPER").upper()
    default_agent_mode: str = os.getenv("AGENT_KRYPTO_AGENT_MODE", "normal").lower()
    learning_mode: bool = _env_bool("AGENT_KRYPTO_LEARNING_MODE", True)
    exploration_rate: float = float(os.getenv("AGENT_KRYPTO_EXPLORATION_RATE", "0.22"))
    learning_buy_score_threshold: int = int(os.getenv("AGENT_KRYPTO_LEARNING_BUY_SCORE_THRESHOLD", "4"))
    learning_profit_target: float = float(os.getenv("AGENT_KRYPTO_LEARNING_PROFIT_TARGET", "0.025"))
    learning_stop_loss: float = float(os.getenv("AGENT_KRYPTO_LEARNING_STOP_LOSS", "0.05"))
    learning_max_hold_hours: int = int(os.getenv("AGENT_KRYPTO_LEARNING_MAX_HOLD_HOURS", "18"))
    max_trades_per_day: int = int(os.getenv("AGENT_KRYPTO_MAX_TRADES_PER_DAY", "18"))
    max_open_positions: int = int(os.getenv("AGENT_KRYPTO_MAX_OPEN_POSITIONS", "14"))
    quote_currency: str = os.getenv("AGENT_KRYPTO_QUOTE_CURRENCY", "USD").upper()
    display_currency: str = os.getenv("AGENT_KRYPTO_DISPLAY_CURRENCY", "PLN").upper()
    exchange_quote_currency: str = os.getenv("AGENT_KRYPTO_EXCHANGE_QUOTE", "USDT").upper()
    preferred_trade_quotes: list[str] = field(default_factory=lambda: ["USDT", "BTC", "BNB"])
    binance_api_key: str = os.getenv("BINANCE_API_KEY", "")
    binance_api_secret: str = os.getenv("BINANCE_API_SECRET", "")
    tracked_symbols: list[str] = field(default_factory=lambda: DEFAULT_SYMBOLS.copy())
    allocation_quote: dict[str, float] = field(default_factory=lambda: DEFAULT_ALLOCATION_QUOTE.copy())
    coingecko_ids: dict[str, str] = field(default_factory=lambda: COINGECKO_IDS.copy())
    binance_symbols: dict[str, str] = field(default_factory=lambda: BINANCE_SYMBOLS.copy())
    coinbase_products: dict[str, str] = field(default_factory=lambda: COINBASE_PRODUCTS.copy())
    symbol_groups: dict[str, list[str]] = field(default_factory=lambda: {group: members.copy() for group, members in SYMBOL_GROUPS.items()})
    agent_mode_profiles: dict[str, dict[str, object]] = field(default_factory=lambda: {mode: profile.copy() for mode, profile in AGENT_MODE_PROFILES.items()})
    history_start_floors: dict[str, str] = field(default_factory=lambda: HISTORY_START_FLOORS.copy())

    @property
    def bars_per_day(self) -> int:
        mapping = {
            "15m": 96,
            "30m": 48,
            "1h": 24,
            "2h": 12,
            "4h": 6,
            "6h": 4,
            "8h": 3,
            "12h": 2,
            "1d": 1,
        }
        return mapping.get(self.market_interval, 24)

    @property
    def market_data_sources(self) -> list[str]:
        return ["binance", "coinbase", "coingecko", "demo"]


settings = Settings()