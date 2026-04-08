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
    "FET",
    "RENDER",
    "WLD",
    "KAS",
    "MNT",
    "PYTH",
    "RUNE",
]


DEFAULT_ALLOCATION_QUOTE = {
    "BTC": 700.0,
    "ETH": 600.0,
    "BNB": 425.0,
    "SOL": 425.0,
    "XRP": 325.0,
    "ADA": 275.0,
    "DOGE": 225.0,
    "TRX": 200.0,
    "AVAX": 250.0,
    "DOT": 225.0,
    "LINK": 225.0,
    "TON": 225.0,
    "SUI": 200.0,
    "LTC": 200.0,
    "BCH": 200.0,
    "ATOM": 175.0,
    "UNI": 175.0,
    "NEAR": 175.0,
    "APT": 175.0,
    "ETC": 175.0,
    "XLM": 150.0,
    "HBAR": 150.0,
    "FIL": 150.0,
    "ARB": 150.0,
    "AAVE": 150.0,
    "OP": 125.0,
    "INJ": 125.0,
    "ICP": 125.0,
    "VET": 125.0,
    "ALGO": 125.0,
    "SHIB": 100.0,
    "PEPE": 100.0,
    "SEI": 125.0,
    "FET": 125.0,
    "RENDER": 125.0,
    "WLD": 100.0,
    "KAS": 100.0,
    "MNT": 100.0,
    "PYTH": 100.0,
    "RUNE": 125.0,
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
    "FET": "artificial-superintelligence-alliance",
    "RENDER": "render-token",
    "WLD": "worldcoin-wld",
    "KAS": "kaspa",
    "MNT": "mantle",
    "PYTH": "pyth-network",
    "RUNE": "thorchain",
}


_EXCHANGE_QUOTE = os.getenv("AGENT_KRYPTO_EXCHANGE_QUOTE", "USDT").upper()
BINANCE_SYMBOLS = {symbol: f"{symbol}{_EXCHANGE_QUOTE}" for symbol in DEFAULT_SYMBOLS}


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
    "DeFi": ["LINK", "UNI", "AAVE", "RUNE", "INJ"],
    "Infra": ["ARB", "OP", "FIL", "HBAR", "PYTH"],
    "AI": ["FET", "RENDER", "WLD"],
    "Payments": ["TRX", "XLM", "LTC", "BCH", "VET"],
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
    "trading": {
        "label": "Trading",
        "description": "Agresywny handel: niski prog wejscia, duza alokacja, szybkie obroty. Maksymalny zysk = maksymalne ryzyko.",
        "buy_score_threshold": 3,
        "exploration_rate": 0.35,
        "profit_target": 0.02,
        "stop_loss": 0.07,
        "max_hold_hours": 12,
        "max_trades_per_day": 9999,
        "max_open_positions": 9999,
        "allocation_scale": 1.5,
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
    starting_balance_quote: float = float(os.getenv("AGENT_KRYPTO_START_BALANCE", os.getenv("AGENT_KRYPTO_START_BALANCE_PLN", "10000")))
    starting_balance_display_pln: float = float(os.getenv("AGENT_KRYPTO_START_BALANCE_PLN", "10000"))
    fee_rate: float = float(os.getenv("AGENT_KRYPTO_FEE_RATE", "0.001"))
    slippage: float = float(os.getenv("AGENT_KRYPTO_SLIPPAGE", "0.0005"))
    history_days: int = int(os.getenv("AGENT_KRYPTO_HISTORY_DAYS", "90"))
    history_bars: int = int(os.getenv("AGENT_KRYPTO_HISTORY_BARS", "500"))
    market_interval: str = os.getenv("AGENT_KRYPTO_MARKET_INTERVAL", "1h")
    cycle_interval_seconds: int = int(os.getenv("AGENT_KRYPTO_CYCLE_INTERVAL_SECONDS", "300"))
    dashboard_refresh_seconds: int = int(os.getenv("AGENT_KRYPTO_DASHBOARD_REFRESH_SECONDS", "30"))
    live_quote_cache_seconds: int = int(os.getenv("AGENT_KRYPTO_LIVE_QUOTE_CACHE_SECONDS", "30"))
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
    exchange_quote_currency: str = os.getenv("AGENT_KRYPTO_EXCHANGE_QUOTE", "USDC").upper()
    preferred_trade_quotes: list[str] = field(default_factory=lambda: ["PLN", "USDC", "EUR", "BTC", "ETH", "BNB"])
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