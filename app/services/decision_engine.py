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
        reasons: list[str] = []
        decision_value = "HOLD"
        confidence = 0.45
        # Learning mode: always use profile thresholds so agent adapts from experience
        learning_mode = settings.learning_mode
        # Exploration trades: only in PAPER mode (too risky for real money)
        exploration_mode = settings.trading_mode == "PAPER" and settings.learning_mode

        # ── Extract all indicators ──
        close = float(feature_row["close"])
        rsi = float(feature_row["rsi"])
        macd = float(feature_row["macd"])
        macd_signal = float(feature_row["macd_signal"])
        macd_hist = float(feature_row["macd_hist"])
        ema20 = float(feature_row["ema20"])
        ema50 = float(feature_row["ema50"])
        trend = str(feature_row["trend"])
        volume_change = float(feature_row["volume_change"])
        up_probability = float(feature_row.get("up_probability", 50.0))
        bottom_probability = float(feature_row.get("bottom_probability", 50.0))
        top_probability = float(feature_row.get("top_probability", 50.0))
        bb_upper = float(feature_row.get("bb_upper", close))
        bb_lower = float(feature_row.get("bb_lower", close))
        sma20 = float(feature_row.get("sma20", close))
        vwap = float(feature_row.get("vwap", close))
        bb_width = float(feature_row.get("bb_width", 0.0))
        prev_close = float(feature_row.get("prev_close", close))
        prev_rsi = float(feature_row.get("prev_rsi", rsi))
        prev_macd_hist = float(feature_row.get("prev_macd_hist", macd_hist))
        prev_macd = float(feature_row.get("prev_macd", macd))
        prev_macd_signal = float(feature_row.get("prev_macd_signal", macd_signal))

        # ── BUY SIGNAL SCORING (multi-indicator confluence) ──
        buy_score = 0
        buy_signals: list[str] = []

        # 1. RSI Oversold (strongest buy signal when <30, moderate <40)
        if rsi < 30:
            buy_score += 3
            buy_signals.append(f"RSI mocno wyprzedany ({rsi:.0f})")
        elif rsi < 40:
            buy_score += 1
            buy_signals.append(f"RSI w strefie wyprzedania ({rsi:.0f})")

        # 2. MACD Bullish Crossover (MACD crosses above signal line)
        if macd > macd_signal and prev_macd <= prev_macd_signal:
            buy_score += 3
            buy_signals.append("MACD przeciecie bycze (swiezy sygnal)")
        elif macd > macd_signal:
            buy_score += 1
            buy_signals.append("MACD powyzej linii sygnalu")

        # 3. MACD Histogram momentum shift (from negative to positive or rising)
        if macd_hist > 0 and prev_macd_hist <= 0:
            buy_score += 2
            buy_signals.append("Histogram MACD przeszedl na plus")
        elif macd_hist > prev_macd_hist and macd_hist > 0:
            buy_score += 1
            buy_signals.append("Histogram MACD rosnie")

        # 4. Bollinger Band Bounce (price near or below lower band)
        if bb_lower > 0:
            bb_position = (close - bb_lower) / (bb_upper - bb_lower) if bb_upper != bb_lower else 0.5
            if bb_position <= 0.05:
                buy_score += 3
                buy_signals.append("Cena na dolnej wstedze Bollingera (silne wyprzedanie)")
            elif bb_position <= 0.20:
                buy_score += 2
                buy_signals.append("Cena blisko dolnej wstegi Bollingera")

        # 5. Bollinger Squeeze (low volatility = breakout incoming)
        if bb_width < 2.0 and bb_width > 0:
            buy_score += 1
            buy_signals.append(f"Bollinger Squeeze: niska zmiennosc ({bb_width:.1f}%) - mozliwy breakout")

        # 6. Price above VWAP (institutional support)
        if close > vwap and vwap > 0:
            buy_score += 1
            buy_signals.append("Cena powyzej VWAP (wsparcie instytucjonalne)")

        # 7. EMA Trend alignment (price > EMA20 > EMA50 = strong uptrend)
        if trend == "UP":
            buy_score += 2
            buy_signals.append("Trend wzrostowy EMA20 > EMA50")
        elif close > ema20 and ema20 > ema50 * 0.998:
            buy_score += 1
            buy_signals.append("EMA zbiegaja sie w gore")

        # 8. Golden Cross detection (EMA20 crosses above EMA50)
        if trend == "UP" and ema20 > ema50 and (ema20 - ema50) / ema50 < 0.005:
            buy_score += 2
            buy_signals.append("Golden Cross: EMA20 wlasnie przecielo EMA50 w gore")

        # 9. Volume confirmation (require rising volume for strong signals)
        if volume_change > 0.15:
            buy_score += 2
            buy_signals.append(f"Potwierdzenie wolumenem (+{volume_change*100:.0f}%)")
        elif volume_change > 0:
            buy_score += 1
            buy_signals.append("Rosnacy wolumen")

        # 10. Probability engine support
        if up_probability >= 60:
            buy_score += 2
            buy_signals.append(f"Wysoka szansa wzrostu ({up_probability:.0f}%)")
        elif up_probability >= 55:
            buy_score += 1
            buy_signals.append(f"Umiarkowana szansa wzrostu ({up_probability:.0f}%)")

        if bottom_probability >= 60:
            buy_score += 2
            buy_signals.append(f"Sygnał dna ({bottom_probability:.0f}%)")

        # 11. RSI Bullish Divergence (price makes lower low, RSI makes higher low)
        prev2_close = float(feature_row.get("prev2_close", prev_close))
        prev2_rsi = float(feature_row.get("prev2_rsi", prev_rsi))
        if close < prev2_close and rsi > prev2_rsi and rsi < 45:
            buy_score += 3
            buy_signals.append("Dywergencja bycza RSI (cena spada ale momentum rosnie)")

        # 12. Mean reversion from extreme (price far below SMA20)
        if sma20 > 0:
            price_vs_sma = (close - sma20) / sma20 * 100
            if price_vs_sma < -3.0:
                buy_score += 2
                buy_signals.append(f"Odchylenie od SMA20: {price_vs_sma:.1f}% (mean reversion)")

        # ── 13. WHALE / ANOMALY SIGNALS ──
        whale_score = float(feature_row.get("whale_score", 0))
        whale_signal = str(feature_row.get("whale_signal", "NONE"))
        vol_zscore = float(feature_row.get("vol_zscore", 0))
        vol_ratio_val = float(feature_row.get("vol_ratio", 1))
        obv_divergence = str(feature_row.get("obv_divergence", "NONE"))

        if whale_signal == "WHALE_BUY":
            buy_score += 3
            buy_signals.append(f"🐋 Wieloryb kupuje! Score={whale_score:.1f}, wolumen {vol_ratio_val:.1f}x sredniej")
        elif whale_signal == "WHALE_ACCUMULATE":
            buy_score += 2
            buy_signals.append(f"🐋 Akumulacja wieloryba: duzy wolumen bez ruchu ceny (score={whale_score:.1f})")
        elif whale_signal == "SPIKE_UP":
            buy_score += 2
            buy_signals.append(f"Nagly wzrost +{float(feature_row.get('price_change_pct', 0)):.1f}% przy wolumenie {vol_zscore:.1f}σ")
        elif whale_signal == "HIGH_VOLUME":
            buy_score += 1
            buy_signals.append(f"Wysoki wolumen: {vol_ratio_val:.1f}x sredniej")

        if whale_signal == "WHALE_SELL":
            buy_score -= 3
            buy_signals.append(f"🐋 UWAGA: Wieloryb sprzedaje! Score={whale_score:.1f} (kara -3)")
        elif whale_signal == "SPIKE_DOWN":
            buy_score -= 2
            buy_signals.append(f"UWAGA: Nagly spadek {float(feature_row.get('price_change_pct', 0)):.1f}% (kara -2)")

        if obv_divergence == "BULLISH_DIV":
            buy_score += 2
            buy_signals.append("OBV dywergencja bycza: smart money akumuluje mimo spadku ceny")
        elif obv_divergence == "BEARISH_DIV":
            buy_score -= 2
            buy_signals.append("UWAGA: OBV dywergencja niedzwiedzia: smart money dystrybuuje (kara -2)")

        # ── PENALTY: Don't buy in strong downtrend without reversal signals ──
        if trend == "DOWN":
            buy_score -= 2
            buy_signals.append("UWAGA: Trend spadkowy (kara -2)")
            if rsi > 40 and macd < macd_signal:
                buy_score -= 2
                buy_signals.append("Lapanie noza: trend DOWN + brak potwierdzenia momentum")

        # ── Knowledge playbooks ──
        knowledge_score, knowledge_reasons = self._apply_knowledge_playbooks(feature_row)
        buy_score += knowledge_score
        buy_signals.extend(knowledge_reasons)

        # ── Check for open trade (SELL logic) ──
        open_trade = session.execute(
            select(SimulatedTrade)
            .where(SimulatedTrade.symbol == symbol, SimulatedTrade.status == "OPEN")
            .order_by(SimulatedTrade.opened_at.desc())
        ).scalar_one_or_none()

        if open_trade is not None:
            sell_reasons: list[str] = []
            current_value = open_trade.quantity * close * (1 - settings.slippage)
            profit_pct = (current_value - (open_trade.buy_value + open_trade.buy_fee)) / (open_trade.buy_value + open_trade.buy_fee)
            hold_hours = (datetime.utcnow() - open_trade.opened_at).total_seconds() / 3600

            profit_target = float(profile["profit_target"]) if learning_mode else 0.04
            stop_loss = float(profile["stop_loss"]) if learning_mode else 0.03

            # ── SELL SIGNALS ──
            sell_score = 0

            # 1. Take Profit
            if profit_pct >= profit_target:
                sell_score += 3
                sell_reasons.append(f"Take profit {profit_pct*100:.1f}% >= {profit_target*100:.0f}%")

            # 2. Stop Loss
            if profit_pct <= -stop_loss:
                sell_score += 4
                sell_reasons.append(f"Stop loss {profit_pct*100:.1f}% <= -{stop_loss*100:.0f}%")

            # 3. RSI Overbought
            if rsi > 70:
                sell_score += 3
                sell_reasons.append(f"RSI wykupiony ({rsi:.0f})")
            elif rsi > 65:
                sell_score += 1
                sell_reasons.append(f"RSI blisko strefy wykupienia ({rsi:.0f})")

            # 4. MACD Bearish Crossover
            if macd < macd_signal and prev_macd >= prev_macd_signal:
                sell_score += 3
                sell_reasons.append("MACD przeciecie niedzwiedzie (swiezy sygnal sprzedazy)")
            elif macd < macd_signal:
                sell_score += 1
                sell_reasons.append("MACD ponizej linii sygnalu")

            # 5. Bollinger upper band (overbought)
            if bb_upper > 0 and bb_lower > 0:
                bb_pos = (close - bb_lower) / (bb_upper - bb_lower) if bb_upper != bb_lower else 0.5
                if bb_pos >= 0.95:
                    sell_score += 2
                    sell_reasons.append("Cena na gornej wstedze Bollingera (wykupienie)")

            # 6. Price below VWAP (institutional selling)
            if close < vwap and vwap > 0 and profit_pct > 0:
                sell_score += 1
                sell_reasons.append("Cena ponizej VWAP (presja sprzedazy)")

            # 7. Bearish RSI divergence
            if close > prev2_close and rsi < prev2_rsi and rsi > 55:
                sell_score += 2
                sell_reasons.append("Dywergencja niedzwiedzia RSI")

            # 8. Top probability
            if top_probability >= 65:
                sell_score += 2
                sell_reasons.append(f"Szansa lokalnego szczytu ({top_probability:.0f}%)")

            # 9. Momentum loss
            if up_probability <= 40:
                sell_score += 2
                sell_reasons.append(f"Utrata momentum ({up_probability:.0f}% szansy na wzrost)")

            # 10. Trailing stop: if was profitable but now losing momentum
            if profit_pct > profit_target * 0.5 and macd_hist < 0 and macd_hist < prev_macd_hist:
                sell_score += 2
                sell_reasons.append("Trailing: zysk maleje, momentum slabnie")

            # 11. Time-based rotation (learning mode)
            if learning_mode and hold_hours >= float(profile["max_hold_hours"]):
                sell_score += 3
                sell_reasons.append(f"Rotacja po {hold_hours:.0f}h")

            # 12. WHALE SELL SIGNALS
            if whale_signal == "WHALE_SELL":
                sell_score += 3
                sell_reasons.append(f"🐋 Wieloryb sprzedaje! Score={whale_score:.1f} - zagrozenie spadkiem")
            elif whale_signal == "SPIKE_DOWN":
                sell_score += 2
                sell_reasons.append(f"Nagly spadek {float(feature_row.get('price_change_pct', 0)):.1f}% przy duzym wolumenie")
            if obv_divergence == "BEARISH_DIV":
                sell_score += 2
                sell_reasons.append("OBV dywergencja: smart money wychodzi z pozycji")
            # Whale buy while holding = hold longer (negative sell pressure)
            if whale_signal == "WHALE_BUY":
                sell_score -= 2
                sell_reasons.append(f"🐋 Wieloryb kupuje - trzymaj pozycje (bonus -2 do sell)")

            # Decision: require confluence for sell too
            if sell_score >= 3:
                decision_value = "SELL"
                confidence = min(0.95, 0.50 + sell_score * 0.06 + max(top_probability - 50, 0) / 100)
                reasons = sell_reasons
            else:
                reasons = ["Trzymaj pozycje: brak sygnalu sprzedazy"]
        else:
            # ── BUY DECISION: require multi-indicator confluence ──
            buy_threshold = int(profile["buy_score_threshold"]) if learning_mode else 6
            # Require minimum 3 different confirming signals
            if buy_score >= buy_threshold and len([s for s in buy_signals if "kara" not in s.lower() and "uwaga" not in s.lower()]) >= 3:
                decision_value = "BUY"
                confidence = min(0.95, 0.40 + buy_score * 0.04 + max(up_probability - 50, 0) / 100)
                reasons = buy_signals
            elif exploration_mode:
                experiment = self._learning_experiment(symbol, feature_row, buy_score, profile)
                if experiment is not None:
                    decision_value = "BUY"
                    confidence = experiment["confidence"]
                    reasons = [experiment["reason"]]
                else:
                    reasons = buy_signals or ["Brak wystarczajacej konfluencji sygnalow"]
            else:
                reasons = buy_signals or ["Brak wystarczajacej konfluencji sygnalow"]

        # ── Daily trade limit ──
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
            score=buy_score if open_trade is None else 0,
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