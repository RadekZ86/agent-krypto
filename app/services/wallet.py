from __future__ import annotations

from datetime import datetime

from app.config import settings
from app.models import Decision, LearningLog, MarketData, SimulatedTrade
from app.services.market_data import LiveQuoteService, load_latest_market_row
from app.services.runtime_state import RuntimeStateService


class WalletService:
    def __init__(self) -> None:
        self.runtime_state = RuntimeStateService()
        self.live_quotes = LiveQuoteService()

    def execute_decision(self, decision: Decision, market_price: float) -> dict[str, float | str] | None:
        if decision.decision == "BUY":
            return self._open_position(decision, market_price)
        if decision.decision == "SELL":
            return self._close_position(decision, market_price)
        if decision.decision == "PARTIAL_SELL":
            return self._partial_close_position(decision, market_price)
        return None

    def reset_paper_portfolio(self) -> dict[str, int]:
        deleted_trades = SimulatedTrade.objects.all().delete()[0]
        deleted_logs = LearningLog.objects.all().delete()[0]
        return {
            "deleted_trades": int(deleted_trades or 0),
            "deleted_learning_logs": int(deleted_logs or 0),
        }

    def get_snapshot(self) -> dict[str, object]:
        trades = list(SimulatedTrade.objects.order_by('opened_at'))
        open_trades = [trade for trade in trades if trade.status == "OPEN"]
        closed_trades = [trade for trade in trades if trade.status == "CLOSED"]
        winning_trades = [trade for trade in closed_trades if (trade.profit or 0.0) > 0]
        losing_trades = [trade for trade in closed_trades if (trade.profit or 0.0) < 0]

        total_buy_value = sum(trade.buy_value for trade in trades)
        total_buy_fees = sum(trade.buy_fee for trade in trades)
        total_sell_value = sum(trade.sell_value or 0.0 for trade in closed_trades)
        total_sell_fees = sum(trade.sell_fee or 0.0 for trade in closed_trades)
        cash = settings.starting_balance_quote
        for trade in trades:
            cash -= trade.buy_value + trade.buy_fee
            if trade.sell_value is not None:
                cash += trade.sell_value

        positions: list[dict[str, float | str]] = []
        open_value = 0.0
        unrealized_profit = 0.0
        for trade in open_trades:
            current_price = self._latest_price(trade.symbol) or trade.buy_price
            current_value = trade.quantity * current_price
            total_cost = trade.buy_value + trade.buy_fee
            pnl_value = current_value - total_cost
            pnl_pct = pnl_value / total_cost if total_cost else 0.0
            open_value += current_value
            unrealized_profit += pnl_value
            positions.append(
                {
                    "symbol": trade.symbol,
                    "quantity": round(trade.quantity, 6),
                    "buy_price": round(trade.buy_price, 2),
                    "current_price": round(current_price, 2),
                    "value": round(current_value, 2),
                    "pnl_value": round(pnl_value, 2),
                    "pnl_pct": round(pnl_pct * 100, 2),
                }
            )

        realized_profit = sum((trade.profit or 0.0) for trade in closed_trades)
        gross_profit = sum(trade.profit or 0.0 for trade in winning_trades)
        gross_loss = abs(sum(trade.profit or 0.0 for trade in losing_trades))
        profitable_trades = len(winning_trades)
        win_rate = (profitable_trades / len(closed_trades) * 100) if closed_trades else 0.0
        monthly_profit = sum(
            (trade.profit or 0.0)
            for trade in closed_trades
            if trade.closed_at is not None and (datetime.utcnow() - trade.closed_at).days <= 30
        )
        last_closed_trade = closed_trades[-1] if closed_trades else None

        return {
            "cash_balance": round(cash, 2),
            "open_value": round(open_value, 2),
            "equity": round(cash + open_value, 2),
            "realized_profit": round(realized_profit, 2),
            "gross_profit": round(gross_profit, 2),
            "gross_loss": round(gross_loss, 2),
            "unrealized_profit": round(unrealized_profit, 2),
            "win_rate": round(win_rate, 2),
            "monthly_roi": round((monthly_profit / settings.starting_balance_quote) * 100, 2) if settings.starting_balance_quote else 0.0,
            "positions": positions,
            "closed_trades_count": len(closed_trades),
            "open_positions_count": len(open_trades),
            "buy_count": len(trades),
            "sell_count": len(closed_trades),
            "winning_trades_count": len(winning_trades),
            "losing_trades_count": len(losing_trades),
            "starting_balance": round(settings.starting_balance_quote, 2),
            "spent_on_buys": round(total_buy_value, 2),
            "capital_returned": round(total_sell_value, 2),
            "fees_paid": round(total_buy_fees + total_sell_fees, 2),
            "capital_locked_cost": round(sum((trade.buy_value + trade.buy_fee) for trade in open_trades), 2),
            "last_closed_trade": {
                "symbol": last_closed_trade.symbol,
                "profit": round(last_closed_trade.profit or 0.0, 2),
                "closed_at": last_closed_trade.closed_at.isoformat() if last_closed_trade.closed_at is not None else None,
            }
            if last_closed_trade is not None
            else None,
        }

    def _open_position(self, decision: Decision, market_price: float) -> dict[str, float | str] | None:
        existing_position = SimulatedTrade.objects.filter(symbol=decision.symbol, status="OPEN").first()
        if existing_position is not None:
            return None

        open_positions_count = SimulatedTrade.objects.filter(status="OPEN").count()
        profile = self.runtime_state.get_active_profile()
        if int(open_positions_count) >= int(profile["max_open_positions"]):
            return None

        cash = float(self.get_snapshot()["cash_balance"])
        allocation_scale = float(profile.get("allocation_scale", 1.0))
        target_allocation = settings.allocation_quote.get(decision.symbol, 40.0) * allocation_scale
        gross_value = min(target_allocation, cash * 0.95)
        if gross_value < 25:
            return None

        executed_price = market_price * (1 + settings.slippage)
        buy_fee = gross_value * settings.fee_rate
        total_cost = gross_value + buy_fee
        if total_cost > cash:
            gross_value = cash / (1 + settings.fee_rate)
            buy_fee = gross_value * settings.fee_rate
            total_cost = gross_value + buy_fee

        if gross_value < 25:
            return None

        quantity = gross_value / executed_price
        trade = SimulatedTrade(
            symbol=decision.symbol,
            decision_id=decision.id,
            buy_price=executed_price,
            quantity=quantity,
            buy_value=gross_value,
            buy_fee=buy_fee,
            status="OPEN",
            opened_at=datetime.utcnow(),
        )
        trade.save()
        return {
            "action": "BUY",
            "symbol": decision.symbol,
            "price": round(executed_price, 2),
            "quantity": round(quantity, 6),
            "cost": round(total_cost, 2),
        }

    def _close_position(self, decision: Decision, market_price: float) -> dict[str, float | str] | None:
        trade = SimulatedTrade.objects.filter(symbol=decision.symbol, status="OPEN").order_by('-opened_at').first()
        if trade is None:
            return None

        executed_price = market_price * (1 - settings.slippage)
        gross_proceeds = trade.quantity * executed_price
        sell_fee = gross_proceeds * settings.fee_rate
        sell_value = gross_proceeds - sell_fee
        total_cost = trade.buy_value + trade.buy_fee

        trade.sell_price = executed_price
        trade.sell_fee = sell_fee
        trade.sell_value = sell_value
        trade.profit = sell_value - total_cost
        trade.duration_minutes = (datetime.utcnow() - trade.opened_at).total_seconds() / 60
        trade.status = "CLOSED"
        trade.closed_at = datetime.utcnow()
        trade.save()

        return {
            "action": "SELL",
            "symbol": decision.symbol,
            "price": round(executed_price, 2),
            "profit": round(trade.profit or 0.0, 2),
        }

    def _partial_close_position(self, decision: Decision, market_price: float, fraction: float = 0.5) -> dict[str, float | str] | None:
        """Zamknij czesc pozycji (domyslnie 50%) i pozostaw reszte OPEN.

        Mechanizm: tworzymy NOWA transakcje CLOSED z czescia quantity (linkowana do tego
        samego decision_id zeby oznaczyc ze partial juz nastapil) oraz redukujemy quantity
        i buy_value oryginalnego OPEN trade'a proporcjonalnie. Nie dodajemy nowej kolumny
        do tabeli - wystarczy ze sibling CLOSED z tym samym decision_id dziala jako flaga.
        """
        trade = SimulatedTrade.objects.filter(symbol=decision.symbol, status="OPEN").order_by('-opened_at').first()
        if trade is None:
            return None
        if fraction <= 0 or fraction >= 1:
            return None
        # Jezeli juz byl partial dla tego decision_id - nie rob drugiego
        if trade.decision_id and SimulatedTrade.objects.filter(decision_id=trade.decision_id, status="CLOSED").exists():
            return None

        executed_price = market_price * (1 - settings.slippage)
        partial_qty = trade.quantity * fraction
        remaining_qty = trade.quantity - partial_qty

        partial_buy_value = trade.buy_value * fraction
        partial_buy_fee = trade.buy_fee * fraction

        gross_proceeds = partial_qty * executed_price
        sell_fee = gross_proceeds * settings.fee_rate
        sell_value = gross_proceeds - sell_fee
        partial_profit = sell_value - (partial_buy_value + partial_buy_fee)

        # Utworz CLOSED trade dla sprzedanej czesci (dziedziczy decision_id - sluzy jako flaga partial)
        closed_leg = SimulatedTrade(
            symbol=trade.symbol,
            decision_id=trade.decision_id,
            buy_price=trade.buy_price,
            sell_price=executed_price,
            quantity=partial_qty,
            buy_value=partial_buy_value,
            buy_fee=partial_buy_fee,
            sell_value=sell_value,
            sell_fee=sell_fee,
            profit=partial_profit,
            duration_minutes=(datetime.utcnow() - trade.opened_at).total_seconds() / 60,
            status="CLOSED",
            opened_at=trade.opened_at,
            closed_at=datetime.utcnow(),
        )
        closed_leg.save()

        # Zredukuj oryginalny OPEN trade do pozostalej czesci
        trade.quantity = remaining_qty
        trade.buy_value = trade.buy_value - partial_buy_value
        trade.buy_fee = trade.buy_fee - partial_buy_fee
        trade.save()

        return {
            "action": "PARTIAL_SELL",
            "symbol": decision.symbol,
            "price": round(executed_price, 2),
            "quantity_sold": round(partial_qty, 6),
            "quantity_remaining": round(remaining_qty, 6),
            "profit": round(partial_profit, 2),
        }

    def _latest_price(self, symbol: str) -> float | None:
        live_quote = self.live_quotes.get_quote(symbol)
        if live_quote is not None:
            return float(live_quote["price"])
        row = load_latest_market_row(symbol)
        return float(row.close) if row is not None else None