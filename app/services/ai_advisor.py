from __future__ import annotations

import logging
import re
from typing import Any

from sqlalchemy.orm import Session

from app.config import settings
from app.models import OpenAIUsageLog

try:
    from openai import OpenAI
except ImportError:
    OpenAI = None

logger = logging.getLogger(__name__)

# Pattern for detecting trade commands in user messages
_CMD_BUY_RE = re.compile(r'\b(?:kup|buy|zakup|zamów)\s+([A-Z]{2,10})\b', re.IGNORECASE)
_CMD_SELL_RE = re.compile(r'\b(?:sprzedaj|sell|pozbądź|zlikwiduj)\s+([A-Z]{2,10})\b', re.IGNORECASE)
_CMD_SELL_ALL_RE = re.compile(r'\b(?:sprzedaj|sell)\s+(?:wszystko|all|cały|calego|calość)\b', re.IGNORECASE)


def parse_user_command(message: str) -> dict | None:
    """Parse user chat message for actionable trade commands.
    Returns dict with 'action' and 'symbol' or None if no command detected."""
    if _CMD_SELL_ALL_RE.search(message):
        return {"action": "SELL_ALL", "symbol": None}
    m = _CMD_SELL_RE.search(message)
    if m:
        return {"action": "SELL", "symbol": m.group(1).upper()}
    m = _CMD_BUY_RE.search(message)
    if m:
        return {"action": "BUY", "symbol": m.group(1).upper()}
    return None


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
        paper_wallet = dashboard["wallet"]
        market_rows = dashboard["market"]
        decision_rows = dashboard["recent_decisions"][:5]
        learning = dashboard.get("learning", {})
        chart_packages = dashboard.get("chart_packages", {})
        backtest = dashboard.get("backtest", {})
        articles = dashboard.get("articles", [])
        system_status = dashboard.get("system_status", {})
        private_learning = dashboard.get("private_learning")
        trade_ranking = dashboard.get("trade_ranking")
        binance_wallet = dashboard.get("binance_wallet")
        selected_symbol = symbol if symbol in chart_packages else dashboard.get("chart_focus_symbol")
        selected_chart = chart_packages.get(selected_symbol) if selected_symbol else None

        is_live = system_status.get("trading_mode") == "LIVE" and binance_wallet is not None

        if is_live:
            wallet_info = f"Portfel Binance (LIVE): {binance_wallet}"
            mode_instruction = (
                "Uzytkownik jest w trybie LIVE z prawdziwym kontem Binance. "
                "Analizuj WYLACZNIE dane z portfela Binance powyzej. "
                "NIE wspominaj o danych paper tradingu. "
                "Podawaj realne wartosci z konta Binance."
            )
        else:
            wallet_info = f"Portfel paper (symulacja): {paper_wallet}"
            mode_instruction = (
                "Tryb PAPER — nazywaj wynik portfela symulowanym wynikiem paper tradingu, a nie realnym zarobkiem."
            )

        prompt = (
            "Napisz po polsku zwiezla analize panelu kryptowalutowego. "
            "Maksymalnie 6 zdan. Uwzglednij stan portfela, ryzyko, wykres wybranego symbolu i czego agent powinien sie dalej uczyc. "
            "Nie dawaj obietnic zysku ani porad inwestycyjnych. "
            "Zasada nadrzedna: zero klamstwa. Nie wolno niczego dopowiadac, zgadywac ani ukrywac niepewnosci. "
            "Jesli dane sa niepelne, stale lub niespojne, napisz to wprost. "
            f"{mode_instruction}\n\n"
            f"{wallet_info}\n"
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

    def chat(
        self,
        session: Session,
        user_message: str,
        dashboard: dict[str, Any],
        conversation_history: list[dict[str, str]] | None = None,
    ) -> dict[str, Any]:
        """Interactive chat with the agent. User can ask questions about decisions,
        portfolio, market, and give trading commands."""
        if not settings.openai_api_key:
            return {"enabled": False, "reply": "Dodaj OPENAI_API_KEY w pliku .env, aby wlaczyc czat z agentem."}
        if OpenAI is None:
            return {"enabled": False, "reply": "Biblioteka openai nie jest zainstalowana."}

        client = OpenAI(api_key=settings.openai_api_key)

        system_status = dashboard.get("system_status", {})
        binance_wallet = dashboard.get("binance_wallet")
        is_live = system_status.get("trading_mode") == "LIVE" and binance_wallet is not None

        if is_live:
            wallet_info = f"Portfel Binance (LIVE): {binance_wallet}"
        else:
            wallet_info = f"Portfel paper (symulacja): {dashboard['wallet']}"

        # Detect commands
        command = parse_user_command(user_message)
        command_context = ""
        if command:
            command_context = (
                f"\n\nUWAGA: Uzytkownik wydal polecenie handlowe: {command}. "
                "Jesli to BUY lub SELL, powiedz ze wykonasz zlecenie i opisz krotko dlaczego to moze byc dobry/zly pomysl. "
                "Dodaj ostrzezenie o ryzyku. Odpowiedz koniecznie zawieraj JSON na koncu w formacie: "
                '<!--CMD:{"action":"BUY/SELL","symbol":"SYMBOL"}-->'
            )

        system_prompt = (
            "Jestes Agent Krypto — inteligentny asystent tradingowy kryptowalutowy. "
            "Odpowiadasz po polsku, krotko i konkretnie (max 8 zdan). "
            "Masz pelny dostep do danych portfela, rynku i historii decyzji agenta. "
            "Mozesz wyjasnic dlaczego agent kupil/sprzedal dane krypto, opierajac sie na danych decyzji i wskaznikach. "
            "Jesli uzytkownik prosi o kupno/sprzedaz, mozesz to wykonac (w trybie LIVE na Binance). "
            "Zawsze ostrzegaj o ryzyku. Nie skladaj obietnic zysku. "
            "Jesli nie masz pewnych danych, powiedz to wprost.\n\n"
            f"KONTEKST:\n"
            f"{wallet_info}\n"
            f"Rynek: {dashboard.get('market', [])[:10]}\n"
            f"Ostatnie decyzje: {dashboard.get('recent_decisions', [])[:5]}\n"
            f"Ostatnie transakcje: {dashboard.get('recent_trades', [])[:5]}\n"
            f"Tryb handlu: {system_status.get('trading_mode', 'PAPER')}\n"
            f"Tryb agenta: {system_status.get('agent_mode', 'normal')}\n"
            f"Prywatne uczenie: {dashboard.get('private_learning')}\n"
            f"Ranking trade'ow: {dashboard.get('trade_ranking')}\n"
            f"Status: {system_status}"
            f"{command_context}"
        )

        messages = [{"role": "system", "content": system_prompt}]
        if conversation_history:
            for msg in conversation_history[-10:]:  # Keep last 10 messages for context
                messages.append({"role": msg.get("role", "user"), "content": msg.get("content", "")})
        messages.append({"role": "user", "content": user_message})

        try:
            response = client.chat.completions.create(
                model=settings.openai_model,
                messages=messages,
                temperature=0.4,
                max_tokens=500,
            )
        except Exception as exc:
            logger.error("Agent chat OpenAI error: %s", exc)
            return {"enabled": False, "reply": "Nie udalo sie uzyskac odpowiedzi od AI. Sprawdz klucz API."}

        reply = response.choices[0].message.content.strip()
        usage = response.usage
        input_tokens = getattr(usage, "prompt_tokens", 0) or 0
        output_tokens = getattr(usage, "completion_tokens", 0) or 0
        total_tokens = input_tokens + output_tokens
        estimated_cost = ((input_tokens / 1_000_000) * settings.openai_input_cost_per_million) + ((output_tokens / 1_000_000) * settings.openai_output_cost_per_million)

        session.add(
            OpenAIUsageLog(
                model=settings.openai_model,
                symbol=command["symbol"] if command else "chat",
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                total_tokens=total_tokens,
                estimated_cost_usd=estimated_cost,
            )
        )
        session.commit()

        # Extract embedded command from AI response
        detected_cmd = None
        cmd_match = re.search(r'<!--CMD:(\{.*?\})-->', reply)
        if cmd_match:
            import json
            try:
                detected_cmd = json.loads(cmd_match.group(1))
            except json.JSONDecodeError:
                pass
            # Remove CMD tag from visible reply
            reply = re.sub(r'<!--CMD:\{.*?\}-->', '', reply).strip()

        return {
            "enabled": True,
            "reply": reply,
            "command": detected_cmd or command,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "estimated_cost_usd": round(estimated_cost, 6),
        }