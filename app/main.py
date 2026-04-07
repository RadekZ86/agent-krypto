from __future__ import annotations

import logging
import os
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


def _get_client_ip(request: Request) -> str:
    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        return forwarded.split(",")[0].strip()[:45]
    real_ip = request.headers.get("X-Real-IP", "")
    if real_ip:
        return real_ip[:45]
    return (request.client.host if request.client else "unknown")[:45]

    return selected_key, binance_service.get_client(
        api_key=selected_key.api_key,
        api_secret=api_secret,
        testnet=selected_key.is_testnet,
    )


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
def chart_package(symbol: str) -> JSONResponse:
    if symbol not in settings.tracked_symbols:
        raise HTTPException(status_code=404, detail=f"Nieznany symbol: {symbol}")
    with SessionLocal() as session:
        payload = learning_center.build_chart_package(session, symbol)
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
        )
        result = ai_advisor.chat(
            session,
            user_message=body.message,
            dashboard=dashboard_payload,
            conversation_history=body.history,
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
                    session.add(LiveOrderLog(
                        username=user.username, symbol=symbol, action="BUY", status="ok",
                        detail=f"Czat: kupiono za {round(alloc, 2)} {quote}",
                        order_id=str(result.get("orderId", "")), allocation=round(alloc, 4), quote_currency=quote,
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
                    detail_msg = f"Czat: sprzedano {round(qty_floored, 6)} {symbol}"
                    if earn_redeemed:
                        detail_msg += " (po odkupieniu z Earn)"
                    session.add(LiveOrderLog(
                        username=user.username, symbol=symbol, action="SELL", status="ok",
                        detail=detail_msg,
                        order_id=str(result.get("orderId", "")), allocation=round(qty_floored, 6), quote_currency=quote,
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
        market_rows.append(
            {
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
            }
        )

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
        "binance_private_ready": bool(settings.binance_api_key and settings.binance_api_secret),
        "quote_currency": settings.quote_currency,
        "display_currency": display_currency,
        "max_trades_per_day": active_profile["max_trades_per_day"],
        "max_open_positions": active_profile["max_open_positions"],
        "preferred_trade_quotes": settings.preferred_trade_quotes,
        "live_alloc_mode": user_alloc_mode,
        "live_alloc_value": user_alloc_value,
    }

    private_learning = None
    trade_ranking = None
    binance_wallet = None
    live_portfolio = None
    if current_user is not None:
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
                    # Try PLN first (Binance PL), then configured exchange quote, then USDT
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