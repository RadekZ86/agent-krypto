from __future__ import annotations

import json
import logging
import re
from typing import Any

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
    def generate_market_brief(self, dashboard: dict[str, Any], symbol: str | None = None) -> dict[str, str | bool | int | float]:
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
        bybit_wallet = dashboard.get("bybit_wallet")
        bybit_positions = dashboard.get("bybit_positions")
        leverage_paper = dashboard.get("leverage_paper")
        live_portfolio = dashboard.get("live_portfolio")
        selected_symbol = symbol if symbol in chart_packages else dashboard.get("chart_focus_symbol")
        selected_chart = chart_packages.get(selected_symbol) if selected_symbol else None

        is_live = system_status.get("trading_mode") == "LIVE"

        # Build wallet info from all sources
        wallet_parts = []
        if is_live and binance_wallet:
            wallet_parts.append(f"Portfel Binance (LIVE): {binance_wallet}")
        if is_live and bybit_wallet:
            wallet_parts.append(f"Portfel Bybit (LIVE): {bybit_wallet}")
        if is_live and bybit_positions:
            wallet_parts.append(f"Pozycje Bybit perpetual: {bybit_positions}")
        if not wallet_parts:
            wallet_parts.append(f"Portfel paper (symulacja): {paper_wallet}")
        if leverage_paper:
            wallet_parts.append(
                f"Paper dzwignia: equity=${leverage_paper.get('current_equity',0):.0f}, "
                f"P&L=${leverage_paper.get('total_realized_pnl',0):.1f}, "
                f"win_rate={leverage_paper.get('win_rate',0):.0f}%, "
                f"dzwignia={leverage_paper.get('current_leverage_level',2)}x"
            )
        if is_live and live_portfolio:
            wallet_parts.append(f"Holdowane krypto (z P&L): {live_portfolio[:10]}")
        wallet_info = "\n".join(wallet_parts)

        if is_live and (binance_wallet or bybit_wallet):
            mode_instruction = (
                "Uzytkownik jest w trybie LIVE z prawdziwym kontem. "
                "Analizuj dane z portfeli Binance i/lub Bybit. "
                "NIE wspominaj o danych paper tradingu (chyba ze o nauce dzwigni). "
                "Podawaj realne wartosci z kont."
            )
        else:
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
            f"Binance polaczone: {system_status.get('binance_private_ready', False)}\n"
            f"Bybit polaczone: {system_status.get('bybit_private_ready', False)}\n"
            f"Artykuly edukacyjne: {articles[:8]}\n"
            f"Backtest: {backtest}\n"
            f"Live stats: {dashboard.get('live_stats')}\n"
            f"Status systemu: {system_status}\n"
            f"Wybrany wykres ({selected_symbol}): {selected_chart}"
        )

        try:
            response = client.chat.completions.create(
                model=settings.openai_model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
            )
        except Exception:
            return {
                "enabled": False,
                "message": "Nie udalo sie pobrac odpowiedzi z OpenAI. Sprawdz klucz API, limit konta albo polaczenie sieciowe.",
            }

        message = (response.choices[0].message.content or "").strip()
        usage = getattr(response, "usage", None)
        input_tokens = int(getattr(usage, "prompt_tokens", 0) or 0)
        output_tokens = int(getattr(usage, "completion_tokens", 0) or 0)
        total_tokens = int(getattr(usage, "total_tokens", input_tokens + output_tokens) or (input_tokens + output_tokens))
        estimated_cost = ((input_tokens / 1_000_000) * settings.openai_input_cost_per_million) + ((output_tokens / 1_000_000) * settings.openai_output_cost_per_million)

        OpenAIUsageLog(
            model=settings.openai_model,
            symbol=selected_symbol,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            estimated_cost_usd=estimated_cost,
        ).save()

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
        user_message: str,
        dashboard: dict[str, Any],
        conversation_history: list[dict[str, str]] | None = None,
        current_user: Any | None = None,
    ) -> dict[str, Any]:
        """Interactive chat with the agent. User can ask questions about decisions,
        portfolio, market, and give trading commands.
        Admin user (zajcu1986@wp.pl) can also modify agent parameters via chat."""
        if not settings.openai_api_key:
            return {"enabled": False, "reply": "Dodaj OPENAI_API_KEY w pliku .env, aby wlaczyc czat z agentem."}
        if OpenAI is None:
            return {"enabled": False, "reply": "Biblioteka openai nie jest zainstalowana."}

        # Check if admin user (self-modification rights)
        from app.services.self_modify import is_admin
        admin_mode = is_admin(current_user)

        client = OpenAI(api_key=settings.openai_api_key)

        system_status = dashboard.get("system_status", {})
        binance_wallet = dashboard.get("binance_wallet")
        bybit_wallet = dashboard.get("bybit_wallet")
        bybit_positions = dashboard.get("bybit_positions")
        leverage_paper = dashboard.get("leverage_paper")
        live_portfolio = dashboard.get("live_portfolio")
        is_live = system_status.get("trading_mode") == "LIVE"

        # Build comprehensive wallet info
        wallet_parts = []
        if is_live and binance_wallet:
            wallet_parts.append(f"Portfel Binance (LIVE): {binance_wallet}")
        if is_live and bybit_wallet:
            wallet_parts.append(f"Portfel Bybit (LIVE): {bybit_wallet}")
        if is_live and bybit_positions:
            wallet_parts.append(f"Pozycje Bybit perpetual: {bybit_positions}")
        if not wallet_parts:
            wallet_parts.append(f"Portfel paper (symulacja): {dashboard.get('wallet', {})}")
        if leverage_paper:
            wallet_parts.append(
                f"Paper dźwignia: equity=${leverage_paper.get('current_equity',0):.0f}, "
                f"P&L=${leverage_paper.get('total_realized_pnl',0):.1f}, "
                f"win_rate={leverage_paper.get('win_rate',0):.0f}%, "
                f"dźwignia={leverage_paper.get('current_leverage_level',2)}x, "
                f"otwarte={len(leverage_paper.get('open_positions',[]))}"
            )
        if is_live and live_portfolio:
            wallet_parts.append(f"Holdowane krypto (z P&L): {live_portfolio[:10]}")
        wallet_info = "\n".join(wallet_parts)

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

        live_stats = dashboard.get("live_stats") or {}
        fee_info = ""
        if live_stats.get("total_commission"):
            comm_parts = [f"{asset}: {amt}" for asset, amt in live_stats.get("commission_by_asset", {}).items()]
            fee_info = f"\nProwizje LIVE lacznie: {live_stats['total_commission']} ({', '.join(comm_parts)})"

        system_prompt = (
            "Jestes Agent Krypto — inteligentny asystent tradingowy kryptowalutowy. "
            "Odpowiadasz po polsku, krotko i konkretnie (max 8 zdan). "
            "Masz pelny dostep do danych portfela (Binance + Bybit), rynku, "
            "paper tradingu z dzwignia, i historii decyzji agenta. "
            "Mozesz wyjasnic dlaczego agent kupil/sprzedal dane krypto, opierajac sie na danych decyzji i wskaznikach. "
            "Masz dostep do danych dzwigni (leverage paper trading) — mozesz wyjasniac pozycje LONG/SHORT, TP/SL, funding rate. "
            "Znasz prowizje handlowe i mozesz wyjasnic ich wplyw na zysk/strate. "
            "Jesli uzytkownik prosi o kupno/sprzedaz, mozesz to wykonac (w trybie LIVE na Binance lub Bybit). "
            "Zawsze ostrzegaj o ryzyku. Nie skladaj obietnic zysku. "
            "Jesli nie masz pewnych danych, powiedz to wprost.\n\n"
            f"KONTEKST:\n"
            f"{wallet_info}\n"
            f"Rynek (top 10): {dashboard.get('market', [])[:10]}\n"
            f"Ostatnie decyzje: {dashboard.get('recent_decisions', [])[:5]}\n"
            f"Ostatnie transakcje: {dashboard.get('recent_trades', [])[:5]}\n"
            f"Tryb handlu: {system_status.get('trading_mode', 'PAPER')}\n"
            f"Tryb agenta: {system_status.get('agent_mode', 'normal')}\n"
            f"Binance polaczone: {system_status.get('binance_private_ready', False)}\n"
            f"Bybit polaczone: {system_status.get('bybit_private_ready', False)}\n"
            f"Prywatne uczenie: {dashboard.get('private_learning')}\n"
            f"Ranking trade'ow: {dashboard.get('trade_ranking')}\n"
            f"Live stats: {live_stats}\n"
            f"{fee_info}\n"
            f"Status: {system_status}"
            f"{command_context}"
        )

        # Admin self-modification tools
        if admin_mode:
            # Pre-fetch current state for the AI context
            from app.services.self_modify import execute_command as _exec_cmd
            _current_state = _exec_cmd({"tool": "get_params"}, current_user)
            _learn_state = _exec_cmd({"tool": "get_learning_stats"}, current_user)
            _adaptive = _exec_cmd({"tool": "get_adaptive_state"}, current_user)

            system_prompt += (
                "\n\n=== TRYB ADMINISTRATORA (SELF-MODIFY) ===\n"
                "Uzytkownik jest administratorem i moze Cie prosic o zmiane parametrow agenta. "
                "Masz dostep do narzedzi modyfikacji. Gdy uzytkownik prosi o zmiane parametru, "
                "odpowiedz normalnie i DODAJ na koncu polecenie w formacie:\n"
                '<!--SELFMOD:{"tool":"nazwa","params":{...}}-->\n\n'
                "Dostepne narzedzia:\n"
                '1. set_param - zmien parametr: {"tool":"set_param","params":{"key":"buy_score_threshold","value":5}}\n'
                "   Dozwolone klucze: buy_score_threshold (1-10), profit_target (0.005-0.15), "
                "stop_loss (0.005-0.15), max_hold_hours (1-168), max_trades_per_day (1-9999), "
                "max_open_positions (1-9999), exploration_rate (0-0.5), allocation_scale (0.1-3.0)\n"
                '2. set_agent_mode - zmien tryb: {"tool":"set_agent_mode","params":{"mode":"risky"}}\n'
                "   Tryby: cautious, normal, risky, trading\n"
                '3. get_signal_ranking - pokaz ranking sygnalow: {"tool":"get_signal_ranking","params":{}}\n'
                '4. reset_signal_stats - resetuj statystyki sygnalow: {"tool":"reset_signal_stats","params":{}}\n\n'
                "Mozesz uzyc wielu polecen na raz (kazde w osobnym <!--SELFMOD:...-->).\n"
                "NIGDY nie modyfikuj parametrow bez wyraznej prosby uzytkownika.\n"
                "Opisz co zmieniasz i dlaczego.\n\n"
                f"Aktualny profil: {json.dumps(_current_state.get('active_profile', {}), ensure_ascii=False, default=str)}\n"
                f"Nadpisania reczne: {json.dumps(_current_state.get('manual_overrides', {}), ensure_ascii=False)}\n"
                f"Statystyki nauki: {json.dumps(_learn_state, ensure_ascii=False, default=str)}\n"
                f"Stan adaptacji: {json.dumps(_adaptive, ensure_ascii=False, default=str)}\n"
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

        OpenAIUsageLog(
            model=settings.openai_model,
            symbol=command["symbol"] if command else "chat",
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            estimated_cost_usd=estimated_cost,
        ).save()

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

        # Extract and execute self-modification commands (admin only)
        selfmod_results = []
        if admin_mode:
            from app.services.self_modify import execute_command as _exec_selfmod
            selfmod_matches = re.findall(r'<!--SELFMOD:(\{.*?\})-->', reply)
            for match_str in selfmod_matches:
                try:
                    selfmod_cmd = json.loads(match_str)
                    result = _exec_selfmod(selfmod_cmd, current_user)
                    selfmod_results.append(result)
                    logger.info("SELFMOD executed: %s -> %s", selfmod_cmd.get("tool"), result.get("ok"))
                except (json.JSONDecodeError, Exception) as exc:
                    selfmod_results.append({"ok": False, "error": str(exc)})
            # Remove SELFMOD tags from visible reply
            reply = re.sub(r'<!--SELFMOD:\{.*?\}-->', '', reply).strip()

        return {
            "enabled": True,
            "reply": reply,
            "command": detected_cmd or command,
            "selfmod_results": selfmod_results if selfmod_results else None,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "estimated_cost_usd": round(estimated_cost, 6),
        }