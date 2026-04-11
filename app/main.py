from __future__ import annotations

import logging
import os
import threading
import time as _time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Request, Depends, Cookie
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, EmailStr, Field
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from sqlalchemy import desc, func, select
from starlette.responses import Response

from app.config import settings
from app.database import SessionLocal, init_db
from app.models import AuditLog, Decision, FeatureSnapshot, LiveOrderLog, MarketData, OpenAIUsageLog, SimulatedTrade, User
from app.services.auth import AuthService, APIKeyService, validate_password
from app.services.binance_api import BinanceService
from app.services.bybit_api import BybitService
from app.services.leverage_engine import LeverageEngine
from app.services.agent_cycle import AgentCycle
from app.services.ai_advisor import AIAdvisor
from app.services.backtest import BacktestService
from app.services.currency_service import CurrencyService
from app.services.learning_center import LearningCenter
from app.services.market_data import LiveQuoteService, load_latest_market_row
from app.services.runtime_state import RuntimeStateService
from app.services.scheduler import SchedulerService
from app.services.wallet import WalletService

logger = logging.getLogger(__name__)

# ---- Exchange data cache (per-user, TTL-based) ----
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

# ---- Rate limiter ----
limiter = Limiter(key_func=get_remote_address)

app = FastAPI(title=settings.app_name)
app.state.limiter = limiter


# ---- CORS ----
_allowed_origins = [
    origin.strip()
    for origin in os.getenv("ALLOWED_ORIGINS", "https://agentkrypto.apka.org.pl,https://magicparty.usermd.net").split(",")
    if origin.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["Content-Type"],
    max_age=600,
)


# ---- Security headers middleware ----
@app.middleware("http")
async def security_headers(request: Request, call_next):
    response: Response = await call_next(request)
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self' https://cdn.jsdelivr.net 'unsafe-inline'; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src 'self' https://fonts.gstatic.com; "
        "img-src 'self' data:; "
        "connect-src 'self'; "
        "frame-ancestors 'none';"
    )
    if os.getenv("FORCE_HTTPS", "").lower() in ("1", "true"):
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response


# ---- Rate-limit error handler ----
@app.exception_handler(RateLimitExceeded)
async def _rate_limit_handler(request: Request, exc: RateLimitExceeded):
    return JSONResponse({"detail": "Zbyt wiele żądań. Spróbuj ponownie za chwilę."}, status_code=429)
base_dir = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(base_dir / "templates"))
app.mount("/static", StaticFiles(directory=str(base_dir / "static")), name="static")
static_assets_version = str(
    max(
        int((base_dir / "static" / "app.js").stat().st_mtime),
        int((base_dir / "static" / "styles.css").stat().st_mtime),
    )
)

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


# Request models for auth
class RegisterRequest(BaseModel):
    email: EmailStr
    username: str = Field(..., min_length=3, max_length=32, pattern=r"^[a-zA-Z0-9_\-]+$")
    password: str = Field(..., min_length=8, max_length=128)

class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., max_length=128)

class AddAPIKeyRequest(BaseModel):
    label: str | None = Field(None, max_length=64)
    exchange: str = Field("binance", pattern=r"^[a-z]+$")
    api_key: str = Field(..., min_length=10, max_length=128, pattern=r"^[a-zA-Z0-9]+$")
    api_secret: str = Field(..., min_length=10, max_length=256, pattern=r"^[a-zA-Z0-9]+$")
    is_testnet: bool = False
    permissions: str = Field("read", pattern=r"^(read|trade)$")


async def get_current_user(session_token: Optional[str] = Cookie(None)) -> Optional[User]:
    """Get current user from session token cookie."""
    if not session_token:
        return None
    with SessionLocal() as session:
        user = auth_service.validate_token(session, session_token)
        return user


async def require_auth(session_token: Optional[str] = Cookie(None)) -> User:
    """Require authentication - raises 401 if not logged in."""
    user = await get_current_user(session_token)
    if not user:
        raise HTTPException(status_code=401, detail="Wymagane logowanie")
    return user


def serialize_user(user: User) -> dict[str, object]:
    return {
        "id": user.id,
        "email": user.email,
        "username": user.username,
        "trading_mode": getattr(user, "trading_mode", "PAPER"),
        "agent_mode": getattr(user, "agent_mode", "normal"),
        "created_at": user.created_at.isoformat() if user.created_at else None,
    }


def resolve_request_user(request: Request) -> User | None:
    session_token = request.cookies.get("session_token")
    if not session_token:
        return None
    with SessionLocal() as session:
        return auth_service.validate_token(session, session_token)


def get_user_binance_client(session, user_id: int, key_id: int | None = None):
    keys = api_key_service.get_user_api_keys(session, user_id)
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


def get_user_bybit_client(session, user_id: int, key_id: int | None = None):
    """Get a Bybit client for the user (filters by exchange='bybit')."""
    keys = api_key_service.get_user_api_keys(session, user_id)
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


def _get_client_ip(request: Request) -> str:
    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        return forwarded.split(",")[0].strip()[:45]
    real_ip = request.headers.get("X-Real-IP", "")
    if real_ip:
        return real_ip[:45]
    return (request.client.host if request.client else "unknown")[:45]


def run_managed_cycle() -> dict[str, object]:
    with SessionLocal() as session:
        return cycle_runner.run(session)


scheduler_service = SchedulerService(settings.cycle_interval_seconds, run_managed_cycle)


def no_cache_headers() -> dict[str, str]:
    return {
        "Cache-Control": "no-store, max-age=0",
        "Pragma": "no-cache",
    }


@app.on_event("startup")
def startup_event() -> None:
    init_db()
    # Migrate XOR-encrypted API keys to Fernet
    try:
        with SessionLocal() as session:
            migrated = api_key_service.re_encrypt_from_xor(session)
            if migrated:
                logger.info("Security: migrated %d API keys to Fernet encryption", migrated)
    except Exception as exc:
        logger.error("API key migration failed: %s", exc)
    with SessionLocal() as session:
        existing_market = session.execute(select(MarketData.id).limit(1)).scalar_one_or_none()
        existing_decision = session.execute(select(Decision.id).limit(1)).scalar_one_or_none()
        if existing_market is None or existing_decision is None:
            cycle_runner.run(session)
    if settings.scheduler_enabled:
        scheduler_service.start()
    # Prewarm caches in a background thread so the first dashboard load is fast
    import threading

    def _prewarm() -> None:
        import time
        time.sleep(2)
        try:
            # Stage 1: warm Bybit bulk ticker (single fast API call)
            from app.services.bybit_market import _fetch_all_linear_tickers
            _fetch_all_linear_tickers()
        except Exception:
            pass
        try:
            # Stage 2: warm market quotes + summaries + dashboard
            with SessionLocal() as session:
                _build_dashboard_payload(session)
        except Exception:
            pass

    threading.Thread(target=_prewarm, daemon=True, name="cache-prewarm").start()


@app.on_event("shutdown")
def shutdown_event() -> None:
    scheduler_service.stop()


@app.get("/", response_class=HTMLResponse)
def index(request: Request) -> HTMLResponse:
    response = templates.TemplateResponse(
        request,
        "index.html",
        {
            "request": request,
            "app_name": settings.app_name,
            "symbols": settings.tracked_symbols,
            "static_assets_version": static_assets_version,
        },
    )
    for header, value in no_cache_headers().items():
        response.headers[header] = value
    return response


@app.get("/api/dashboard")
def dashboard(request: Request) -> JSONResponse:
    scheduler_service.ensure_running()
    current_user = resolve_request_user(request)
    with SessionLocal() as session:
        return JSONResponse(_build_dashboard_payload(session, current_user=current_user), headers=no_cache_headers())


@app.get("/api/chart-package")
def chart_package(symbol: str, limit: int = 120) -> JSONResponse:
    if symbol not in settings.tracked_symbols:
        raise HTTPException(status_code=404, detail=f"Nieznany symbol: {symbol}")
    limit = min(max(limit, 10), 300)
    with SessionLocal() as session:
        payload = learning_center.build_chart_package(session, symbol, limit=limit)
    if payload is None:
        raise HTTPException(status_code=404, detail=f"Brak danych wykresu dla {symbol}")
    return JSONResponse(payload, headers=no_cache_headers())


@app.post("/api/run-cycle")
def run_cycle() -> JSONResponse:
    with SessionLocal() as session:
        run_result = cycle_runner.run(session)
        dashboard_payload = _build_dashboard_payload(session)
    return JSONResponse({"run": run_result, "dashboard": dashboard_payload})


@app.get("/api/backtest")
def backtest(force_refresh: bool = False) -> JSONResponse:
    with SessionLocal() as session:
        payload = backtest_service.get_rankings(session, force_refresh=force_refresh)
    return JSONResponse(payload)


@app.post("/api/scheduler/start")
def scheduler_start() -> JSONResponse:
    scheduler_service.start()
    return JSONResponse(scheduler_service.status())


@app.post("/api/scheduler/stop")
def scheduler_stop() -> JSONResponse:
    scheduler_service.stop()
    return JSONResponse(scheduler_service.status())


@app.get("/api/ai-insight")
def ai_insight(request: Request, symbol: str | None = None) -> JSONResponse:
    current_user = resolve_request_user(request)
    with SessionLocal() as session:
        dashboard_payload = _build_dashboard_payload(
            session,
            include_chart_package=True,
            chart_focus_symbol=symbol,
            current_user=current_user,
        )
        result = ai_advisor.generate_market_brief(session, dashboard_payload, symbol=symbol)
    return JSONResponse(result)


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=2000)
    history: list[dict] = Field(default_factory=list)


@app.post("/api/agent-chat")
@limiter.limit("15/minute")
def agent_chat(request: Request, body: ChatRequest) -> JSONResponse:
    """Interactive chat with Agent Krypto. User can ask questions and give commands."""
    current_user = resolve_request_user(request)
    with SessionLocal() as session:
        dashboard_payload = _build_dashboard_payload(
            session,
            include_chart_package=True,
            current_user=current_user,
            skip_exchange_api=True,
        )
        result = ai_advisor.chat(
            session,
            user_message=body.message,
            dashboard=dashboard_payload,
            conversation_history=body.history,
            current_user=current_user,
        )
    return JSONResponse(result)


class ChatExecuteRequest(BaseModel):
    action: str = Field(..., pattern=r"^(BUY|SELL)$")
    symbol: str = Field(..., min_length=2, max_length=10, pattern=r"^[A-Z]+$")


@app.post("/api/agent-chat/execute")
@limiter.limit("10/minute")
async def agent_chat_execute(request: Request, body: ChatExecuteRequest, user: User = Depends(require_auth)) -> JSONResponse:
    """Execute a trading command from chat (requires LIVE mode + auth)."""
    with SessionLocal() as session:
        db_user = session.get(User, user.id)
        if db_user is None or db_user.trading_mode != "LIVE":
            return JSONResponse({"ok": False, "error": "Musisz byc w trybie LIVE aby wykonywac zlecenia."}, status_code=400)

        selected_key, client = get_user_binance_client(session, user.id)
        if client is None:
            return JSONResponse({"ok": False, "error": "Brak klucza API Binance."}, status_code=400)

        from app.models import LiveOrderLog
        from app.services.agent_cycle import _BRIDGE_QUOTES, _MIN_ORDER

        symbol = body.symbol
        action = body.action

        if action == "BUY":
            # Find usable quote currency
            balances = client.get_balances()
            tradeable = client.get_tradeable_pairs()  # {base: [quotes]}
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

                # Use user allocation settings
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
                    session.add(LiveOrderLog(
                        username=user.username, symbol=symbol, action="BUY", status="ok",
                        detail=f"Czat: kupiono za {round(alloc, 2)} {quote}",
                        order_id=str(result.get("orderId", "")), allocation=round(alloc, 4), quote_currency=quote,
                        commission=comm, commission_asset=comm_asset,
                    ))
                    session.commit()
                    return JSONResponse({"ok": True, "detail": f"Kupiono {symbol} za {round(alloc, 2)} {quote}", "order": result})
                else:
                    detail = result.get("error", "Blad zlecenia") if isinstance(result, dict) else str(result)

            session.add(LiveOrderLog(
                username=user.username, symbol=symbol, action="BUY", status="error",
                detail=f"Czat: {detail}", allocation=0, quote_currency="",
            ))
            session.commit()
            return JSONResponse({"ok": False, "error": detail}, status_code=400)

        elif action == "SELL":
            import math, time as _time
            balances = client.get_balances()
            tradeable = client.get_tradeable_pairs()  # {base: [quotes]}
            available_quotes = tradeable.get(symbol, [])
            held = next((b for b in balances if b["asset"] == symbol), None)
            if not held or held["free"] <= 0:
                return JSONResponse({"ok": False, "error": f"Nie posiadasz {symbol} do sprzedazy."}, status_code=400)

            # Check actual spot balance vs merged (Earn) balance
            spot_free = client.get_spot_free(symbol)
            total_free = held["free"]
            earn_redeemed = False

            if spot_free < total_free * 0.5:
                # Most of the balance is in Earn — try to redeem
                earn_pos = client.get_earn_flexible_position(symbol)
                if earn_pos:
                    product_id = earn_pos.get("productId", "")
                    if product_id:
                        redeem_result = client.redeem_earn_flexible(product_id, redeem_all=True)
                        if isinstance(redeem_result, dict) and "error" not in redeem_result:
                            earn_redeemed = True
                            _time.sleep(2)  # Wait for redemption to settle
                            spot_free = client.get_spot_free(symbol)
                        else:
                            err_msg = redeem_result.get("error", str(redeem_result)) if isinstance(redeem_result, dict) else str(redeem_result)
                            logger.warning("Earn redeem failed for %s: %s", symbol, err_msg)

            qty = spot_free
            if qty <= 0:
                return JSONResponse({"ok": False, "error": f"Saldo spot {symbol} = 0. Tokeny moga byc zablokowane w Earn/Staking."}, status_code=400)

            # Get LOT_SIZE filter from exchange info
            exchange_info = client.get_exchange_info()
            symbols_info = {}
            if isinstance(exchange_info, dict) and "error" not in exchange_info:
                symbols_info = {s["symbol"]: s for s in exchange_info.get("symbols", [])}

            # Find best pair
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
                    session.add(LiveOrderLog(
                        username=user.username, symbol=symbol, action="SELL", status="ok",
                        detail=detail_msg,
                        order_id=str(result.get("orderId", "")), allocation=round(qty_floored, 6), quote_currency=quote,
                        commission=comm, commission_asset=comm_asset,
                    ))
                    session.commit()
                    return JSONResponse({"ok": True, "detail": f"Sprzedano {round(qty_floored, 6)} {symbol} za {quote}", "order": result})
                else:
                    detail = result.get("error", "Blad zlecenia") if isinstance(result, dict) else str(result)
                    session.add(LiveOrderLog(
                        username=user.username, symbol=symbol, action="SELL", status="error",
                        detail=f"Czat: {detail}", allocation=0, quote_currency=quote,
                    ))
                    session.commit()
                    return JSONResponse({"ok": False, "error": detail}, status_code=400)

            return JSONResponse({"ok": False, "error": f"Nie znaleziono pary handlowej dla {symbol}."}, status_code=400)

    return JSONResponse({"ok": False, "error": "Nieznana akcja."}, status_code=400)


@app.post("/api/agent-mode/{mode}")
def set_agent_mode(mode: str, request: Request) -> JSONResponse:
    current_user = resolve_request_user(request)
    with SessionLocal() as session:
        normalized = mode.strip().lower()
        if normalized not in settings.agent_mode_profiles:
            raise HTTPException(status_code=400, detail=f"Nieznany tryb agenta: {mode}")

        if current_user is not None:
            db_user = session.get(User, current_user.id)
            if db_user is not None:
                db_user.agent_mode = normalized
                session.commit()
                current_user = db_user
        else:
            runtime_state.set_agent_mode(session, normalized)

        payload = _build_dashboard_payload(session, current_user=current_user)
    return JSONResponse({"mode": normalized, "dashboard": payload})


@app.post("/api/paper/reset")
def reset_paper_portfolio() -> JSONResponse:
    scheduler_was_enabled = scheduler_service.status().get("enabled", False)
    if scheduler_was_enabled:
        scheduler_service.stop()

    with SessionLocal() as session:
        reset_stats = wallet_service.reset_paper_portfolio(session)
        payload = _build_dashboard_payload(session)

    return JSONResponse(
        {
            "message": "Portfel paper zostal zresetowany do stanu startowego.",
            "scheduler_stopped": scheduler_was_enabled,
            "reset": reset_stats,
            "dashboard": payload,
        }
    )


@app.get("/api/chart-history")
def chart_history(symbol: str, force_refresh: bool = False) -> JSONResponse:
    if symbol not in settings.tracked_symbols:
        raise HTTPException(status_code=404, detail=f"Nieznany symbol: {symbol}")
    payload = learning_center.build_lifecycle_history(symbol, force_refresh=force_refresh)
    return JSONResponse(payload)


@app.get("/api/calendar")
def calendar_data(request: Request, year: int | None = None, month: int | None = None) -> JSONResponse:
    """Return trade/order data grouped by day for the calendar view, with weekly/monthly/yearly summaries."""
    from datetime import datetime, date, timedelta
    from collections import defaultdict

    now = datetime.utcnow()
    y = year or now.year
    m = month or now.month

    # Build date range: full month + padding to complete weeks
    first_day = date(y, m, 1)
    if m == 12:
        last_day = date(y + 1, 1, 1) - timedelta(days=1)
    else:
        last_day = date(y, m + 1, 1) - timedelta(days=1)

    # Extend to full weeks (Mon=0..Sun=6)
    start = first_day - timedelta(days=first_day.weekday())
    end = last_day + timedelta(days=6 - last_day.weekday())

    with SessionLocal() as session:
        current_user = resolve_request_user(request)

        # --- Live orders (LIVE mode) — filtered by user ---
        live_query = (
            select(LiveOrderLog)
            .where(
                LiveOrderLog.created_at >= datetime.combine(start, datetime.min.time()),
                LiveOrderLog.created_at <= datetime.combine(end, datetime.max.time()),
            )
        )
        if current_user is not None:
            live_query = live_query.where(LiveOrderLog.username == current_user.username)
        live_rows = session.execute(
            live_query.order_by(LiveOrderLog.created_at)
        ).scalars().all()

        # --- Paper trades ---
        paper_rows = session.execute(
            select(SimulatedTrade)
            .where(
                SimulatedTrade.opened_at >= datetime.combine(start, datetime.min.time()),
                SimulatedTrade.opened_at <= datetime.combine(end, datetime.max.time()),
            )
            .order_by(SimulatedTrade.opened_at)
        ).scalars().all()

        # Also get trades CLOSED in this period (may have been opened earlier)
        paper_closed = session.execute(
            select(SimulatedTrade)
            .where(
                SimulatedTrade.closed_at >= datetime.combine(start, datetime.min.time()),
                SimulatedTrade.closed_at <= datetime.combine(end, datetime.max.time()),
                SimulatedTrade.status == "CLOSED",
            )
            .order_by(SimulatedTrade.closed_at)
        ).scalars().all()

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
        seen_ids = set()
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
                pass  # already counted as BUY
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

        # --- Build summaries ---
        day_list = sorted(days.values(), key=lambda x: x["date"])

        # Weekly summaries
        weeks = defaultdict(lambda: {"buys": 0, "sells": 0, "live_buys": 0, "live_sells": 0, "paper_profit": 0.0, "live_volume": 0.0, "errors": 0, "skips": 0})
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

        # Monthly summary (only current month)
        month_summary = {"buys": 0, "sells": 0, "live_buys": 0, "live_sells": 0, "paper_profit": 0.0, "live_volume": 0.0, "errors": 0, "skips": 0, "active_days": 0}
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
        year_live = session.execute(
            select(
                func.count(LiveOrderLog.id),
                func.coalesce(func.sum(LiveOrderLog.allocation), 0.0),
            ).where(
                LiveOrderLog.created_at >= datetime(y, 1, 1),
                LiveOrderLog.created_at < datetime(y + 1, 1, 1),
                LiveOrderLog.status == "ok",
            )
        ).one()
        year_paper = session.execute(
            select(
                func.count(SimulatedTrade.id),
                func.coalesce(func.sum(SimulatedTrade.profit), 0.0),
            ).where(
                SimulatedTrade.closed_at >= datetime(y, 1, 1),
                SimulatedTrade.closed_at < datetime(y + 1, 1, 1),
                SimulatedTrade.status == "CLOSED",
            )
        ).one()
        year_summary = {
            "live_trades": int(year_live[0] or 0),
            "live_volume": round(float(year_live[1] or 0), 2),
            "paper_closed": int(year_paper[0] or 0),
            "paper_profit": round(float(year_paper[1] or 0), 2),
        }

        # Simplify day entries for JSON
        for dd in day_list:
            dd["paper_profit"] = round(dd["paper_profit"], 2)
            dd["live_volume"] = round(dd["live_volume"], 4)

    return JSONResponse({
        "year": y,
        "month": m,
        "days": day_list,
        "weeks": {k: dict(v) for k, v in weeks.items()},
        "month_summary": month_summary,
        "year_summary": year_summary,
    }, headers=no_cache_headers())


def _build_dashboard_payload(
    session,
    include_chart_package: bool = False,
    chart_focus_symbol: str | None = None,
    current_user: User | None = None,
    skip_exchange_api: bool = False,
) -> dict[str, object]:
    active_profile = runtime_state.get_active_profile(session)
    if current_user is not None:
        user_mode = getattr(current_user, "agent_mode", None) or "normal"
        user_profile = settings.agent_mode_profiles.get(user_mode, settings.agent_mode_profiles[settings.default_agent_mode]).copy()
        user_profile["id"] = user_mode
        active_profile = user_profile
    display_currency = runtime_state.get_display_currency(session)
    usd_to_display_rate, rate_source = currency_service.get_rate(settings.quote_currency, display_currency)
    market_rows: list[dict[str, object]] = []
    chart_packages: dict[str, dict[str, object]] = {}

    # --- Batch queries: load latest feature & decision per symbol in 2 queries ---
    from sqlalchemy import and_
    _all_symbols = list(settings.tracked_symbols)

    _latest_feature_subq = (
        select(func.max(FeatureSnapshot.id).label("max_id"))
        .where(FeatureSnapshot.symbol.in_(_all_symbols))
        .group_by(FeatureSnapshot.symbol)
        .subquery()
    )
    _features_by_sym: dict[str, FeatureSnapshot] = {
        f.symbol: f
        for f in session.execute(
            select(FeatureSnapshot).where(FeatureSnapshot.id.in_(select(_latest_feature_subq.c.max_id)))
        ).scalars().all()
    }

    _latest_decision_subq = (
        select(func.max(Decision.id).label("max_id"))
        .where(Decision.symbol.in_(_all_symbols))
        .group_by(Decision.symbol)
        .subquery()
    )
    _decisions_by_sym: dict[str, Decision] = {
        d.symbol: d
        for d in session.execute(
            select(Decision).where(Decision.id.in_(select(_latest_decision_subq.c.max_id)))
        ).scalars().all()
    }

    # --- Load recent whale alerts per symbol ---
    from app.models import WhaleAlert
    from datetime import timedelta
    _whale_cutoff = datetime.utcnow() - timedelta(hours=24)
    _recent_whale_alerts = session.execute(
        select(WhaleAlert)
        .where(WhaleAlert.created_at >= _whale_cutoff)
        .order_by(desc(WhaleAlert.created_at))
    ).scalars().all()
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

    # Pre-fetch Bybit perpetual data — lightweight (1 API call, no per-symbol requests)
    from app.services.bybit_market import get_batch_perp_tickers
    try:
        _perp_data = get_batch_perp_tickers(_all_symbols)
    except Exception:
        _perp_data = {}

    for symbol in settings.tracked_symbols:
        market = load_latest_market_row(session, symbol)
        feature = _features_by_sym.get(symbol)
        decision = _decisions_by_sym.get(symbol)
        market_summary = learning_center.build_market_summary(session, symbol)

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

    # Stale data detection: warn if latest data is older than 5 minutes
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
        selected_chart_package = learning_center.build_chart_package(session, resolved_chart_focus_symbol)
        if selected_chart_package is not None:
            chart_packages[resolved_chart_focus_symbol] = selected_chart_package

    recent_decisions = session.execute(
        select(Decision).order_by(desc(Decision.timestamp)).limit(10)
    ).scalars().all()
    recent_trades = session.execute(
        select(SimulatedTrade).order_by(desc(SimulatedTrade.opened_at)).limit(10)
    ).scalars().all()
    live_orders = session.execute(
        select(LiveOrderLog).order_by(desc(LiveOrderLog.created_at)).limit(50)
    ).scalars().all()

    learning_payload = learning_center.build_learning_state(session, market_rows, chart_packages)
    backtest_payload = backtest_service.get_rankings(session)
    api_usage = session.execute(
        select(
            func.count(OpenAIUsageLog.id),
            func.coalesce(func.sum(OpenAIUsageLog.input_tokens), 0),
            func.coalesce(func.sum(OpenAIUsageLog.output_tokens), 0),
            func.coalesce(func.sum(OpenAIUsageLog.total_tokens), 0),
            func.coalesce(func.sum(OpenAIUsageLog.estimated_cost_usd), 0.0),
        )
    ).one()
    user_trading_mode = current_user.trading_mode if current_user and hasattr(current_user, 'trading_mode') else settings.trading_mode
    user_alloc_mode = getattr(current_user, "live_alloc_mode", "percent") or "percent" if current_user else "percent"
    user_alloc_value = getattr(current_user, "live_alloc_value", 10.0) or 10.0 if current_user else 10.0
    # Determine if user has Binance/Bybit keys configured (check DB, not env)
    _user_has_binance = False
    _user_has_bybit = False
    if current_user is not None:
        _user_api_keys = api_key_service.get_user_api_keys(session, current_user.id)
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
            # Use cached exchange data (fast path for chat & repeated dashboard loads)
            private_learning = _cached.get("private_learning")
            trade_ranking = _cached.get("trade_ranking")
            binance_wallet = _cached.get("binance_wallet")
            live_portfolio = _cached.get("live_portfolio")
            bybit_wallet = _cached.get("bybit_wallet")
            bybit_positions = _cached.get("bybit_positions")
        else:
            # Fresh fetch from exchange APIs
            _, client = get_user_binance_client(session, current_user.id)
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

            # --- Bybit wallet + positions ---
            _, bybit_client = get_user_bybit_client(session, current_user.id)
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

            # Cache the fetched data for subsequent requests (chat, refreshes)
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
        leverage_snapshot = leverage_engine.get_snapshot(session)
    except Exception:
        pass

    # --- Build live_stats from LiveOrderLog + live_portfolio when LIVE ---
    live_stats: dict[str, object] | None = None
    if user_trading_mode == "LIVE" and current_user is not None:
        _live_orders_all = session.execute(
            select(LiveOrderLog).where(LiveOrderLog.username == current_user.username)
        ).scalars().all()
        _ok_buys = [o for o in _live_orders_all if o.status == "ok" and o.action == "BUY"]
        _ok_sells = [o for o in _live_orders_all if o.status == "ok" and o.action == "SELL"]

        # PnL from live_portfolio (real Binance holdings)
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

        # Total commissions from LiveOrderLog
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
        "wallet": wallet_service.get_snapshot(session),
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
            "calls": int(api_usage[0] or 0),
            "input_tokens": int(api_usage[1] or 0),
            "output_tokens": int(api_usage[2] or 0),
            "total_tokens": int(api_usage[3] or 0),
            "estimated_cost_usd": round(float(api_usage[4] or 0.0), 6),
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


# ============== AUTH ENDPOINTS ==============

@app.post("/api/auth/register")
@limiter.limit("5/minute")
def register(request: Request, body: RegisterRequest) -> JSONResponse:
    """Register a new user account."""
    ip = _get_client_ip(request)
    with SessionLocal() as session:
        success, message, user = auth_service.register(
            session, 
            email=body.email, 
            username=body.username, 
            password=body.password,
            ip_address=ip,
        )
        if not success or user is None:
            raise HTTPException(status_code=400, detail=message)

        login_success, login_message, token = auth_service.login(
            session,
            email_or_username=body.email,
            password=body.password,
            ip_address=ip,
            user_agent=request.headers.get("User-Agent"),
        )
        if not login_success or token is None:
            raise HTTPException(status_code=400, detail=login_message)

        response = JSONResponse({"success": True, "user": serialize_user(user)})
        _set_session_cookie(response, token)
        return response


@app.post("/api/auth/login")
@limiter.limit("5/minute")
def login(request: Request, body: LoginRequest) -> JSONResponse:
    """Login with email and password."""
    ip = _get_client_ip(request)
    with SessionLocal() as session:
        success, message, token = auth_service.login(
            session,
            email_or_username=body.email,
            password=body.password,
            ip_address=ip,
            user_agent=request.headers.get("User-Agent"),
        )
        if not success or token is None:
            raise HTTPException(status_code=401, detail=message)

        user = auth_service.validate_token(session, token)
        if user is None:
            raise HTTPException(status_code=401, detail="Nie udalo sie odczytac sesji uzytkownika")

        response = JSONResponse({"success": True, "user": serialize_user(user)})
        _set_session_cookie(response, token)
        return response


def _set_session_cookie(response: JSONResponse, token: str) -> None:
    _secure = os.getenv("FORCE_HTTPS", "").lower() in ("1", "true")
    response.set_cookie(
        key="session_token",
        value=token,
        httponly=True,
        secure=_secure,
        max_age=24 * 3600,
        samesite="strict" if _secure else "lax",
    )


@app.post("/api/auth/logout")
async def logout(session_token: Optional[str] = Cookie(None)) -> JSONResponse:
    """Logout current user."""
    if session_token:
        with SessionLocal() as session:
            auth_service.logout(session, session_token)
    
    response = JSONResponse({"success": True})
    response.delete_cookie(key="session_token")
    return response


@app.get("/api/auth/me")
async def get_me(session_token: Optional[str] = Cookie(None)) -> JSONResponse:
    """Get current logged in user."""
    user = await get_current_user(session_token)
    if not user:
        return JSONResponse({"authenticated": False, "user": None})
    
    return JSONResponse({
        "authenticated": True,
        "user": serialize_user(user),
    })


@app.post("/api/user/trading-mode")
async def set_trading_mode(request: Request, user: User = Depends(require_auth)) -> JSONResponse:
    """Toggle user's trading mode between PAPER and LIVE."""
    body = await request.json()
    mode = str(body.get("mode", "PAPER")).upper()
    if mode not in ("PAPER", "LIVE"):
        return JSONResponse({"ok": False, "error": "Tryb musi byc PAPER lub LIVE"}, status_code=400)

    ip = _get_client_ip(request)
    with SessionLocal() as session:
        db_user = session.get(User, user.id)
        if db_user is None:
            return JSONResponse({"ok": False, "error": "Nie znaleziono uzytkownika"}, status_code=404)

        if mode == "LIVE":
            keys = api_key_service.get_user_api_keys(session, user.id)
            trade_key = next(
                (k for k in keys if k.is_active and not k.is_testnet),
                None,
            )
            if trade_key is None:
                return JSONResponse(
                    {"ok": False, "error": "Brak klucza API Binance. Dodaj klucz w Ustawieniach."},
                    status_code=400,
                )
            # Auto-test Binance permissions and upgrade local record
            api_secret = api_key_service.get_decrypted_secret(trade_key)
            if api_secret:
                client = binance_service.get_client(trade_key.api_key, api_secret, trade_key.is_testnet)
                account = client.get_account()
                if isinstance(account, dict) and account.get("canTrade"):
                    trade_key.permissions = "trade"
                    session.flush()
                else:
                    return JSONResponse(
                        {"ok": False, "error": "Klucz API nie ma uprawnien do handlu. Wlacz 'Handel Spot' na Binance."},
                        status_code=400,
                    )

        db_user.trading_mode = mode
        session.add(AuditLog(user_id=user.id, action="trading_mode_changed", resource=mode, ip_address=ip))
        session.commit()

    return JSONResponse({"ok": True, "trading_mode": mode})


@app.post("/api/user/live-allocation")
async def set_live_allocation(request: Request, user: User = Depends(require_auth)) -> JSONResponse:
    """Set how much of Binance balance the agent can use per trade."""
    body = await request.json()
    mode = str(body.get("mode", "percent")).lower()
    value = float(body.get("value", 10.0))
    if mode not in ("percent", "fixed", "max"):
        return JSONResponse({"ok": False, "error": "Tryb musi byc: percent, fixed lub max"}, status_code=400)
    if mode == "percent" and (value < 1 or value > 100):
        return JSONResponse({"ok": False, "error": "Procent musi byc od 1 do 100"}, status_code=400)
    if mode == "fixed" and value < 1:
        return JSONResponse({"ok": False, "error": "Kwota musi byc wieksza niz 0"}, status_code=400)

    with SessionLocal() as session:
        db_user = session.get(User, user.id)
        if db_user is None:
            return JSONResponse({"ok": False, "error": "Nie znaleziono uzytkownika"}, status_code=404)
        db_user.live_alloc_mode = mode
        db_user.live_alloc_value = value
        session.commit()

    return JSONResponse({"ok": True, "live_alloc_mode": mode, "live_alloc_value": value})


# ============== API KEY MANAGEMENT ==============

@app.get("/api/keys")
async def list_api_keys(user: User = Depends(require_auth)) -> JSONResponse:
    """List user's API keys (secrets are masked)."""
    with SessionLocal() as session:
        keys = api_key_service.get_user_api_keys(session, user.id)
        return JSONResponse({
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


@app.post("/api/keys")
@limiter.limit("10/minute")
async def add_api_key(request: Request, body: AddAPIKeyRequest, user: User = Depends(require_auth)) -> JSONResponse:
    """Add a new API key."""
    ip = _get_client_ip(request)
    with SessionLocal() as session:
        label = body.label or f"{body.exchange.upper()} {body.api_key[:4]}"
        success, message, api_key_obj = api_key_service.add_api_key(
            session,
            user_id=user.id,
            label=label,
            exchange=body.exchange,
            api_key=body.api_key,
            api_secret=body.api_secret,
            is_testnet=body.is_testnet,
            permissions=body.permissions,
            ip_address=ip,
        )
        if not success or api_key_obj is None:
            raise HTTPException(status_code=400, detail=message)
        return JSONResponse({"success": True, "key_id": api_key_obj.id})


@app.delete("/api/keys/{key_id}")
async def delete_api_key(key_id: int, user: User = Depends(require_auth)) -> JSONResponse:
    """Delete an API key."""
    with SessionLocal() as session:
        deleted = api_key_service.delete_api_key(session, user_id=user.id, key_id=key_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="Klucz API nie znaleziony")
        return JSONResponse({"success": True})


# ============== BINANCE API ENDPOINTS ==============

@app.get("/api/binance/test")
async def test_binance_connection(key_id: int, user: User = Depends(require_auth)) -> JSONResponse:
    """Test Binance API connection with specified key."""
    with SessionLocal() as session:
        selected_key, client = get_user_binance_client(session, user.id, key_id)
        if selected_key is None:
            raise HTTPException(status_code=404, detail="Klucz API nie znaleziony")
        if client is None:
            raise HTTPException(status_code=500, detail="Błąd odszyfrowywania klucza")

        success, message = client.test_connection()
        return JSONResponse({
            "success": success,
            "message": message,
            "key_label": selected_key.label,
            "is_testnet": selected_key.is_testnet,
        })


@app.get("/api/binance/account")
async def get_binance_account(key_id: int, user: User = Depends(require_auth)) -> JSONResponse:
    """Get Binance account information."""
    with SessionLocal() as session:
        selected_key, client = get_user_binance_client(session, user.id, key_id)
        if selected_key is None:
            raise HTTPException(status_code=404, detail="Klucz API nie znaleziony")
        if client is None:
            raise HTTPException(status_code=500, detail="Błąd odszyfrowywania klucza")

        result = client.get_account()
        if "error" in result:
            logger.warning("Binance account error for user %s: %s", user.id, result["error"])
            raise HTTPException(status_code=400, detail="Nie udało się pobrać danych konta. Sprawdź klucz API.")
        return JSONResponse(result)


@app.get("/api/binance/balances")
async def get_binance_balances(key_id: int, user: User = Depends(require_auth)) -> JSONResponse:
    """Get non-zero Binance balances."""
    with SessionLocal() as session:
        selected_key, client = get_user_binance_client(session, user.id, key_id)
        if selected_key is None:
            raise HTTPException(status_code=404, detail="Klucz API nie znaleziony")
        if client is None:
            raise HTTPException(status_code=500, detail="Błąd odszyfrowywania klucza")

        balances = client.get_balances()
        if balances and isinstance(balances[0], dict) and "error" in balances[0]:
            logger.warning("Binance balances error for user %s: %s", user.id, balances[0]["error"])
            raise HTTPException(status_code=400, detail="Nie udało się pobrać sald. Sprawdź klucz API.")
        return JSONResponse({"balances": balances})


@app.get("/api/binance/portfolio")
async def get_binance_portfolio(key_id: int, user: User = Depends(require_auth)) -> JSONResponse:
    """Get Binance portfolio value in USDT."""
    with SessionLocal() as session:
        selected_key, client = get_user_binance_client(session, user.id, key_id)
        if selected_key is None:
            raise HTTPException(status_code=404, detail="Klucz API nie znaleziony")
        if client is None:
            raise HTTPException(status_code=500, detail="Błąd odszyfrowywania klucza")

        portfolio = client.get_portfolio_value()
        if "error" in portfolio:
            logger.warning("Binance portfolio error for user %s: %s", user.id, portfolio["error"])
            raise HTTPException(status_code=400, detail="Nie udało się pobrać portfela. Sprawdź klucz API.")

        return JSONResponse({
            "total_value_usdt": portfolio["total_value"],
            "quote_currency": portfolio["quote_currency"],
            "holdings": portfolio["holdings"],
        })


@app.get("/api/binance/leverage-check")
async def check_leverage(user: User = Depends(require_auth)) -> JSONResponse:
    """Check if margin/leverage trading is available on user's Binance account."""
    with SessionLocal() as session:
        _, client = get_user_binance_client(session, user.id)
        if client is None:
            return JSONResponse({
                "leverage_available": False,
                "reason": "Brak klucza API Binance. Dodaj klucz w Ustawieniach.",
            })
        result = client.check_margin_available()
        return JSONResponse(result)


@app.get("/api/binance/dust")
async def get_dust_assets(user: User = Depends(require_auth)) -> JSONResponse:
    """Get small balances eligible for conversion to BNB."""
    with SessionLocal() as session:
        _, client = get_user_binance_client(session, user.id)
        if client is None:
            return JSONResponse({"error": "Brak klucza API Binance."}, status_code=400)
        assets = client.get_dust_assets()
        return JSONResponse({"assets": assets})


@app.post("/api/binance/dust/convert")
@limiter.limit("5/minute")
async def convert_dust(request: Request, user: User = Depends(require_auth)) -> JSONResponse:
    """Convert small balances (dust) to BNB."""
    with SessionLocal() as session:
        _, client = get_user_binance_client(session, user.id)
        if client is None:
            return JSONResponse({"error": "Brak klucza API Binance."}, status_code=400)
        dust_list = client.get_dust_assets()
        if not dust_list:
            return JSONResponse({"error": "Brak malych kwot do konwersji."}, status_code=400)
        asset_names = [d["asset"] for d in dust_list]
        result = client.convert_dust_to_bnb(asset_names)
        if isinstance(result, dict) and "error" in result:
            return JSONResponse({"error": result["error"]}, status_code=400)
        transferred = result.get("totalTransfered", result.get("totalTransferred", 0))
        transfer_results = result.get("transferResult", [])
        return JSONResponse({
            "ok": True,
            "total_bnb": float(transferred),
            "converted_count": len(transfer_results),
            "details": transfer_results,
        })


# ============== LEVERAGE PAPER TRADING ==============

@app.get("/api/leverage/snapshot")
async def leverage_snapshot_api() -> JSONResponse:
    """Get leverage paper trading snapshot."""
    with SessionLocal() as session:
        return JSONResponse(leverage_engine.get_snapshot(session))


@app.get("/api/leverage/perp/{symbol}")
async def leverage_perp_data(symbol: str) -> JSONResponse:
    """Get Bybit perpetual market data for a symbol (public, no auth)."""
    from app.services.bybit_market import get_perp_snapshot
    data = get_perp_snapshot(symbol.upper())
    if data is None:
        raise HTTPException(status_code=404, detail=f"Brak danych perpetual dla {symbol}")
    return JSONResponse(data)


@app.get("/api/leverage/chart/{symbol}")
async def leverage_chart_api(symbol: str, interval: str = "60", limit: int = 200) -> JSONResponse:
    """Bybit perpetual klines + leverage agent markers + funding overlay."""
    from app.services.bybit_market import get_perp_klines, get_perp_ticker, get_funding_history
    sym = symbol.upper()

    klines = get_perp_klines(sym, interval=interval, limit=min(int(limit), 200))
    if not klines:
        raise HTTPException(status_code=404, detail=f"Brak danych klines dla {sym}")

    # Ticker for current funding info
    ticker = get_perp_ticker(sym) or {}

    # Funding history for overlay
    funding = get_funding_history(sym, limit=50)

    # Leverage trade markers from DB
    with SessionLocal() as session:
        from app.models import LeverageSimTrade
        trades = session.execute(
            select(LeverageSimTrade)
            .where(LeverageSimTrade.symbol == sym)
            .order_by(desc(LeverageSimTrade.opened_at))
            .limit(50)
        ).scalars().all()

        markers = []
        for t in trades:
            # Entry marker
            markers.append({
                "time": int(t.opened_at.timestamp()),
                "type": "entry",
                "side": t.side,
                "leverage": t.leverage,
                "price": t.entry_price,
                "score": t.decision_score,
                "reason": (t.decision_reason or "")[:120],
            })
            # Exit marker
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

        # Open positions for price lines
        open_positions = session.execute(
            select(LeverageSimTrade)
            .where(LeverageSimTrade.symbol == sym, LeverageSimTrade.status == "OPEN")
        ).scalars().all()
        positions = [{
            "side": p.side,
            "entry_price": p.entry_price,
            "liquidation_price": p.liquidation_price,
            "take_profit": p.take_profit,
            "stop_loss": p.stop_loss,
            "leverage": p.leverage,
            "margin_used": p.margin_used,
        } for p in open_positions]

    return JSONResponse({
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


# ============== BYBIT API ENDPOINTS ==============

@app.get("/api/bybit/test")
async def test_bybit_connection(key_id: int, user: User = Depends(require_auth)) -> JSONResponse:
    """Test Bybit API connection with specified key."""
    with SessionLocal() as session:
        selected_key, client = get_user_bybit_client(session, user.id, key_id)
        if selected_key is None:
            raise HTTPException(status_code=404, detail="Klucz API Bybit nie znaleziony")
        if client is None:
            raise HTTPException(status_code=500, detail="Błąd odszyfrowywania klucza")

        success, message = client.test_connection()
        return JSONResponse({
            "success": success,
            "message": message,
            "key_label": selected_key.label,
            "is_testnet": selected_key.is_testnet,
        })


@app.get("/api/bybit/portfolio")
async def get_bybit_portfolio(key_id: int, user: User = Depends(require_auth)) -> JSONResponse:
    """Get Bybit portfolio value (wallet + positions)."""
    with SessionLocal() as session:
        selected_key, client = get_user_bybit_client(session, user.id, key_id)
        if selected_key is None:
            raise HTTPException(status_code=404, detail="Klucz API Bybit nie znaleziony")
        if client is None:
            raise HTTPException(status_code=500, detail="Błąd odszyfrowywania klucza")

        portfolio = client.get_portfolio_value()
        if "error" in portfolio:
            logger.warning("Bybit portfolio error for user %s: %s", user.id, portfolio["error"])
            raise HTTPException(status_code=400, detail="Nie udało się pobrać portfela Bybit.")
        return JSONResponse(portfolio)


@app.get("/api/bybit/positions")
async def get_bybit_positions(user: User = Depends(require_auth)) -> JSONResponse:
    """Get open Bybit perpetual positions."""
    with SessionLocal() as session:
        _, client = get_user_bybit_client(session, user.id)
        if client is None:
            return JSONResponse({"positions": []})
        positions = client.get_open_positions_summary()
        return JSONResponse({"positions": positions})


@app.get("/api/bybit/leverage/{symbol}")
async def get_bybit_leverage_info(symbol: str, user: User = Depends(require_auth)) -> JSONResponse:
    """Get leverage info for a Bybit symbol."""
    with SessionLocal() as session:
        _, client = get_user_bybit_client(session, user.id)
        if client is None:
            raise HTTPException(status_code=400, detail="Brak klucza API Bybit.")
        info = client.get_leverage_info(symbol)
        if "error" in info:
            raise HTTPException(status_code=400, detail=info["error"])
        return JSONResponse(info)


@app.post("/api/bybit/leverage/{symbol}")
@limiter.limit("10/minute")
async def set_bybit_leverage(request: Request, symbol: str, user: User = Depends(require_auth)) -> JSONResponse:
    """Set leverage for a Bybit symbol."""
    body = await request.json()
    leverage = str(body.get("leverage", "1"))
    with SessionLocal() as session:
        _, client = get_user_bybit_client(session, user.id)
        if client is None:
            raise HTTPException(status_code=400, detail="Brak klucza API Bybit.")
        result = client.set_leverage(symbol, leverage, leverage)
        if "error" in result:
            raise HTTPException(status_code=400, detail=result["error"])
        return JSONResponse({"success": True, "symbol": symbol, "leverage": leverage})


@app.post("/api/bybit/trade")
@limiter.limit("10/minute")
async def place_bybit_trade(request: Request, user: User = Depends(require_auth)) -> JSONResponse:
    """Place a trade on Bybit (spot or linear perpetual)."""
    body = await request.json()
    symbol = body.get("symbol")
    side = body.get("side")  # Buy / Sell
    order_type = body.get("order_type", "Market")  # Market / Limit
    qty = str(body.get("qty", "0"))
    category = body.get("category", "linear")
    price = body.get("price")
    leverage = body.get("leverage")
    take_profit = body.get("take_profit")
    stop_loss = body.get("stop_loss")
    reduce_only = body.get("reduce_only", False)

    if not symbol or not side or float(qty) <= 0:
        raise HTTPException(status_code=400, detail="Brak wymaganych pól: symbol, side, qty")

    with SessionLocal() as session:
        _, client = get_user_bybit_client(session, user.id)
        if client is None:
            raise HTTPException(status_code=400, detail="Brak klucza API Bybit.")

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
            raise HTTPException(status_code=400, detail=result["error"])
        return JSONResponse({"success": True, "order": result})


@app.get("/api/bybit/orders")
async def get_bybit_orders(user: User = Depends(require_auth), category: str = "linear") -> JSONResponse:
    """Get open Bybit orders."""
    with SessionLocal() as session:
        _, client = get_user_bybit_client(session, user.id)
        if client is None:
            return JSONResponse({"orders": []})
        orders = client.get_open_orders(category)
        if "error" in orders:
            return JSONResponse({"orders": []})
        return JSONResponse({"orders": orders.get("list", [])})


@app.get("/api/bybit/history")
async def get_bybit_trade_history(user: User = Depends(require_auth), category: str = "linear", limit: int = 50) -> JSONResponse:
    """Get Bybit closed P&L history — used for agent learning."""
    with SessionLocal() as session:
        _, client = get_user_bybit_client(session, user.id)
        if client is None:
            return JSONResponse({"history": []})
        history = client.get_trading_history(category, min(limit, 100))
        return JSONResponse({"history": history})