from __future__ import annotations

import json
import logging
import math
import os
import re
import threading
import time as _time
from collections import defaultdict
from datetime import datetime, date, timedelta
from pathlib import Path

from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST, require_http_methods
from django.db.models import Count, Max, Sum
from django.db.models.functions import Coalesce
from django_ratelimit.decorators import ratelimit

from app.config import settings
from app.models import (
    AuditLog,
    Decision,
    FeatureSnapshot,
    LeverageSimTrade,
    LiveOrderLog,
    MarketData,
    OpenAIUsageLog,
    SimulatedTrade,
    User,
    WhaleAlert,
)
from app.services.agent_cycle import AgentCycle
from app.services.ai_advisor import AIAdvisor
from app.services.auth import APIKeyService, AuthService
from app.services.backtest import BacktestService
from app.services.binance_api import BinanceService
from app.services.bybit_api import BybitService
from app.services.currency_service import CurrencyService
from app.services.learning_center import LearningCenter
from app.services.leverage_engine import LeverageEngine
from app.services.market_data import LiveQuoteService, load_latest_market_row
from app.services.runtime_state import RuntimeStateService
from app.services.scheduler import SchedulerService
from app.services.wallet import WalletService

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Exchange data cache (per-user, TTL-based)
# ---------------------------------------------------------------------------
_exchange_cache: dict[int, dict] = {}
_exchange_cache_lock = threading.Lock()
_EXCHANGE_CACHE_TTL = 120  # seconds


def _get_exchange_cache(user_id: int) -> dict | None:
    with _exchange_cache_lock:
        entry = _exchange_cache.get(user_id)
        if entry and (_time.time() - entry["ts"]) < _EXCHANGE_CACHE_TTL:
            return entry["data"]
    return None


def _set_exchange_cache(user_id: int, data: dict) -> None:
    with _exchange_cache_lock:
        _exchange_cache[user_id] = {"ts": _time.time(), "data": data}


# ---------------------------------------------------------------------------
# Static assets version (cache-buster)
# ---------------------------------------------------------------------------
base_dir = Path(__file__).resolve().parent
try:
    static_assets_version = str(
        max(
            int((base_dir / "static" / "app.js").stat().st_mtime),
            int((base_dir / "static" / "styles.css").stat().st_mtime),
        )
    )
except FileNotFoundError:
    static_assets_version = "0"

# ---------------------------------------------------------------------------
# Module-level service singletons
# ---------------------------------------------------------------------------
cycle_runner = AgentCycle()
wallet_service = WalletService()
ai_advisor = AIAdvisor()
learning_center = LearningCenter()
backtest_service = BacktestService()
runtime_state = RuntimeStateService()
currency_service = CurrencyService()
live_quote_service = LiveQuoteService()
auth_service = AuthService()
api_key_service = APIKeyService()
binance_service = BinanceService()
bybit_service = BybitService()
leverage_engine = LeverageEngine()


def run_managed_cycle() -> dict[str, object]:
    return cycle_runner.run()


scheduler_service = SchedulerService(settings.cycle_interval_seconds, run_managed_cycle)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def no_cache_headers() -> dict[str, str]:
    return {
        "Cache-Control": "no-store, max-age=0",
        "Pragma": "no-cache",
    }


def _apply_no_cache(response: JsonResponse) -> JsonResponse:
    for header, value in no_cache_headers().items():
        response[header] = value
    return response


def resolve_request_user(request) -> User | None:
    session_token = request.COOKIES.get("session_token")
    if not session_token:
        return None
    return auth_service.validate_token(session_token)


def _require_auth(request):
    """Return (user, None) when authenticated, or (None, JsonResponse) when not."""
    user = resolve_request_user(request)
    if user is None:
        return None, JsonResponse({"detail": "Wymagane logowanie"}, status=401)
    return user, None


def serialize_user(user: User) -> dict[str, object]:
    return {
        "id": user.id,
        "email": user.email,
        "username": user.username,
        "trading_mode": getattr(user, "trading_mode", "PAPER"),
        "agent_mode": getattr(user, "agent_mode", "normal"),
        "created_at": user.created_at.isoformat() if user.created_at else None,
    }


def _get_client_ip(request) -> str:
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if forwarded:
        return forwarded.split(",")[0].strip()[:45]
    real_ip = request.META.get("HTTP_X_REAL_IP", "")
    if real_ip:
        return real_ip[:45]
    return (request.META.get("REMOTE_ADDR") or "unknown")[:45]


def get_user_binance_client(user_id: int, key_id: int | None = None):
    keys = api_key_service.get_user_api_keys(user_id)
    if not keys:
        return None, None
    selected_key = next((key for key in keys if key.id == key_id), None) if key_id is not None else keys[0]
    if selected_key is None:
        return None, None
    api_secret = api_key_service.get_decrypted_secret(selected_key)
    if not api_secret:
        return selected_key, None
    return selected_key, binance_service.get_client(
        api_key=selected_key.api_key,
        api_secret=api_secret,
        testnet=selected_key.is_testnet,
    )


def get_user_bybit_client(user_id: int, key_id: int | None = None):
    keys = api_key_service.get_user_api_keys(user_id)
    bybit_keys = [k for k in keys if k.exchange == "bybit"]
    if not bybit_keys:
        return None, None
    selected_key = next((k for k in bybit_keys if k.id == key_id), None) if key_id is not None else bybit_keys[0]
    if selected_key is None:
        return None, None
    api_secret = api_key_service.get_decrypted_secret(selected_key)
    if not api_secret:
        return selected_key, None
    return selected_key, bybit_service.get_client(
        api_key=selected_key.api_key,
        api_secret=api_secret,
        testnet=selected_key.is_testnet,
    )


def _set_session_cookie(response: JsonResponse, token: str) -> None:
    _secure = os.getenv("FORCE_HTTPS", "").lower() in ("1", "true")
    response.set_cookie(
        key="session_token",
        value=token,
        httponly=True,
        secure=_secure,
        max_age=24 * 3600,
        samesite="Strict" if _secure else "Lax",
    )


# ---------------------------------------------------------------------------
# Inline validation helpers (replaces Pydantic)
# ---------------------------------------------------------------------------
_EMAIL_RE = re.compile(r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$")
_USERNAME_RE = re.compile(r"^[a-zA-Z0-9_\-]+$")
_ALPHANUMERIC_RE = re.compile(r"^[a-zA-Z0-9]+$")
_EXCHANGE_RE = re.compile(r"^[a-z]+$")
_PERMISSIONS_RE = re.compile(r"^(read|trade)$")
_ACTION_RE = re.compile(r"^(BUY|SELL)$")
_SYMBOL_RE = re.compile(r"^[A-Z]+$")


def _parse_json_body(request):
    """Return (parsed_dict, None) or (None, JsonResponse) on error."""
    try:
        return json.loads(request.body), None
    except (json.JSONDecodeError, ValueError):
        return None, JsonResponse({"detail": "Nieprawidłowe dane JSON"}, status=400)


# ===================================================================
# VIEW FUNCTIONS
# ===================================================================


# ---------------------------------------------------------------------------
# GET /
# ---------------------------------------------------------------------------
@require_GET
def index(request):
    response = render(request, "index.html", {
        "app_name": settings.app_name,
        "symbols": settings.tracked_symbols,
        "static_assets_version": static_assets_version,
    })
    for header, value in no_cache_headers().items():
        response[header] = value
    return response


# ---------------------------------------------------------------------------
# GET /api/dashboard
# ---------------------------------------------------------------------------
@require_GET
def dashboard(request):
    # Only the worker that owns the scheduler lock should attempt to wake the scheduler.
    # Other workers must NOT call ensure_running(), otherwise multiple cycles run in parallel.
    from app.startup import _scheduler_lock_handle
    if _scheduler_lock_handle is not None:
        scheduler_service.ensure_running()
    current_user = resolve_request_user(request)
    payload = _build_dashboard_payload(current_user=current_user)
    return _apply_no_cache(JsonResponse(payload))


# ---------------------------------------------------------------------------
# GET /api/chart-package
# ---------------------------------------------------------------------------
@require_GET
def chart_package(request):
    symbol = request.GET.get("symbol", "")
    limit_raw = request.GET.get("limit", "120")
    try:
        limit = min(max(int(limit_raw), 10), 300)
    except (ValueError, TypeError):
        limit = 120
    if symbol not in settings.tracked_symbols:
        return JsonResponse({"detail": f"Nieznany symbol: {symbol}"}, status=404)
    payload = learning_center.build_chart_package(symbol, limit=limit)
    if payload is None:
        return JsonResponse({"detail": f"Brak danych wykresu dla {symbol}"}, status=404)
    return _apply_no_cache(JsonResponse(payload))


# ---------------------------------------------------------------------------
# POST /api/run-cycle
# ---------------------------------------------------------------------------
@csrf_exempt
@require_POST
def run_cycle(request):
    run_result = cycle_runner.run()
    dashboard_payload = _build_dashboard_payload()
    return JsonResponse({"run": run_result, "dashboard": dashboard_payload})


# ---------------------------------------------------------------------------
# GET /api/backtest
# ---------------------------------------------------------------------------
@require_GET
def backtest(request):
    force_refresh = request.GET.get("force_refresh", "").lower() in ("1", "true")
    payload = backtest_service.get_rankings(force_refresh=force_refresh)
    return JsonResponse(payload)


# ---------------------------------------------------------------------------
# POST /api/scheduler/start
# ---------------------------------------------------------------------------
@csrf_exempt
@require_POST
def scheduler_start(request):
    from app.startup import _scheduler_lock_handle
    if _scheduler_lock_handle is None:
        # This worker does not own the scheduler. Tell the user a sibling worker is in charge.
        return JsonResponse({
            **scheduler_service.status(),
            "note": "Scheduler dziala w innym workerze — odswiez strone i sproboj ponownie.",
        })
    scheduler_service.start()
    return JsonResponse(scheduler_service.status())


# ---------------------------------------------------------------------------
# POST /api/scheduler/stop
# ---------------------------------------------------------------------------
@csrf_exempt
@require_POST
def scheduler_stop(request):
    from app.startup import _scheduler_lock_handle
    if _scheduler_lock_handle is None:
        return JsonResponse({
            **scheduler_service.status(),
            "note": "Scheduler dziala w innym workerze — odswiez strone i sproboj ponownie.",
        })
    scheduler_service.stop()
    return JsonResponse(scheduler_service.status())


# ---------------------------------------------------------------------------
# GET /api/ai-insight
# ---------------------------------------------------------------------------
@require_GET
def ai_insight(request):
    symbol = request.GET.get("symbol")
    current_user = resolve_request_user(request)
    dashboard_payload = _build_dashboard_payload(
        include_chart_package=True,
        chart_focus_symbol=symbol,
        current_user=current_user,
    )
    result = ai_advisor.generate_market_brief(dashboard_payload, symbol=symbol)
    return JsonResponse(result)


# ---------------------------------------------------------------------------
# POST /api/agent-chat
# ---------------------------------------------------------------------------
@csrf_exempt
@require_POST
@ratelimit(key="ip", rate="15/m")
def agent_chat(request):
    body, err = _parse_json_body(request)
    if err:
        return err
    message = str(body.get("message", "")).strip()
    if not message or len(message) > 2000:
        return JsonResponse({"detail": "message: wymagany, 1-2000 znaków"}, status=400)
    history = body.get("history", [])
    if not isinstance(history, list):
        history = []

    current_user = resolve_request_user(request)
    dashboard_payload = _build_dashboard_payload(
        include_chart_package=True,
        current_user=current_user,
        skip_exchange_api=True,
    )
    result = ai_advisor.chat(
        user_message=message,
        dashboard=dashboard_payload,
        conversation_history=history,
        current_user=current_user,
    )
    return JsonResponse(result)


# ---------------------------------------------------------------------------
# POST /api/agent-chat/execute
# ---------------------------------------------------------------------------
@csrf_exempt
@require_POST
@ratelimit(key="ip", rate="10/m")
def agent_chat_execute(request):
    user, err = _require_auth(request)
    if err:
        return err
    body, err = _parse_json_body(request)
    if err:
        return err

    action = str(body.get("action", ""))
    symbol = str(body.get("symbol", ""))
    if not _ACTION_RE.match(action):
        return JsonResponse({"detail": "action musi byc BUY lub SELL"}, status=400)
    if not symbol or len(symbol) < 2 or len(symbol) > 10 or not _SYMBOL_RE.match(symbol):
        return JsonResponse({"detail": "Nieprawidlowy symbol"}, status=400)

    db_user = User.objects.filter(pk=user.id).first()
    if db_user is None or db_user.trading_mode != "LIVE":
        return JsonResponse({"ok": False, "error": "Musisz byc w trybie LIVE aby wykonywac zlecenia."}, status=400)

    selected_key, client = get_user_binance_client(user.id)
    if client is None:
        return JsonResponse({"ok": False, "error": "Brak klucza API Binance."}, status=400)

    from app.services.agent_cycle import _BRIDGE_QUOTES, _MIN_ORDER

    if action == "BUY":
        balances = client.get_balances()
        tradeable = client.get_tradeable_pairs()
        available_quotes = tradeable.get(symbol, [])
        detail = "Brak odpowiedniej pary lub srodkow"

        for quote in _BRIDGE_QUOTES:
            if quote not in available_quotes:
                continue
            pair = f"{symbol}{quote}"
            bal = next((b for b in balances if b["asset"] == quote), None)
            if not bal:
                continue
            available = bal["free"]
            min_ord = _MIN_ORDER.get(quote, 10.0)
            if available < min_ord:
                continue

            alloc_mode = getattr(db_user, "live_alloc_mode", "percent") or "percent"
            alloc_value = getattr(db_user, "live_alloc_value", 10.0) or 10.0
            if alloc_mode == "percent":
                alloc = available * (alloc_value / 100.0)
            elif alloc_mode == "fixed":
                alloc = min(alloc_value, available)
            else:
                alloc = available
            alloc = max(alloc, min_ord)
            if alloc > available:
                continue

            result = client.create_order(symbol=pair, side="BUY", order_type="MARKET", quote_quantity=round(alloc, 6))
            if isinstance(result, dict) and "error" not in result:
                from app.services.binance_api import extract_commission
                comm, comm_asset = extract_commission(result)
                LiveOrderLog.objects.create(
                    username=user.username, symbol=symbol, action="BUY", status="ok",
                    detail=f"Czat: kupiono za {round(alloc, 2)} {quote}",
                    order_id=str(result.get("orderId", "")), allocation=round(alloc, 4), quote_currency=quote,
                    commission=comm, commission_asset=comm_asset,
                )
                return JsonResponse({"ok": True, "detail": f"Kupiono {symbol} za {round(alloc, 2)} {quote}", "order": result})
            else:
                detail = result.get("error", "Blad zlecenia") if isinstance(result, dict) else str(result)

        LiveOrderLog.objects.create(
            username=user.username, symbol=symbol, action="BUY", status="error",
            detail=f"Czat: {detail}", allocation=0, quote_currency="",
        )
        return JsonResponse({"ok": False, "error": detail}, status=400)

    elif action == "SELL":
        balances = client.get_balances()
        tradeable = client.get_tradeable_pairs()
        available_quotes = tradeable.get(symbol, [])
        held = next((b for b in balances if b["asset"] == symbol), None)
        if not held or held["free"] <= 0:
            return JsonResponse({"ok": False, "error": f"Nie posiadasz {symbol} do sprzedazy."}, status=400)

        spot_free = client.get_spot_free(symbol)
        total_free = held["free"]
        earn_redeemed = False

        if spot_free < total_free * 0.5:
            earn_pos = client.get_earn_flexible_position(symbol)
            if earn_pos:
                product_id = earn_pos.get("productId", "")
                if product_id:
                    redeem_result = client.redeem_earn_flexible(product_id, redeem_all=True)
                    if isinstance(redeem_result, dict) and "error" not in redeem_result:
                        earn_redeemed = True
                        _time.sleep(2)
                        spot_free = client.get_spot_free(symbol)
                    else:
                        err_msg = redeem_result.get("error", str(redeem_result)) if isinstance(redeem_result, dict) else str(redeem_result)
                        logger.warning("Earn redeem failed for %s: %s", symbol, err_msg)

        qty = spot_free
        if qty <= 0:
            return JsonResponse({"ok": False, "error": f"Saldo spot {symbol} = 0. Tokeny moga byc zablokowane w Earn/Staking."}, status=400)

        exchange_info = client.get_exchange_info()
        symbols_info = {}
        if isinstance(exchange_info, dict) and "error" not in exchange_info:
            symbols_info = {s["symbol"]: s for s in exchange_info.get("symbols", [])}

        for quote in _BRIDGE_QUOTES:
            if quote not in available_quotes:
                continue
            pair = f"{symbol}{quote}"
            sym_info = symbols_info.get(pair, {})
            filters = sym_info.get("filters", [])
            lot_filter = next((f for f in filters if f["filterType"] == "LOT_SIZE"), None)
            if lot_filter:
                step = float(lot_filter["stepSize"])
                min_qty = float(lot_filter.get("minQty", 0))
                if step > 0:
                    qty_floored = math.floor(qty / step) * step
                    step_str = f"{step:.10f}".rstrip("0")
                    decimals = len(step_str.split(".")[-1]) if "." in step_str else 0
                    qty_floored = round(qty_floored, decimals)
                else:
                    qty_floored = qty
                if qty_floored < min_qty:
                    continue
            else:
                qty_floored = qty

            if qty_floored <= 0:
                continue

            result = client.create_order(symbol=pair, side="SELL", order_type="MARKET", quantity=round(qty_floored, 8))
            if isinstance(result, dict) and "error" not in result:
                from app.services.binance_api import extract_commission
                comm, comm_asset = extract_commission(result)
                detail_msg = f"Czat: sprzedano {round(qty_floored, 6)} {symbol}"
                if earn_redeemed:
                    detail_msg += " (po odkupieniu z Earn)"
                LiveOrderLog.objects.create(
                    username=user.username, symbol=symbol, action="SELL", status="ok",
                    detail=detail_msg,
                    order_id=str(result.get("orderId", "")), allocation=round(qty_floored, 6), quote_currency=quote,
                    commission=comm, commission_asset=comm_asset,
                )
                return JsonResponse({"ok": True, "detail": f"Sprzedano {round(qty_floored, 6)} {symbol} za {quote}", "order": result})
            else:
                detail = result.get("error", "Blad zlecenia") if isinstance(result, dict) else str(result)
                LiveOrderLog.objects.create(
                    username=user.username, symbol=symbol, action="SELL", status="error",
                    detail=f"Czat: {detail}", allocation=0, quote_currency=quote,
                )
                return JsonResponse({"ok": False, "error": detail}, status=400)

        return JsonResponse({"ok": False, "error": f"Nie znaleziono pary handlowej dla {symbol}."}, status=400)

    return JsonResponse({"ok": False, "error": "Nieznana akcja."}, status=400)


# ---------------------------------------------------------------------------
# POST /api/agent-mode/<mode>
# ---------------------------------------------------------------------------
@csrf_exempt
@require_POST
def set_agent_mode(request, mode: str):
    current_user = resolve_request_user(request)
    normalized = mode.strip().lower()
    if normalized not in settings.agent_mode_profiles:
        return JsonResponse({"detail": f"Nieznany tryb agenta: {mode}"}, status=400)

    if current_user is not None:
        db_user = User.objects.filter(pk=current_user.id).first()
        if db_user is not None:
            db_user.agent_mode = normalized
            db_user.save(update_fields=["agent_mode"])
            current_user = db_user
    else:
        runtime_state.set_agent_mode(normalized)

    payload = _build_dashboard_payload(current_user=current_user)
    return JsonResponse({"mode": normalized, "dashboard": payload})


# ---------------------------------------------------------------------------
# POST /api/paper/reset
# ---------------------------------------------------------------------------
@csrf_exempt
@require_POST
def reset_paper_portfolio(request):
    scheduler_was_enabled = scheduler_service.status().get("enabled", False)
    if scheduler_was_enabled:
        scheduler_service.stop()

    reset_stats = wallet_service.reset_paper_portfolio()
    payload = _build_dashboard_payload()

    return JsonResponse({
        "message": "Portfel paper zostal zresetowany do stanu startowego.",
        "scheduler_stopped": scheduler_was_enabled,
        "reset": reset_stats,
        "dashboard": payload,
    })


# ---------------------------------------------------------------------------
# GET /api/chart-history
# ---------------------------------------------------------------------------
@require_GET
def chart_history(request):
    symbol = request.GET.get("symbol", "")
    force_refresh = request.GET.get("force_refresh", "").lower() in ("1", "true")
    if symbol not in settings.tracked_symbols:
        return JsonResponse({"detail": f"Nieznany symbol: {symbol}"}, status=404)
    payload = learning_center.build_lifecycle_history(symbol, force_refresh=force_refresh)
    return JsonResponse(payload)


# ---------------------------------------------------------------------------
# GET /api/calendar
# ---------------------------------------------------------------------------
@require_GET
def calendar_data(request):
    now = datetime.utcnow()
    try:
        y = int(request.GET["year"]) if "year" in request.GET else now.year
        m = int(request.GET["month"]) if "month" in request.GET else now.month
    except (ValueError, TypeError):
        y, m = now.year, now.month

    first_day = date(y, m, 1)
    if m == 12:
        last_day = date(y + 1, 1, 1) - timedelta(days=1)
    else:
        last_day = date(y, m + 1, 1) - timedelta(days=1)

    start = first_day - timedelta(days=first_day.weekday())
    end = last_day + timedelta(days=6 - last_day.weekday())

    current_user = resolve_request_user(request)

    # --- Live orders ---
    live_qs = LiveOrderLog.objects.filter(
        created_at__gte=datetime.combine(start, datetime.min.time()),
        created_at__lte=datetime.combine(end, datetime.max.time()),
    )
    if current_user is not None:
        live_qs = live_qs.filter(username=current_user.username)
    live_rows = list(live_qs.order_by("created_at"))

    # --- Paper trades (opened in range) ---
    paper_rows = list(
        SimulatedTrade.objects.filter(
            opened_at__gte=datetime.combine(start, datetime.min.time()),
            opened_at__lte=datetime.combine(end, datetime.max.time()),
        ).order_by("opened_at")
    )

    # --- Paper trades closed in range ---
    paper_closed = list(
        SimulatedTrade.objects.filter(
            closed_at__gte=datetime.combine(start, datetime.min.time()),
            closed_at__lte=datetime.combine(end, datetime.max.time()),
            status="CLOSED",
        ).order_by("closed_at")
    )

    # --- Build day map ---
    days: dict[str, dict] = {}
    d = start
    while d <= end:
        days[d.isoformat()] = {
            "date": d.isoformat(),
            "in_month": d.month == m,
            "buys": [],
            "sells": [],
            "live_buys": [],
            "live_sells": [],
            "live_errors": 0,
            "live_skips": 0,
            "paper_profit": 0.0,
            "live_volume": 0.0,
        }
        d += timedelta(days=1)

    # Fill live orders
    for row in live_rows:
        day_key = row.created_at.date().isoformat()
        if day_key not in days:
            continue
        entry = {
            "time": row.created_at.strftime("%H:%M"),
            "symbol": row.symbol,
            "status": row.status,
            "detail": row.detail,
            "allocation": row.allocation,
            "quote": row.quote_currency,
        }
        if row.action == "BUY":
            if row.status == "ok":
                days[day_key]["live_buys"].append(entry)
                days[day_key]["live_volume"] += (row.allocation or 0)
            elif row.status == "error":
                days[day_key]["live_errors"] += 1
            elif row.status == "skip":
                days[day_key]["live_skips"] += 1
        elif row.action == "SELL":
            if row.status == "ok":
                days[day_key]["live_sells"].append(entry)
                days[day_key]["live_volume"] += (row.allocation or 0)
            elif row.status == "error":
                days[day_key]["live_errors"] += 1

    # Fill paper trade opens
    seen_ids: set[int] = set()
    for row in paper_rows:
        day_key = row.opened_at.date().isoformat()
        if day_key not in days:
            continue
        seen_ids.add(row.id)
        entry = {
            "time": row.opened_at.strftime("%H:%M"),
            "symbol": row.symbol,
            "qty": round(row.quantity, 6),
            "price": round(row.buy_price, 2),
            "value": round(row.buy_value, 2),
        }
        days[day_key]["buys"].append(entry)

    # Fill paper trade closes
    for row in paper_closed:
        if row.id in seen_ids and row.closed_at:
            pass
        day_key = row.closed_at.date().isoformat() if row.closed_at else None
        if not day_key or day_key not in days:
            continue
        entry = {
            "time": row.closed_at.strftime("%H:%M"),
            "symbol": row.symbol,
            "qty": round(row.quantity, 6),
            "sell_price": round(row.sell_price, 2) if row.sell_price else 0,
            "profit": round(row.profit, 2) if row.profit else 0,
        }
        days[day_key]["sells"].append(entry)
        days[day_key]["paper_profit"] += (row.profit or 0)

    # --- Summaries ---
    day_list = sorted(days.values(), key=lambda x: x["date"])

    # Weekly summaries
    weeks = defaultdict(lambda: {
        "buys": 0, "sells": 0, "live_buys": 0, "live_sells": 0,
        "paper_profit": 0.0, "live_volume": 0.0, "errors": 0, "skips": 0,
    })
    for dd in day_list:
        dt = date.fromisoformat(dd["date"])
        week_start = (dt - timedelta(days=dt.weekday())).isoformat()
        w = weeks[week_start]
        w["buys"] += len(dd["buys"])
        w["sells"] += len(dd["sells"])
        w["live_buys"] += len(dd["live_buys"])
        w["live_sells"] += len(dd["live_sells"])
        w["paper_profit"] += dd["paper_profit"]
        w["live_volume"] += dd["live_volume"]
        w["errors"] += dd["live_errors"]
        w["skips"] += dd["live_skips"]

    # Monthly summary
    month_summary = {
        "buys": 0, "sells": 0, "live_buys": 0, "live_sells": 0,
        "paper_profit": 0.0, "live_volume": 0.0, "errors": 0, "skips": 0, "active_days": 0,
    }
    for dd in day_list:
        if not dd["in_month"]:
            continue
        has_activity = len(dd["buys"]) + len(dd["sells"]) + len(dd["live_buys"]) + len(dd["live_sells"]) > 0
        month_summary["buys"] += len(dd["buys"])
        month_summary["sells"] += len(dd["sells"])
        month_summary["live_buys"] += len(dd["live_buys"])
        month_summary["live_sells"] += len(dd["live_sells"])
        month_summary["paper_profit"] += dd["paper_profit"]
        month_summary["live_volume"] += dd["live_volume"]
        month_summary["errors"] += dd["live_errors"]
        month_summary["skips"] += dd["live_skips"]
        if has_activity:
            month_summary["active_days"] += 1
    month_summary["paper_profit"] = round(month_summary["paper_profit"], 2)
    month_summary["live_volume"] = round(month_summary["live_volume"], 4)

    # Year summary
    year_live_agg = LiveOrderLog.objects.filter(
        created_at__gte=datetime(y, 1, 1),
        created_at__lt=datetime(y + 1, 1, 1),
        status="ok",
    ).aggregate(
        count=Count("id"),
        total_allocation=Coalesce(Sum("allocation"), 0.0),
    )
    year_paper_agg = SimulatedTrade.objects.filter(
        closed_at__gte=datetime(y, 1, 1),
        closed_at__lt=datetime(y + 1, 1, 1),
        status="CLOSED",
    ).aggregate(
        count=Count("id"),
        total_profit=Coalesce(Sum("profit"), 0.0),
    )
    year_summary = {
        "live_trades": int(year_live_agg["count"] or 0),
        "live_volume": round(float(year_live_agg["total_allocation"] or 0), 2),
        "paper_closed": int(year_paper_agg["count"] or 0),
        "paper_profit": round(float(year_paper_agg["total_profit"] or 0), 2),
    }

    for dd in day_list:
        dd["paper_profit"] = round(dd["paper_profit"], 2)
        dd["live_volume"] = round(dd["live_volume"], 4)

    return _apply_no_cache(JsonResponse({
        "year": y,
        "month": m,
        "days": day_list,
        "weeks": {k: dict(v) for k, v in weeks.items()},
        "month_summary": month_summary,
        "year_summary": year_summary,
    }))


# ===================================================================
# AUTH ENDPOINTS
# ===================================================================


# ---------------------------------------------------------------------------
# POST /api/auth/register
# ---------------------------------------------------------------------------
@csrf_exempt
@require_POST
@ratelimit(key="ip", rate="5/m")
def register(request):
    body, err = _parse_json_body(request)
    if err:
        return err

    email = str(body.get("email", "")).strip()
    username = str(body.get("username", "")).strip()
    password = str(body.get("password", ""))

    if not email or not _EMAIL_RE.match(email):
        return JsonResponse({"detail": "Nieprawidlowy adres email"}, status=400)
    if len(username) < 3 or len(username) > 32 or not _USERNAME_RE.match(username):
        return JsonResponse({"detail": "Username: 3-32 znaków, litery/cyfry/_/-"}, status=400)
    if len(password) < 8 or len(password) > 128:
        return JsonResponse({"detail": "Hasło: 8-128 znaków"}, status=400)

    ip = _get_client_ip(request)
    success, message, user = auth_service.register(
        email=email,
        username=username,
        password=password,
        ip_address=ip,
    )
    if not success or user is None:
        return JsonResponse({"detail": message}, status=400)

    login_success, login_message, token = auth_service.login(
        email_or_username=email,
        password=password,
        ip_address=ip,
        user_agent=request.META.get("HTTP_USER_AGENT"),
    )
    if not login_success or token is None:
        return JsonResponse({"detail": login_message}, status=400)

    response = JsonResponse({"success": True, "user": serialize_user(user)})
    _set_session_cookie(response, token)
    return response


# ---------------------------------------------------------------------------
# POST /api/auth/login
# ---------------------------------------------------------------------------
@csrf_exempt
@require_POST
@ratelimit(key="ip", rate="5/m")
def login_view(request):
    body, err = _parse_json_body(request)
    if err:
        return err

    email = str(body.get("email", "")).strip()
    password = str(body.get("password", ""))

    if not email or not _EMAIL_RE.match(email):
        return JsonResponse({"detail": "Nieprawidlowy adres email"}, status=400)
    if not password or len(password) > 128:
        return JsonResponse({"detail": "Nieprawidlowe haslo"}, status=400)

    ip = _get_client_ip(request)
    success, message, token = auth_service.login(
        email_or_username=email,
        password=password,
        ip_address=ip,
        user_agent=request.META.get("HTTP_USER_AGENT"),
    )
    if not success or token is None:
        return JsonResponse({"detail": message}, status=401)

    user = auth_service.validate_token(token)
    if user is None:
        return JsonResponse({"detail": "Nie udalo sie odczytac sesji uzytkownika"}, status=401)

    response = JsonResponse({"success": True, "user": serialize_user(user)})
    _set_session_cookie(response, token)
    return response


# ---------------------------------------------------------------------------
# POST /api/auth/logout
# ---------------------------------------------------------------------------
@csrf_exempt
@require_POST
def logout_view(request):
    session_token = request.COOKIES.get("session_token")
    if session_token:
        auth_service.logout(session_token)
    response = JsonResponse({"success": True})
    response.delete_cookie(key="session_token")
    return response


# ---------------------------------------------------------------------------
# GET /api/auth/me
# ---------------------------------------------------------------------------
@require_GET
def get_me(request):
    session_token = request.COOKIES.get("session_token")
    if not session_token:
        return JsonResponse({"authenticated": False, "user": None})
    user = auth_service.validate_token(session_token)
    if not user:
        return JsonResponse({"authenticated": False, "user": None})
    return JsonResponse({"authenticated": True, "user": serialize_user(user)})


# ---------------------------------------------------------------------------
# POST /api/user/trading-mode
# ---------------------------------------------------------------------------
@csrf_exempt
@require_POST
def set_trading_mode(request):
    user, err = _require_auth(request)
    if err:
        return err

    body, err = _parse_json_body(request)
    if err:
        return err

    mode = str(body.get("mode", "PAPER")).upper()
    if mode not in ("PAPER", "LIVE"):
        return JsonResponse({"ok": False, "error": "Tryb musi byc PAPER lub LIVE"}, status=400)

    ip = _get_client_ip(request)

    if mode == "LIVE":
        keys = api_key_service.get_user_api_keys(user.id)
        trade_key = next(
            (k for k in keys if k.is_active and not k.is_testnet),
            None,
        )
        if trade_key is None:
            return JsonResponse(
                {"ok": False, "error": "Brak klucza API Binance. Dodaj klucz w Ustawieniach."},
                status=400,
            )
        api_secret = api_key_service.get_decrypted_secret(trade_key)
        if api_secret:
            client = binance_service.get_client(trade_key.api_key, api_secret, trade_key.is_testnet)
            account = client.get_account()
            if isinstance(account, dict) and account.get("canTrade"):
                trade_key.permissions = "trade"
                trade_key.save(update_fields=["permissions"])
            else:
                return JsonResponse(
                    {"ok": False, "error": "Klucz API nie ma uprawnien do handlu. Wlacz 'Handel Spot' na Binance."},
                    status=400,
                )

    db_user = User.objects.filter(pk=user.id).first()
    if db_user is None:
        return JsonResponse({"ok": False, "error": "Nie znaleziono uzytkownika"}, status=404)

    db_user.trading_mode = mode
    db_user.save(update_fields=["trading_mode"])
    AuditLog.objects.create(user_id=user.id, action="trading_mode_changed", resource=mode, ip_address=ip)

    return JsonResponse({"ok": True, "trading_mode": mode})


# ---------------------------------------------------------------------------
# POST /api/user/live-allocation
# ---------------------------------------------------------------------------
@csrf_exempt
@require_POST
def set_live_allocation(request):
    user, err = _require_auth(request)
    if err:
        return err

    body, err = _parse_json_body(request)
    if err:
        return err

    mode = str(body.get("mode", "percent")).lower()
    try:
        value = float(body.get("value", 10.0))
    except (ValueError, TypeError):
        return JsonResponse({"ok": False, "error": "Nieprawidlowa wartosc"}, status=400)

    if mode not in ("percent", "fixed", "max"):
        return JsonResponse({"ok": False, "error": "Tryb musi byc: percent, fixed lub max"}, status=400)
    if mode == "percent" and (value < 1 or value > 100):
        return JsonResponse({"ok": False, "error": "Procent musi byc od 1 do 100"}, status=400)
    if mode == "fixed" and value < 1:
        return JsonResponse({"ok": False, "error": "Kwota musi byc wieksza niz 0"}, status=400)

    db_user = User.objects.filter(pk=user.id).first()
    if db_user is None:
        return JsonResponse({"ok": False, "error": "Nie znaleziono uzytkownika"}, status=404)

    db_user.live_alloc_mode = mode
    db_user.live_alloc_value = value
    db_user.save(update_fields=["live_alloc_mode", "live_alloc_value"])

    return JsonResponse({"ok": True, "live_alloc_mode": mode, "live_alloc_value": value})


# ===================================================================
# API KEY MANAGEMENT
# ===================================================================


# ---------------------------------------------------------------------------
# GET /api/keys
# ---------------------------------------------------------------------------
@require_GET
def list_api_keys(request):
    user, err = _require_auth(request)
    if err:
        return err

    keys = api_key_service.get_user_api_keys(user.id)
    return JsonResponse({
        "keys": [
            {
                "id": key.id,
                "label": key.label,
                "exchange": key.exchange,
                "api_key": key.api_key[:8] + "..." + key.api_key[-4:] if len(key.api_key) > 12 else "***",
                "is_testnet": key.is_testnet,
                "permissions": key.permissions,
                "created_at": key.created_at.isoformat() if key.created_at else None,
            }
            for key in keys
        ]
    })


# ---------------------------------------------------------------------------
# POST /api/keys
# ---------------------------------------------------------------------------
@csrf_exempt
@require_POST
@ratelimit(key="ip", rate="10/m")
def add_api_key(request):
    user, err = _require_auth(request)
    if err:
        return err

    body, err = _parse_json_body(request)
    if err:
        return err

    label = body.get("label")
    exchange = str(body.get("exchange", "binance")).strip().lower()
    api_key_val = str(body.get("api_key", "")).strip()
    api_secret_val = str(body.get("api_secret", "")).strip()
    is_testnet = bool(body.get("is_testnet", False))
    permissions = str(body.get("permissions", "read")).strip().lower()

    if not _EXCHANGE_RE.match(exchange):
        return JsonResponse({"detail": "exchange: tylko male litery"}, status=400)
    if len(api_key_val) < 10 or len(api_key_val) > 128 or not _ALPHANUMERIC_RE.match(api_key_val):
        return JsonResponse({"detail": "api_key: 10-128 znaków alfanumerycznych"}, status=400)
    if len(api_secret_val) < 10 or len(api_secret_val) > 256 or not _ALPHANUMERIC_RE.match(api_secret_val):
        return JsonResponse({"detail": "api_secret: 10-256 znaków alfanumerycznych"}, status=400)
    if not _PERMISSIONS_RE.match(permissions):
        return JsonResponse({"detail": "permissions: read lub trade"}, status=400)
    if label is not None and len(str(label)) > 64:
        return JsonResponse({"detail": "label: max 64 znaki"}, status=400)

    ip = _get_client_ip(request)
    final_label = str(label).strip() if label is not None else f"{exchange.upper()} {api_key_val[:4]}"
    if not final_label:
        final_label = f"{exchange.upper()} {api_key_val[:4]}"

    success, message, api_key_obj = api_key_service.add_api_key(
        user_id=user.id,
        label=final_label,
        exchange=exchange,
        api_key=api_key_val,
        api_secret=api_secret_val,
        is_testnet=is_testnet,
        permissions=permissions,
        ip_address=ip,
    )
    if not success or api_key_obj is None:
        return JsonResponse({"detail": message}, status=400)
    return JsonResponse({"success": True, "key_id": api_key_obj.id})


# ---------------------------------------------------------------------------
# DELETE /api/keys/<key_id>
# ---------------------------------------------------------------------------
@csrf_exempt
@require_http_methods(["DELETE"])
def delete_api_key(request, key_id: int):
    user, err = _require_auth(request)
    if err:
        return err

    deleted = api_key_service.delete_api_key(user_id=user.id, key_id=key_id)
    if not deleted:
        return JsonResponse({"detail": "Klucz API nie znaleziony"}, status=404)
    return JsonResponse({"success": True})


# ===================================================================
# BINANCE API ENDPOINTS
# ===================================================================


# ---------------------------------------------------------------------------
# GET /api/binance/test
# ---------------------------------------------------------------------------
@require_GET
def test_binance_connection(request):
    user, err = _require_auth(request)
    if err:
        return err
    try:
        key_id = int(request.GET["key_id"])
    except (KeyError, ValueError, TypeError):
        return JsonResponse({"detail": "Wymagany parametr key_id"}, status=400)

    selected_key, client = get_user_binance_client(user.id, key_id)
    if selected_key is None:
        return JsonResponse({"detail": "Klucz API nie znaleziony"}, status=404)
    if client is None:
        return JsonResponse({"detail": "Błąd odszyfrowywania klucza"}, status=500)

    success, message = client.test_connection()
    if not success:
        msg_lower = message.lower()
        if "-1022" in message or "signature for this request is not valid" in msg_lower:
            message = "Błąd API Binance (-1022): nieprawidłowy secret dla podanego API key (sprawdź też zbędne spacje/nowe linie)."
        elif "-2015" in message or "invalid api-key, ip, or permissions" in msg_lower:
            mode = "testnet" if selected_key.is_testnet else "mainnet"
            message = f"Błąd API Binance (-2015): nieprawidłowy klucz/IP/uprawnienia dla trybu {mode}."
    return JsonResponse({
        "success": success,
        "message": message,
        "key_label": selected_key.label,
        "is_testnet": selected_key.is_testnet,
    })


# ---------------------------------------------------------------------------
# GET /api/binance/account
# ---------------------------------------------------------------------------
@require_GET
def get_binance_account(request):
    user, err = _require_auth(request)
    if err:
        return err
    try:
        key_id = int(request.GET["key_id"])
    except (KeyError, ValueError, TypeError):
        return JsonResponse({"detail": "Wymagany parametr key_id"}, status=400)

    selected_key, client = get_user_binance_client(user.id, key_id)
    if selected_key is None:
        return JsonResponse({"detail": "Klucz API nie znaleziony"}, status=404)
    if client is None:
        return JsonResponse({"detail": "Błąd odszyfrowywania klucza"}, status=500)

    result = client.get_account()
    if "error" in result:
        logger.warning("Binance account error for user %s: %s", user.id, result["error"])
        return JsonResponse({"detail": "Nie udało się pobrać danych konta. Sprawdź klucz API."}, status=400)
    return JsonResponse(result)


# ---------------------------------------------------------------------------
# GET /api/binance/balances
# ---------------------------------------------------------------------------
@require_GET
def get_binance_balances(request):
    user, err = _require_auth(request)
    if err:
        return err
    try:
        key_id = int(request.GET["key_id"])
    except (KeyError, ValueError, TypeError):
        return JsonResponse({"detail": "Wymagany parametr key_id"}, status=400)

    selected_key, client = get_user_binance_client(user.id, key_id)
    if selected_key is None:
        return JsonResponse({"detail": "Klucz API nie znaleziony"}, status=404)
    if client is None:
        return JsonResponse({"detail": "Błąd odszyfrowywania klucza"}, status=500)

    balances = client.get_balances()
    if balances and isinstance(balances[0], dict) and "error" in balances[0]:
        logger.warning("Binance balances error for user %s: %s", user.id, balances[0]["error"])
        return JsonResponse({"detail": "Nie udało się pobrać sald. Sprawdź klucz API."}, status=400)
    return JsonResponse({"balances": balances})


# ---------------------------------------------------------------------------
# GET /api/binance/portfolio
# ---------------------------------------------------------------------------
@require_GET
def get_binance_portfolio(request):
    user, err = _require_auth(request)
    if err:
        return err
    try:
        key_id = int(request.GET["key_id"])
    except (KeyError, ValueError, TypeError):
        return JsonResponse({"detail": "Wymagany parametr key_id"}, status=400)

    selected_key, client = get_user_binance_client(user.id, key_id)
    if selected_key is None:
        return JsonResponse({"detail": "Klucz API nie znaleziony"}, status=404)
    if client is None:
        return JsonResponse({"detail": "Błąd odszyfrowywania klucza"}, status=500)

    portfolio = client.get_portfolio_value()
    if "error" in portfolio:
        logger.warning("Binance portfolio error for user %s: %s", user.id, portfolio["error"])
        return JsonResponse({"detail": "Nie udało się pobrać portfela. Sprawdź klucz API."}, status=400)

    return JsonResponse({
        "total_value_usdt": portfolio["total_value"],
        "quote_currency": portfolio["quote_currency"],
        "holdings": portfolio["holdings"],
    })


# ---------------------------------------------------------------------------
# GET /api/binance/leverage-check
# ---------------------------------------------------------------------------
@require_GET
def check_leverage(request):
    user, err = _require_auth(request)
    if err:
        return err

    _, client = get_user_binance_client(user.id)
    if client is None:
        return JsonResponse({
            "leverage_available": False,
            "reason": "Brak klucza API Binance. Dodaj klucz w Ustawieniach.",
        })
    result = client.check_margin_available()
    return JsonResponse(result)


# ---------------------------------------------------------------------------
# GET /api/binance/dust
# ---------------------------------------------------------------------------
@require_GET
def get_dust_assets(request):
    user, err = _require_auth(request)
    if err:
        return err

    _, client = get_user_binance_client(user.id)
    if client is None:
        return JsonResponse({"error": "Brak klucza API Binance."}, status=400)
    assets = client.get_dust_assets()
    return JsonResponse({"assets": assets})


# ---------------------------------------------------------------------------
# POST /api/binance/dust/convert
# ---------------------------------------------------------------------------
@csrf_exempt
@require_POST
@ratelimit(key="ip", rate="5/m")
def convert_dust(request):
    user, err = _require_auth(request)
    if err:
        return err

    _, client = get_user_binance_client(user.id)
    if client is None:
        return JsonResponse({"error": "Brak klucza API Binance."}, status=400)
    dust_list = client.get_dust_assets()
    if not dust_list:
        return JsonResponse({"error": "Brak malych kwot do konwersji."}, status=400)
    asset_names = [d["asset"] for d in dust_list]
    result = client.convert_dust_to_bnb(asset_names)
    if isinstance(result, dict) and "error" in result:
        return JsonResponse({"error": result["error"]}, status=400)
    transferred = result.get("totalTransfered", result.get("totalTransferred", 0))
    transfer_results = result.get("transferResult", [])
    return JsonResponse({
        "ok": True,
        "total_bnb": float(transferred),
        "converted_count": len(transfer_results),
        "details": transfer_results,
    })


# ===================================================================
# LEVERAGE PAPER TRADING
# ===================================================================


# ---------------------------------------------------------------------------
# GET /api/leverage/snapshot
# ---------------------------------------------------------------------------
@require_GET
def leverage_snapshot_api(request):
    return JsonResponse(leverage_engine.get_snapshot())


# ---------------------------------------------------------------------------
# GET /api/leverage/perp/<symbol>
# ---------------------------------------------------------------------------
@require_GET
def leverage_perp_data(request, symbol: str):
    from app.services.bybit_market import get_perp_snapshot
    data = get_perp_snapshot(symbol.upper())
    if data is None:
        return JsonResponse({"detail": f"Brak danych perpetual dla {symbol}"}, status=404)
    return JsonResponse(data)


# ---------------------------------------------------------------------------
# GET /api/leverage/chart/<symbol>
# ---------------------------------------------------------------------------
@require_GET
def leverage_chart_api(request, symbol: str):
    from app.services.bybit_market import get_perp_klines, get_perp_ticker, get_funding_history

    sym = symbol.upper()
    interval = request.GET.get("interval", "60")
    try:
        limit = min(int(request.GET.get("limit", "200")), 200)
    except (ValueError, TypeError):
        limit = 200

    klines = get_perp_klines(sym, interval=interval, limit=limit)
    if not klines:
        return JsonResponse({"detail": f"Brak danych klines dla {sym}"}, status=404)

    ticker = get_perp_ticker(sym) or {}
    funding = get_funding_history(sym, limit=50)

    # Leverage trade markers from DB (Django ORM)
    trades = list(
        LeverageSimTrade.objects.filter(symbol=sym).order_by("-opened_at")[:50]
    )
    markers = []
    for t in trades:
        markers.append({
            "time": int(t.opened_at.timestamp()),
            "type": "entry",
            "side": t.side,
            "leverage": t.leverage,
            "price": t.entry_price,
            "score": t.decision_score,
            "reason": (t.decision_reason or "")[:120],
        })
        if t.closed_at and t.exit_price:
            markers.append({
                "time": int(t.closed_at.timestamp()),
                "type": "exit",
                "side": t.side,
                "leverage": t.leverage,
                "price": t.exit_price,
                "pnl": t.pnl,
                "pnl_pct": t.pnl_pct,
                "reason": t.close_reason or "",
                "status": t.status,
            })

    open_positions = list(
        LeverageSimTrade.objects.filter(symbol=sym, status="OPEN")
    )
    positions = [{
        "side": p.side,
        "entry_price": p.entry_price,
        "liquidation_price": p.liquidation_price,
        "take_profit": p.take_profit,
        "stop_loss": p.stop_loss,
        "leverage": p.leverage,
        "margin_used": p.margin_used,
    } for p in open_positions]

    return JsonResponse({
        "symbol": sym,
        "interval": interval,
        "klines": klines,
        "markers": sorted(markers, key=lambda m: m["time"]),
        "positions": positions,
        "funding_rate": ticker.get("funding_rate", 0),
        "funding_rate_pct": ticker.get("funding_rate_pct", 0),
        "mark_price": ticker.get("mark_price", 0),
        "index_price": ticker.get("index_price", 0),
        "funding_history": funding,
    })


# ===================================================================
# BYBIT API ENDPOINTS
# ===================================================================


# ---------------------------------------------------------------------------
# GET /api/bybit/test
# ---------------------------------------------------------------------------
@require_GET
def test_bybit_connection(request):
    user, err = _require_auth(request)
    if err:
        return err
    try:
        key_id = int(request.GET["key_id"])
    except (KeyError, ValueError, TypeError):
        return JsonResponse({"detail": "Wymagany parametr key_id"}, status=400)

    selected_key, client = get_user_bybit_client(user.id, key_id)
    if selected_key is None:
        return JsonResponse({"detail": "Klucz API Bybit nie znaleziony"}, status=404)
    if client is None:
        return JsonResponse({"detail": "Błąd odszyfrowywania klucza"}, status=500)

    success, message = client.test_connection()
    return JsonResponse({
        "success": success,
        "message": message,
        "key_label": selected_key.label,
        "is_testnet": selected_key.is_testnet,
    })


# ---------------------------------------------------------------------------
# GET /api/bybit/portfolio
# ---------------------------------------------------------------------------
@require_GET
def get_bybit_portfolio(request):
    user, err = _require_auth(request)
    if err:
        return err
    try:
        key_id = int(request.GET["key_id"])
    except (KeyError, ValueError, TypeError):
        return JsonResponse({"detail": "Wymagany parametr key_id"}, status=400)

    selected_key, client = get_user_bybit_client(user.id, key_id)
    if selected_key is None:
        return JsonResponse({"detail": "Klucz API Bybit nie znaleziony"}, status=404)
    if client is None:
        return JsonResponse({"detail": "Błąd odszyfrowywania klucza"}, status=500)

    portfolio = client.get_portfolio_value()
    if "error" in portfolio:
        logger.warning("Bybit portfolio error for user %s: %s", user.id, portfolio["error"])
        return JsonResponse({"detail": "Nie udało się pobrać portfela Bybit."}, status=400)
    return JsonResponse(portfolio)


# ---------------------------------------------------------------------------
# GET /api/bybit/positions
# ---------------------------------------------------------------------------
@require_GET
def get_bybit_positions(request):
    user, err = _require_auth(request)
    if err:
        return err

    _, client = get_user_bybit_client(user.id)
    if client is None:
        return JsonResponse({"positions": []})
    positions = client.get_open_positions_summary()
    return JsonResponse({"positions": positions})


# ---------------------------------------------------------------------------
# GET /api/bybit/leverage/<symbol>
# ---------------------------------------------------------------------------
@require_GET
def get_bybit_leverage_info(request, symbol: str):
    user, err = _require_auth(request)
    if err:
        return err

    _, client = get_user_bybit_client(user.id)
    if client is None:
        return JsonResponse({"detail": "Brak klucza API Bybit."}, status=400)
    info = client.get_leverage_info(symbol)
    if "error" in info:
        return JsonResponse({"detail": info["error"]}, status=400)
    return JsonResponse(info)


# ---------------------------------------------------------------------------
# POST /api/bybit/leverage/<symbol>
# ---------------------------------------------------------------------------
@csrf_exempt
@require_POST
@ratelimit(key="ip", rate="10/m")
def set_bybit_leverage(request, symbol: str):
    user, err = _require_auth(request)
    if err:
        return err

    body, err = _parse_json_body(request)
    if err:
        return err
    leverage = str(body.get("leverage", "1"))

    _, client = get_user_bybit_client(user.id)
    if client is None:
        return JsonResponse({"detail": "Brak klucza API Bybit."}, status=400)
    result = client.set_leverage(symbol, leverage, leverage)
    if "error" in result:
        return JsonResponse({"detail": result["error"]}, status=400)
    return JsonResponse({"success": True, "symbol": symbol, "leverage": leverage})


# ---------------------------------------------------------------------------
# POST /api/bybit/trade
# ---------------------------------------------------------------------------
@csrf_exempt
@require_POST
@ratelimit(key="ip", rate="10/m")
def place_bybit_trade(request):
    user, err = _require_auth(request)
    if err:
        return err

    body, err = _parse_json_body(request)
    if err:
        return err

    symbol = body.get("symbol")
    side = body.get("side")
    order_type = body.get("order_type", "Market")
    qty = str(body.get("qty", "0"))
    category = body.get("category", "linear")
    price = body.get("price")
    leverage = body.get("leverage")
    take_profit = body.get("take_profit")
    stop_loss = body.get("stop_loss")
    reduce_only = body.get("reduce_only", False)

    if not symbol or not side or float(qty) <= 0:
        return JsonResponse({"detail": "Brak wymaganych pól: symbol, side, qty"}, status=400)

    _, client = get_user_bybit_client(user.id)
    if client is None:
        return JsonResponse({"detail": "Brak klucza API Bybit."}, status=400)

    result = client.place_order(
        symbol=symbol,
        side=side,
        order_type=order_type,
        qty=qty,
        category=category,
        price=str(price) if price else None,
        leverage=str(leverage) if leverage else None,
        take_profit=str(take_profit) if take_profit else None,
        stop_loss=str(stop_loss) if stop_loss else None,
        reduce_only=reduce_only,
    )
    if "error" in result:
        return JsonResponse({"detail": result["error"]}, status=400)
    return JsonResponse({"success": True, "order": result})


# ---------------------------------------------------------------------------
# GET /api/bybit/orders
# ---------------------------------------------------------------------------
@require_GET
def get_bybit_orders(request):
    user, err = _require_auth(request)
    if err:
        return err
    category = request.GET.get("category", "linear")

    _, client = get_user_bybit_client(user.id)
    if client is None:
        return JsonResponse({"orders": []})
    orders = client.get_open_orders(category)
    if "error" in orders:
        return JsonResponse({"orders": []})
    return JsonResponse({"orders": orders.get("list", [])})


# ---------------------------------------------------------------------------
# GET /api/bybit/history
# ---------------------------------------------------------------------------
@require_GET
def get_bybit_trade_history(request):
    user, err = _require_auth(request)
    if err:
        return err
    category = request.GET.get("category", "linear")
    try:
        limit = min(int(request.GET.get("limit", "50")), 100)
    except (ValueError, TypeError):
        limit = 50

    _, client = get_user_bybit_client(user.id)
    if client is None:
        return JsonResponse({"history": []})
    history = client.get_trading_history(category, limit)
    return JsonResponse({"history": history})


# ===================================================================
# _build_dashboard_payload
# ===================================================================

def _build_dashboard_payload(
    include_chart_package: bool = False,
    chart_focus_symbol: str | None = None,
    current_user: User | None = None,
    skip_exchange_api: bool = False,
) -> dict[str, object]:
    active_profile = runtime_state.get_active_profile()
    if current_user is not None:
        user_mode = getattr(current_user, "agent_mode", None) or "normal"
        user_profile = settings.agent_mode_profiles.get(user_mode, settings.agent_mode_profiles[settings.default_agent_mode]).copy()
        user_profile["id"] = user_mode
        active_profile = user_profile
    display_currency = runtime_state.get_display_currency()
    usd_to_display_rate, rate_source = currency_service.get_rate(settings.quote_currency, display_currency)
    market_rows: list[dict[str, object]] = []
    chart_packages: dict[str, dict[str, object]] = {}

    # --- Batch queries: latest feature & decision per symbol (Django ORM) ---
    _all_symbols = list(settings.tracked_symbols)

    latest_feature_ids = (
        FeatureSnapshot.objects
        .filter(symbol__in=_all_symbols)
        .values("symbol")
        .annotate(max_id=Max("id"))
        .values_list("max_id", flat=True)
    )
    _features_by_sym: dict[str, FeatureSnapshot] = {
        f.symbol: f
        for f in FeatureSnapshot.objects.filter(id__in=latest_feature_ids)
    }

    latest_decision_ids = (
        Decision.objects
        .filter(symbol__in=_all_symbols)
        .values("symbol")
        .annotate(max_id=Max("id"))
        .values_list("max_id", flat=True)
    )
    _decisions_by_sym: dict[str, Decision] = {
        d.symbol: d
        for d in Decision.objects.filter(id__in=latest_decision_ids)
    }

    # --- Recent whale alerts per symbol (Django ORM) ---
    _whale_cutoff = datetime.utcnow() - timedelta(hours=24)
    _recent_whale_alerts = list(
        WhaleAlert.objects.filter(created_at__gte=_whale_cutoff).order_by("-created_at")
    )
    _whale_by_sym: dict[str, list] = {}
    for wa in _recent_whale_alerts:
        _whale_by_sym.setdefault(wa.symbol, []).append({
            "signal_type": wa.signal_type,
            "whale_score": round(wa.whale_score, 1),
            "vol_zscore": round(wa.vol_zscore, 1),
            "price_change_pct": round(wa.price_change_pct, 1),
            "obv_divergence": wa.obv_divergence,
            "created_at": wa.created_at.isoformat() + "Z",
        })

    # Pre-fetch Bybit perpetual data
    from app.services.bybit_market import get_batch_perp_tickers
    try:
        _perp_data = get_batch_perp_tickers(_all_symbols)
    except Exception:
        _perp_data = {}

    for symbol in settings.tracked_symbols:
        market = load_latest_market_row(symbol)
        feature = _features_by_sym.get(symbol)
        decision = _decisions_by_sym.get(symbol)
        market_summary = learning_center.build_market_summary(symbol)

        if market is None or feature is None or decision is None or market_summary is None:
            continue

        summary = market_summary["summary"]
        live_quote = live_quote_service.get_quote(symbol)
        display_price = float(live_quote["price"]) if live_quote is not None else float(market.close)
        display_source = str(live_quote["source"]) if live_quote is not None else market.source
        display_timestamp = str(live_quote["timestamp"]) if live_quote is not None else market.timestamp.isoformat()
        sym_whale_alerts = _whale_by_sym.get(symbol, [])
        latest_whale = sym_whale_alerts[0] if sym_whale_alerts else None
        perp = _perp_data.get(symbol)
        row = {
            "symbol": symbol,
            "price": round(display_price, 2),
            "volume": round(market.volume, 2),
            "source": display_source,
            "timestamp": display_timestamp,
            "rsi": round(feature.rsi, 2),
            "macd": round(feature.macd, 4),
            "trend": feature.trend,
            "volume_change": round(feature.volume_change * 100, 2),
            "decision": decision.decision,
            "confidence": round(decision.confidence * 100, 1),
            "decision_timestamp": decision.timestamp.isoformat(),
            "reason": decision.reason,
            "change_24h": summary.get("change_24h", 0.0),
            "up_probability": summary.get("up_probability", 50.0),
            "bottom_probability": summary.get("bottom_probability", 50.0),
            "top_probability": summary.get("top_probability", 50.0),
            "reversal_signal": summary.get("reversal_signal", "NEUTRAL"),
            "whale_signal": latest_whale["signal_type"] if latest_whale else "NONE",
            "whale_score": latest_whale["whale_score"] if latest_whale else 0,
            "whale_alerts_24h": len(sym_whale_alerts),
        }
        if perp:
            row["funding_rate"] = perp.get("funding_rate_pct", 0)
            row["funding_signal"] = perp.get("funding_signal", "NEUTRAL")
            row["open_interest"] = perp.get("open_interest_value", 0)
            row["oi_trend"] = perp.get("oi_trend", "UNKNOWN")
            row["oi_change_pct"] = perp.get("oi_change_pct", 0)
            row["mark_price"] = perp.get("mark_price", 0)
            row["premium_pct"] = perp.get("premium_pct", 0)
        market_rows.append(row)

    # Stale data detection
    _stale_symbols: list[str] = []
    _now = datetime.utcnow()
    for mr in market_rows:
        try:
            ts = mr.get("timestamp", "")
            if isinstance(ts, str) and ts:
                _clean = ts.replace("Z", "").replace("+00:00", "")
                _parsed = datetime.fromisoformat(_clean)
                if (_now - _parsed).total_seconds() > 300:
                    _stale_symbols.append(mr["symbol"])
        except Exception:
            pass
    _data_stale = len(_stale_symbols) > 0

    resolved_chart_focus_symbol = chart_focus_symbol if chart_focus_symbol in settings.tracked_symbols else None
    if resolved_chart_focus_symbol is None and market_rows:
        resolved_chart_focus_symbol = str(market_rows[0]["symbol"])
    if include_chart_package and resolved_chart_focus_symbol is not None:
        selected_chart_package = learning_center.build_chart_package(resolved_chart_focus_symbol)
        if selected_chart_package is not None:
            chart_packages[resolved_chart_focus_symbol] = selected_chart_package

    # Recent decisions & trades (Django ORM)
    recent_decisions = list(Decision.objects.order_by("-timestamp")[:10])
    recent_trades = list(SimulatedTrade.objects.order_by("-opened_at")[:10])
    live_orders = list(LiveOrderLog.objects.order_by("-created_at")[:50])

    learning_payload = learning_center.build_learning_state(market_rows, chart_packages)
    backtest_payload = backtest_service.get_rankings()

    # API usage aggregate (Django ORM)
    api_usage = OpenAIUsageLog.objects.aggregate(
        calls=Count("id"),
        input_tokens=Coalesce(Sum("input_tokens"), 0),
        output_tokens=Coalesce(Sum("output_tokens"), 0),
        total_tokens=Coalesce(Sum("total_tokens"), 0),
        estimated_cost_usd=Coalesce(Sum("estimated_cost_usd"), 0.0),
    )

    user_trading_mode = current_user.trading_mode if current_user and hasattr(current_user, "trading_mode") else settings.trading_mode
    user_alloc_mode = getattr(current_user, "live_alloc_mode", "percent") or "percent" if current_user else "percent"
    user_alloc_value = getattr(current_user, "live_alloc_value", 10.0) or 10.0 if current_user else 10.0

    _user_has_binance = False
    _user_has_bybit = False
    if current_user is not None:
        _user_api_keys = api_key_service.get_user_api_keys(current_user.id)
        _user_has_binance = any(k.exchange == "binance" and k.is_active for k in _user_api_keys)
        _user_has_bybit = any(k.exchange == "bybit" and k.is_active for k in _user_api_keys)
    _global_binance = bool(settings.binance_api_key and settings.binance_api_secret)

    system_status = {
        "scheduler": scheduler_service.status(),
        "trading_mode": user_trading_mode,
        "learning_mode": settings.learning_mode,
        "agent_mode": active_profile["id"],
        "agent_mode_label": active_profile["label"],
        "agent_mode_description": active_profile["description"],
        "exploration_rate": active_profile["exploration_rate"],
        "market_interval": settings.market_interval,
        "data_sources": settings.market_data_sources,
        "tracked_symbols_count": len(settings.tracked_symbols),
        "binance_private_ready": _user_has_binance or _global_binance,
        "bybit_private_ready": _user_has_bybit,
        "quote_currency": settings.quote_currency,
        "display_currency": display_currency,
        "max_trades_per_day": active_profile["max_trades_per_day"],
        "max_open_positions": active_profile["max_open_positions"],
        "preferred_trade_quotes": settings.preferred_trade_quotes,
        "live_alloc_mode": user_alloc_mode,
        "live_alloc_value": user_alloc_value,
        "data_stale": _data_stale,
        "stale_symbols": _stale_symbols,
    }

    private_learning = None
    trade_ranking = None
    binance_wallet = None
    live_portfolio = None
    bybit_wallet = None
    bybit_positions = None
    if current_user is not None:
        _uid = current_user.id
        _cached = _get_exchange_cache(_uid) if skip_exchange_api else None
        if _cached is not None:
            private_learning = _cached.get("private_learning")
            trade_ranking = _cached.get("trade_ranking")
            binance_wallet = _cached.get("binance_wallet")
            live_portfolio = _cached.get("live_portfolio")
            bybit_wallet = _cached.get("bybit_wallet")
            bybit_positions = _cached.get("bybit_positions")
        else:
            _, client = get_user_binance_client(current_user.id)
            if client is not None:
                private_learning = learning_center.build_private_learning_state(
                    client,
                    settings.tracked_symbols,
                    settings.preferred_trade_quotes,
                )
                trade_ranking = learning_center.build_trade_history_ranking(
                    client,
                    settings.tracked_symbols,
                    settings.preferred_trade_quotes,
                )
                if user_trading_mode == "LIVE":
                    try:
                        for try_quote in ["PLN", settings.exchange_quote_currency, "USDT"]:
                            portfolio = client.get_portfolio_value(try_quote)
                            if isinstance(portfolio, dict) and "error" not in portfolio:
                                total = portfolio.get("total_value", 0)
                                if total > 0:
                                    binance_wallet = portfolio
                                    break
                    except Exception:
                        pass
                    try:
                        quote_for_pnl = (binance_wallet or {}).get("quote_currency", "PLN")
                        live_portfolio = client.get_portfolio_with_cost_basis(quote_for_pnl)
                    except Exception:
                        pass

            _, bybit_client = get_user_bybit_client(current_user.id)
            if bybit_client is not None and user_trading_mode == "LIVE":
                try:
                    bybit_wallet = bybit_client.get_portfolio_value()
                    if isinstance(bybit_wallet, dict) and "error" in bybit_wallet:
                        bybit_wallet = None
                except Exception:
                    bybit_wallet = None
                try:
                    bybit_positions = bybit_client.get_open_positions_summary()
                except Exception:
                    bybit_positions = None

            _set_exchange_cache(_uid, {
                "private_learning": private_learning,
                "trade_ranking": trade_ranking,
                "binance_wallet": binance_wallet,
                "live_portfolio": live_portfolio,
                "bybit_wallet": bybit_wallet,
                "bybit_positions": bybit_positions,
            })

    # --- Leverage paper trading snapshot ---
    leverage_snapshot = None
    try:
        leverage_snapshot = leverage_engine.get_snapshot()
    except Exception:
        pass

    # --- Live stats (Django ORM) ---
    live_stats: dict[str, object] | None = None
    if user_trading_mode == "LIVE" and current_user is not None:
        _live_orders_all = list(LiveOrderLog.objects.filter(username=current_user.username))
        _ok_buys = [o for o in _live_orders_all if o.status == "ok" and o.action == "BUY"]
        _ok_sells = [o for o in _live_orders_all if o.status == "ok" and o.action == "SELL"]

        _stables = {"USDT", "BUSD", "FDUSD", "PLN", "EUR", "USD", "USDC"}
        _lp = live_portfolio or []
        _crypto_holdings = [h for h in _lp if not h.get("is_stable", False) and h.get("asset") not in _stables]
        _gross_profit = sum(h["pnl_value"] for h in _crypto_holdings if h.get("pnl_value", 0) > 0)
        _gross_loss = abs(sum(h["pnl_value"] for h in _crypto_holdings if h.get("pnl_value", 0) < 0))
        _total_pnl = sum(h["pnl_value"] for h in _crypto_holdings)
        _winning = len([h for h in _crypto_holdings if h.get("pnl_value", 0) > 0])
        _losing = len([h for h in _crypto_holdings if h.get("pnl_value", 0) < 0])
        _total_positions = _winning + _losing
        _win_rate = round(_winning / _total_positions * 100, 2) if _total_positions > 0 else 0.0

        _total_commission = sum(o.commission or 0.0 for o in _live_orders_all if o.status == "ok" and o.commission)
        _commission_assets: dict[str, float] = {}
        for o in _live_orders_all:
            if o.status == "ok" and o.commission and o.commission_asset:
                _commission_assets[o.commission_asset] = _commission_assets.get(o.commission_asset, 0) + o.commission

        live_stats = {
            "buy_count": len(_ok_buys),
            "sell_count": len(_ok_sells),
            "win_rate": _win_rate,
            "gross_profit": round(_gross_profit, 2),
            "gross_loss": round(_gross_loss, 2),
            "realized_pnl": round(_total_pnl, 2),
            "winning_count": _winning,
            "losing_count": _losing,
            "total_commission": round(_total_commission, 6),
            "commission_by_asset": {k: round(v, 6) for k, v in _commission_assets.items()},
        }

    return {
        "wallet": wallet_service.get_snapshot(),
        "market": market_rows,
        "chart_packages": chart_packages,
        "chart_focus_symbol": resolved_chart_focus_symbol,
        "recent_decisions": [
            {
                "symbol": row.symbol,
                "decision": row.decision,
                "confidence": round(row.confidence * 100, 1),
                "reason": row.reason,
                "timestamp": row.timestamp.isoformat(),
            }
            for row in recent_decisions
        ],
        "recent_trades": [
            {
                "symbol": row.symbol,
                "status": row.status,
                "quantity": round(row.quantity, 6),
                "buy_price": round(row.buy_price, 2),
                "buy_value": round(row.buy_value, 2),
                "buy_fee": round(row.buy_fee, 2),
                "sell_price": round(row.sell_price, 2) if row.sell_price is not None else None,
                "sell_value": round(row.sell_value, 2) if row.sell_value is not None else None,
                "sell_fee": round(row.sell_fee, 2) if row.sell_fee is not None else None,
                "profit": round(row.profit, 2) if row.profit is not None else None,
                "opened_at": row.opened_at.isoformat(),
                "closed_at": row.closed_at.isoformat() if row.closed_at is not None else None,
            }
            for row in recent_trades
        ],
        "learning": learning_payload,
        "articles": learning_center.get_articles(),
        "backtest": backtest_payload,
        "private_learning": private_learning,
        "trade_ranking": trade_ranking,
        "binance_wallet": binance_wallet,
        "live_portfolio": live_portfolio,
        "bybit_wallet": bybit_wallet,
        "bybit_positions": bybit_positions,
        "leverage_paper": leverage_snapshot,
        "live_stats": live_stats,
        "live_orders": [
            {
                "created_at": row.created_at.isoformat() + "Z",
                "username": row.username,
                "symbol": row.symbol,
                "action": row.action,
                "status": row.status,
                "detail": row.detail,
                "order_id": row.order_id,
                "allocation": row.allocation,
                "quote_currency": row.quote_currency,
            }
            for row in live_orders
        ],
        "api_usage": {
            "calls": int(api_usage["calls"] or 0),
            "input_tokens": int(api_usage["input_tokens"] or 0),
            "output_tokens": int(api_usage["output_tokens"] or 0),
            "total_tokens": int(api_usage["total_tokens"] or 0),
            "estimated_cost_usd": round(float(api_usage["estimated_cost_usd"] or 0.0), 6),
        },
        "system_status": system_status,
        "config": {
            "quote_currency": settings.quote_currency.upper(),
            "display_currency": display_currency,
            "start_balance_display_pln": settings.starting_balance_display_pln,
            "display_fx_rates": {
                f"{settings.quote_currency.upper()}_{display_currency}": usd_to_display_rate,
                f"{settings.exchange_quote_currency}_{display_currency}": usd_to_display_rate,
            },
            "display_rate_source": rate_source,
            "tracked_symbols": settings.tracked_symbols,
            "symbol_groups": settings.symbol_groups,
            "agent_mode_profiles": settings.agent_mode_profiles,
            "start_balance": settings.starting_balance_quote,
            "fee_rate": settings.fee_rate,
            "slippage": settings.slippage,
            "trading_mode": user_trading_mode,
            "learning_mode": settings.learning_mode,
            "preferred_trade_quotes": settings.preferred_trade_quotes,
            "dashboard_refresh_seconds": settings.dashboard_refresh_seconds,
            "live_quote_cache_seconds": settings.live_quote_cache_seconds,
        },
    }


# ---------------------------------------------------------------------------
# GET /api/risk-status — current risk-management directives
# ---------------------------------------------------------------------------
@require_GET
def risk_status(request):
    try:
        from app.services.risk_management import RiskManager
        result = RiskManager().assess()
        return _apply_no_cache(JsonResponse(result))
    except Exception as exc:
        logger.exception("risk_status failed")
        return JsonResponse({
            "level": "NORMAL",
            "allow_new_buys": True,
            "position_size_multiplier": 1.0,
            "reasons": [],
            "error": str(exc),
        }, status=200)


# ---------------------------------------------------------------------------
# GET /api/learning-insights — adaptive learning analytics
# ---------------------------------------------------------------------------
@require_GET
def learning_insights(request):
    """Return summary of closed paper trades: WR, profit factor, exit-reason
    breakdown, equity curve, hold-time distribution, and top/worst symbols.
    """
    from datetime import datetime, timedelta
    from app.models import SimulatedTrade, LearningLog

    def _categorize(reason: str | None) -> str:
        if not reason:
            return "other"
        r = reason.lower()
        if "take profit" in r or "tp osi" in r or "profit target" in r:
            return "take_profit"
        if "stop loss" in r or "stop-loss" in r or "sl osi" in r:
            return "stop_loss"
        if "trailing" in r:
            return "trailing"
        if "partial" in r:
            return "partial"
        if "timeout" in r or "max hold" in r or "time rotation" in r:
            return "timeout"
        if "rsi wykupiony" in r or "rsi overbought" in r:
            return "rsi_overbought"
        if "bb upper" in r or "bollinger" in r and "upper" in r:
            return "bb_upper"
        if "macd bear" in r or "macd spadkow" in r:
            return "macd_bearish"
        if "divergence" in r or "dywergencja" in r:
            return "divergence"
        if "top probability" in r or "szczyt" in r:
            return "top_probability"
        if "momentum" in r:
            return "momentum_loss"
        if "vwap" in r:
            return "vwap"
        if "whale" in r or "sprzedaj" in r and "whale" in r:
            return "whale_sell"
        return "other"

    def _summary_for(days: int | None) -> dict:
        qs = SimulatedTrade.objects.filter(status="CLOSED")
        if days is not None:
            cutoff = datetime.utcnow() - timedelta(days=days)
            qs = qs.filter(closed_at__gte=cutoff)
        trades = list(qs)
        n = len(trades)
        if n == 0:
            return {"trades": 0, "win_rate": 0, "profit_factor": 0,
                    "avg_profit": 0, "total_profit": 0, "avg_hold_hours": 0}
        wins = [t for t in trades if (t.profit or 0) > 0]
        losses = [t for t in trades if (t.profit or 0) <= 0]
        gross_win = sum(t.profit or 0 for t in wins)
        gross_loss = abs(sum(t.profit or 0 for t in losses)) or 1e-9
        avg_hold = sum(((t.duration_minutes or 0) / 60.0) for t in trades) / n
        return {
            "trades": n,
            "win_rate": round(100 * len(wins) / n, 1),
            "profit_factor": round(gross_win / gross_loss, 3),
            "avg_profit": round(sum(t.profit or 0 for t in trades) / n, 4),
            "total_profit": round(sum(t.profit or 0 for t in trades), 2),
            "avg_hold_hours": round(avg_hold, 2),
        }

    try:
        all_trades = list(SimulatedTrade.objects.filter(status="CLOSED").order_by("closed_at"))
        n_total = len(all_trades)

        # Hold-time distribution
        durations_min = [(t.duration_minutes or 0) for t in all_trades]
        median_hold_min = (sorted(durations_min)[n_total // 2] if n_total else 0)
        under_30 = sum(1 for d in durations_min if d < 30)
        under_30_pct = round(100 * under_30 / max(n_total, 1), 1)

        # Exit reason buckets (sourced from LearningLog.notes/result)
        ll_qs = LearningLog.objects.all().values_list("notes", "result")
        buckets: dict[str, int] = {}
        ll_total = 0
        for notes, result in ll_qs:
            ll_total += 1
            key = _categorize((notes or "") + " " + (result or ""))
            buckets[key] = buckets.get(key, 0) + 1
        exit_reasons = sorted(
            [{"name": k, "count": v, "pct": round(100 * v / max(ll_total, 1), 1)}
             for k, v in buckets.items() if v > 0],
            key=lambda x: x["count"],
            reverse=True,
        )

        # Per-symbol stats
        symbol_stats: dict[str, dict] = {}
        for t in all_trades:
            s = symbol_stats.setdefault(t.symbol, {"n": 0, "wins": 0, "profit": 0.0})
            s["n"] += 1
            if (t.profit or 0) > 0:
                s["wins"] += 1
            s["profit"] += t.profit or 0
        symbol_rows = [
            {"symbol": k, "trades": v["n"], "win_rate": round(100 * v["wins"] / v["n"], 1),
             "total_profit": round(v["profit"], 2)}
            for k, v in symbol_stats.items()
        ]
        top_symbols = sorted(symbol_rows, key=lambda x: x["total_profit"], reverse=True)[:5]
        worst_symbols = sorted(symbol_rows, key=lambda x: x["total_profit"])[:5]

        # Equity curve
        equity = 0.0
        equity_curve = []
        for t in all_trades:
            equity += t.profit or 0
            equity_curve.append({
                "ts": t.closed_at.isoformat() if t.closed_at else "",
                "equity": round(equity, 2),
            })

        return _apply_no_cache(JsonResponse({
            "summary_7d": _summary_for(7),
            "summary_30d": _summary_for(30),
            "summary_all": _summary_for(None),
            "median_hold_minutes": round(median_hold_min, 1),
            "under_30min_pct": under_30_pct,
            "exit_reasons": exit_reasons,
            "top_symbols": top_symbols,
            "worst_symbols": worst_symbols,
            "equity_curve": equity_curve,
        }))
    except Exception as exc:
        logger.exception("learning_insights failed")
        return JsonResponse({"error": str(exc)}, status=500)


