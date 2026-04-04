from __future__ import annotations

from datetime import datetime, timedelta
import hashlib

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Decision, SimulatedTrade
from app.services.runtime_state import RuntimeStateService


class DecisionEngine:
    def __init__(self) -> None:
        self.runtime_state = RuntimeStateService()

    def evaluate(self, session: Session, symbol: str, feature_row: dict[str, float | str]) -> Decision:
        profile = self.runtime_state.get_active_profile(session)
        score = 0
        reasons: list[str] = []
        decision_value = "HOLD"
        confidence = 0.45
        learning_mode = settings.trading_mode == "PAPER" and settings.learning_mode
        up_probability = float(feature_row.get("up_probability", 50.0))
        bottom_probability = float(feature_row.get("bottom_probability", 50.0))
        top_probability = float(feature_row.get("top_probability", 50.0))

        if float(feature_row["rsi"]) < 30:
            score += 2
            reasons.append("RSI ponizej 30")
        if float(feature_row["macd"]) > float(feature_row["macd_signal"]):
            score += 2
            reasons.append("MACD powyzej sygnalu")
        if feature_row["trend"] == "UP":
            score += 1
            reasons.append("Trend wzrostowy EMA20 > EMA50")
        if float(feature_row["volume_change"]) > 0:
            score += 1
            reasons.append("Rosnacy wolumen")
        if up_probability >= 58:
            score += 2
            reasons.append(f"Szacowane prawdopodobienstwo ruchu w gore {up_probability:.1f}%")
        if bottom_probability >= 60:
            score += 2
            reasons.append(f"Szansa lokalnego dolka {bottom_probability:.1f}%")

        knowledge_score, knowledge_reasons = self._apply_knowledge_playbooks(feature_row)
        score += knowledge_score
        reasons.extend(knowledge_reasons)

        open_trade = session.execute(
            select(SimulatedTrade)
            .where(SimulatedTrade.symbol == symbol, SimulatedTrade.status == "OPEN")
            .order_by(SimulatedTrade.opened_at.desc())
        ).scalar_one_or_none()

        if open_trade is not None:
            sell_reasons: list[str] = []
            current_price = float(feature_row["close"])
            current_value = open_trade.quantity * current_price * (1 - settings.slippage)
            profit_pct = (current_value - (open_trade.buy_value + open_trade.buy_fee)) / (open_trade.buy_value + open_trade.buy_fee)
            hold_hours = (datetime.utcnow() - open_trade.opened_at).total_seconds() / 3600

            if float(feature_row["rsi"]) > 65:
                sell_reasons.append("RSI powyzej 65")
            profit_target = float(profile["profit_target"]) if learning_mode else 0.04
            stop_loss = float(profile["stop_loss"]) if learning_mode else 0.03
            if profit_pct >= profit_target:
                sell_reasons.append(f"Take profit {(profit_target * 100):.1f}%")
            if profit_pct <= -stop_loss:
                sell_reasons.append(f"Stop loss -{(stop_loss * 100):.1f}%")
            if top_probability >= 65:
                sell_reasons.append(f"Szansa lokalnego szczytu {top_probability:.1f}%")
            if up_probability <= 40:
                sell_reasons.append(f"Rynek traci przewage wzrostowa ({up_probability:.1f}% na wzrost)")
            if learning_mode and hold_hours >= float(profile["max_hold_hours"]):
                sell_reasons.append(f"Rotacja edukacyjna po {hold_hours:.1f}h")

            if sell_reasons:
                decision_value = "SELL"
                confidence = min(0.95, 0.55 + len(sell_reasons) * 0.08 + max(top_probability - 50, 0) / 100)
                reasons = sell_reasons
        else:
            buy_threshold = int(profile["buy_score_threshold"]) if learning_mode else 5
            if score >= buy_threshold:
                decision_value = "BUY"
                confidence = min(0.95, 0.44 + score * 0.05 + max(up_probability - 50, 0) / 100)
            elif learning_mode:
                experiment = self._learning_experiment(symbol, feature_row, score, profile)
                if experiment is not None:
                    decision_value = "BUY"
                    confidence = experiment["confidence"]
                    reasons = [experiment["reason"]]
            else:
                reasons = reasons or ["Brak wystarczajacej przewagi"]

        if decision_value == "BUY" and self._daily_trade_count(session) >= int(profile["max_trades_per_day"]):
            decision_value = "HOLD"
            confidence = 0.52
            reasons = [f"Osiagnieto limit {int(profile['max_trades_per_day'])} transakcji dziennie"]

        decision = Decision(
            symbol=symbol,
            timestamp=datetime.utcnow(),
            decision=decision_value,
            confidence=round(confidence, 3),
            reason="; ".join(reasons),
            score=score,
        )
        session.add(decision)
        session.flush()
        return decision

    def _daily_trade_count(self, session: Session) -> int:
        start_of_day = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        end_of_day = start_of_day + timedelta(days=1)
        result = session.execute(
            select(func.count(SimulatedTrade.id)).where(
                SimulatedTrade.opened_at >= start_of_day,
                SimulatedTrade.opened_at < end_of_day,
            )
        ).scalar_one()
        return int(result)

    def _learning_experiment(self, symbol: str, feature_row: dict[str, float | str], score: int, profile: dict[str, object]) -> dict[str, float | str] | None:
        up_probability = float(feature_row.get("up_probability", 50.0))
        bottom_probability = float(feature_row.get("bottom_probability", 50.0))
        rsi = float(feature_row["rsi"])
        macd = float(feature_row["macd"])
        macd_signal = float(feature_row["macd_signal"])
        volume_change = float(feature_row["volume_change"])
        trend = str(feature_row["trend"])

        signal_points = 0
        if rsi <= 42:
            signal_points += 1
        if macd >= macd_signal:
            signal_points += 1
        if bottom_probability >= 48:
            signal_points += 1
        if up_probability >= 51:
            signal_points += 1
        if volume_change >= -0.08:
            signal_points += 1

        if trend == "DOWN" and signal_points < 4:
            return None
        if signal_points < 3 and score < int(profile["buy_score_threshold"]) - 1:
            return None

        cycle_bucket = datetime.utcnow().strftime("%Y%m%d%H")
        sample = hashlib.sha256(f"{symbol}:{cycle_bucket}:{score}".encode("utf-8")).hexdigest()
        gate = int(sample[:8], 16) / 0xFFFFFFFF
        if gate > float(profile["exploration_rate"]):
            return None

        confidence = min(0.72, 0.43 + signal_points * 0.04 + max(up_probability - 50, 0) / 150)
        return {
            "confidence": round(confidence, 3),
            "reason": "Eksperymentalne wejscie paper trading do nauki na bledach i slabszych setupach",
        }

    def _apply_knowledge_playbooks(self, feature_row: dict[str, float | str]) -> tuple[int, list[str]]:
        score = 0
        reasons: list[str] = []
        rsi = float(feature_row["rsi"])
        macd = float(feature_row["macd"])
        macd_signal = float(feature_row["macd_signal"])
        volume_change = float(feature_row["volume_change"])
        trend = str(feature_row["trend"])
        up_probability = float(feature_row.get("up_probability", 50.0))
        bottom_probability = float(feature_row.get("bottom_probability", 50.0))

        if trend == "UP" and macd >= macd_signal and volume_change >= -0.03:
            score += 1
            reasons.append("Playbook trend continuation: trend i momentum nadal wspieraja pozycje")
        if rsi <= 38 and bottom_probability >= 55:
            score += 1
            reasons.append("Playbook mean reversion: rynek zbliza sie do strefy odbicia")
        if up_probability >= 60 and volume_change > 0.05:
            score += 1
            reasons.append("Playbook breakout validation: ruch ma potwierdzenie w prawdopodobienstwie i wolumenie")
        if trend == "DOWN" and rsi > 45 and up_probability < 55:
            score -= 1
            reasons.append("Playbook no-trade zone: unikaj lapania slabego odbicia w trendzie spadkowym")

        return score, reasons