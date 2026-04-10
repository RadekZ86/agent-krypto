from __future__ import annotations

import threading
from datetime import datetime, timedelta
from typing import Any, Callable

import pandas as pd
from sqlalchemy.orm import Session

from app.config import settings
from app.services.analysis_frame import build_indicator_frame
from app.services.market_data import load_symbol_market_rows
from app.services.probability_engine import ProbabilityEngine

_EMPTY_RANKINGS: dict[str, Any] = {
    "updated_at": None,
    "rankings": [],
    "best_strategy": None,
    "computing": True,
}


class BacktestService:
    def __init__(self) -> None:
        self.probability_engine = ProbabilityEngine()
        self._cache: dict[str, Any] | None = None
        self._cache_created_at: datetime | None = None
        self._computing = False

    def get_rankings(self, session: Session, symbols: list[str] | None = None, force_refresh: bool = False) -> dict[str, Any]:
        if not force_refresh and self._cache is not None and self._cache_created_at is not None:
            if datetime.utcnow() - self._cache_created_at < timedelta(minutes=5):
                return self._cache

        # If cache is stale/empty, return empty immediately and compute in background
        if not self._computing:
            self._computing = True
            threading.Thread(
                target=self._compute_in_background,
                args=(symbols,),
                daemon=True,
                name="backtest-compute",
            ).start()
        return self._cache if self._cache is not None else _EMPTY_RANKINGS

    def _compute_in_background(self, symbols: list[str] | None = None) -> None:
        """Run the heavy computation in a background thread."""
        try:
            from app.database import SessionLocal
            with SessionLocal() as session:
                self._compute(session, symbols)
        except Exception:
            pass
        finally:
            self._computing = False

    def _compute(self, session: Session, symbols: list[str] | None = None) -> dict[str, Any]:
        per_strategy: list[dict[str, Any]] = []
        strategies: list[tuple[str, str, Callable[[pd.Series, dict[str, Any]], bool], Callable[[pd.Series, dict[str, Any], float], bool]]] = [
            (
                "mean_reversion",
                "RSI Reversion",
                lambda row, probs: float(row["rsi"]) < 30 and float(row["macd_hist"]) > -0.0001 and probs["bottom_probability"] >= 55,
                lambda row, probs, profit_pct: float(row["rsi"]) > 56 or profit_pct >= 0.045 or profit_pct <= -0.03 or probs["top_probability"] >= 64,
            ),
            (
                "trend_follow",
                "EMA Trend Follow",
                lambda row, probs: row["trend"] == "UP" and float(row["macd"]) >= float(row["macd_signal"]) and probs["up_probability"] >= 58,
                lambda row, probs, profit_pct: row["trend"] == "DOWN" or float(row["macd"]) < float(row["macd_signal"]) or profit_pct <= -0.028 or probs["top_probability"] >= 70,
            ),
            (
                "breakout_volume",
                "Volume Breakout",
                lambda row, probs: float(row["close"]) > float(row["ema20"]) and float(row["volume_change"]) > 0.18 and probs["up_probability"] >= 60,
                lambda row, probs, profit_pct: float(row["close"]) < float(row["ema20"]) or profit_pct >= 0.06 or profit_pct <= -0.025,
            ),
        ]

        for strategy_code, label, entry_rule, exit_rule in strategies:
            aggregate_capital = 10000.0
            total_profit = 0.0
            total_trades = 0
            total_wins = 0
            max_drawdown = 0.0
            symbol_breakdown: list[dict[str, Any]] = []
            per_symbol_capital = aggregate_capital / max(1, len(symbols_to_process))

            for symbol in symbols_to_process:
                metrics = self._backtest_symbol(session, symbol, per_symbol_capital, entry_rule, exit_rule)
                if metrics is None:
                    continue
                total_profit += metrics["profit"]
                total_trades += metrics["trades"]
                total_wins += metrics["wins"]
                max_drawdown = max(max_drawdown, metrics["max_drawdown"])
                symbol_breakdown.append(
                    {
                        "symbol": symbol,
                        "roi": round(metrics["roi"], 2),
                        "trades": metrics["trades"],
                        "win_rate": round(metrics["win_rate"], 1),
                    }
                )

            win_rate = (total_wins / total_trades * 100) if total_trades else 0.0
            roi = (total_profit / aggregate_capital * 100) if aggregate_capital else 0.0
            per_strategy.append(
                {
                    "code": strategy_code,
                    "label": label,
                    "roi": round(roi, 2),
                    "profit": round(total_profit, 2),
                    "trades": total_trades,
                    "win_rate": round(win_rate, 1),
                    "max_drawdown": round(max_drawdown, 2),
                    "symbols_tested": len(symbol_breakdown),
                    "top_symbols": sorted(symbol_breakdown, key=lambda row: row["roi"], reverse=True)[:5],
                }
            )

        rankings = sorted(per_strategy, key=lambda row: (row["roi"], row["win_rate"], -row["max_drawdown"]), reverse=True)
        payload = {
            "updated_at": datetime.utcnow().isoformat(),
            "rankings": rankings,
            "best_strategy": rankings[0] if rankings else None,
        }
        self._cache = payload
        self._cache_created_at = datetime.utcnow()
        return payload

    def _backtest_symbol(
        self,
        session: Session,
        symbol: str,
        initial_capital: float,
        entry_rule: Callable[[pd.Series, dict[str, Any]], bool],
        exit_rule: Callable[[pd.Series, dict[str, Any], float], bool],
    ) -> dict[str, Any] | None:
        rows = load_symbol_market_rows(session, symbol, limit=min(settings.history_bars, 600))
        if len(rows) < 80:
            return None

        df = build_indicator_frame(rows)
        capital = initial_capital
        peak_equity = initial_capital
        max_drawdown = 0.0
        open_position: dict[str, float] | None = None
        trades = 0
        wins = 0

        for index in range(50, len(df)):
            row = df.iloc[index]
            previous = df.iloc[index - 1] if index > 0 else row
            probs = self.probability_engine.estimate(row, previous)
            price = float(row["close"])

            if open_position is None:
                if entry_rule(row, probs):
                    buy_value = min(initial_capital * 0.18, capital * 0.9)
                    if buy_value < 25:
                        continue
                    executed_price = price * (1 + settings.slippage)
                    quantity = buy_value / executed_price
                    fee = buy_value * settings.fee_rate
                    capital -= buy_value + fee
                    open_position = {
                        "price": executed_price,
                        "quantity": quantity,
                        "cost": buy_value + fee,
                    }
                continue

            current_value = open_position["quantity"] * price * (1 - settings.slippage)
            sell_fee = current_value * settings.fee_rate
            net_value = current_value - sell_fee
            profit_pct = (net_value - open_position["cost"]) / open_position["cost"] if open_position["cost"] else 0.0

            if exit_rule(row, probs, profit_pct):
                capital += net_value
                trades += 1
                if net_value > open_position["cost"]:
                    wins += 1
                open_position = None

            mark_to_market = capital
            if open_position is not None:
                mark_to_market += net_value
            peak_equity = max(peak_equity, mark_to_market)
            if peak_equity:
                max_drawdown = max(max_drawdown, (peak_equity - mark_to_market) / peak_equity * 100)

        if open_position is not None:
            final_price = float(df.iloc[-1]["close"])
            current_value = open_position["quantity"] * final_price * (1 - settings.slippage)
            sell_fee = current_value * settings.fee_rate
            capital += current_value - sell_fee
            trades += 1
            if current_value - sell_fee > open_position["cost"]:
                wins += 1

        profit = capital - initial_capital
        roi = (profit / initial_capital * 100) if initial_capital else 0.0
        win_rate = (wins / trades * 100) if trades else 0.0
        return {
            "profit": profit,
            "roi": roi,
            "trades": trades,
            "wins": wins,
            "win_rate": win_rate,
            "max_drawdown": max_drawdown,
        }