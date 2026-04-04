from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.config import settings
from app.models import OpenAIUsageLog

try:
    from openai import OpenAI
except ImportError:
    OpenAI = None


class AIAdvisor:
    def generate_market_brief(self, session: Session, dashboard: dict[str, Any], symbol: str | None = None) -> dict[str, str | bool | int | float]:
        if not settings.openai_api_key:
            return {
                "enabled": False,
                "message": "Dodaj OPENAI_API_KEY w pliku .env, aby wlaczyc komentarz AI.",
            }

        if OpenAI is None:
            return {
                "enabled": False,
                "message": "Biblioteka openai nie jest zainstalowana.",
            }

        client = OpenAI(api_key=settings.openai_api_key)
        wallet = dashboard["wallet"]
        market_rows = dashboard["market"]
        decision_rows = dashboard["recent_decisions"][:5]
        learning = dashboard.get("learning", {})
        chart_packages = dashboard.get("chart_packages", {})
        backtest = dashboard.get("backtest", {})
        articles = dashboard.get("articles", [])
        system_status = dashboard.get("system_status", {})
        private_learning = dashboard.get("private_learning")
        trade_ranking = dashboard.get("trade_ranking")
        selected_symbol = symbol if symbol in chart_packages else dashboard.get("chart_focus_symbol")
        selected_chart = chart_packages.get(selected_symbol) if selected_symbol else None

        prompt = (
            "Napisz po polsku zwiezla analize panelu kryptowalutowego. "
            "Maksymalnie 6 zdan. Uwzglednij stan portfela, ryzyko, wykres wybranego symbolu i czego agent powinien sie dalej uczyc. "
            "Nie dawaj obietnic zysku ani porad inwestycyjnych. "
            "Zasada nadrzedna: zero klamstwa. Nie wolno niczego dopowiadac, zgadywac ani ukrywac niepewnosci. "
            "Jesli dane sa niepelne, stale lub niespojne, napisz to wprost. "
            "Jesli trading_mode to PAPER, nazywaj wynik portfela symulowanym wynikiem paper tradingu, a nie realnym zarobkiem.\n\n"
            f"Portfel: {wallet}\n"
            f"Rynek: {market_rows}\n"
            f"Decyzje: {decision_rows}\n"
            f"Wnioski nauki: {learning.get('findings', [])}\n"
            f"Program nauki: {learning.get('curriculum', [])}\n"
            f"Playbooki wiedzy: {learning.get('knowledge_base', [])}\n"
            f"Nastepne kroki: {learning.get('next_steps', [])}\n"
            f"Braki systemu: {learning.get('requirements', [])}\n"
            f"Prywatne uczenie Binance: {private_learning}\n"
            f"Ranking trade'ow Binance: {trade_ranking}\n"
            f"Artykuly edukacyjne: {articles[:8]}\n"
            f"Backtest: {backtest}\n"
            f"Status systemu: {system_status}\n"
            f"Wybrany wykres ({selected_symbol}): {selected_chart}"
        )

        try:
            response = client.responses.create(
                model=settings.openai_model,
                input=prompt,
                temperature=0.3,
            )
        except Exception:
            return {
                "enabled": False,
                "message": "Nie udalo sie pobrac odpowiedzi z OpenAI. Sprawdz klucz API, limit konta albo polaczenie sieciowe.",
            }

        message = response.output_text.strip()
        usage = getattr(response, "usage", None)
        input_tokens = int(getattr(usage, "input_tokens", 0) or 0)
        output_tokens = int(getattr(usage, "output_tokens", 0) or 0)
        total_tokens = int(getattr(usage, "total_tokens", input_tokens + output_tokens) or (input_tokens + output_tokens))
        estimated_cost = ((input_tokens / 1_000_000) * settings.openai_input_cost_per_million) + ((output_tokens / 1_000_000) * settings.openai_output_cost_per_million)

        session.add(
            OpenAIUsageLog(
                model=settings.openai_model,
                symbol=selected_symbol,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                total_tokens=total_tokens,
                estimated_cost_usd=estimated_cost,
            )
        )
        session.commit()
        return {
            "enabled": True,
            "message": message,
            "symbol": selected_symbol or "global",
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": total_tokens,
            "estimated_cost_usd": round(estimated_cost, 6),
        }