from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import desc, func, select

from app.config import settings
from app.database import SessionLocal, init_db
from app.models import Decision, FeatureSnapshot, MarketData, OpenAIUsageLog, SimulatedTrade
from app.services.agent_cycle import AgentCycle
from app.services.ai_advisor import AIAdvisor
from app.services.backtest import BacktestService
from app.services.currency_service import CurrencyService
from app.services.learning_center import LearningCenter
from app.services.market_data import LiveQuoteService, load_latest_market_row
from app.services.runtime_state import RuntimeStateService
from app.services.scheduler import SchedulerService
from app.services.wallet import WalletService


app = FastAPI(title=settings.app_name)
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
    with SessionLocal() as session:
        existing_market = session.execute(select(MarketData.id).limit(1)).scalar_one_or_none()
        existing_decision = session.execute(select(Decision.id).limit(1)).scalar_one_or_none()
        if existing_market is None or existing_decision is None:
            cycle_runner.run(session)
    if settings.scheduler_enabled:
        scheduler_service.start()


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
def dashboard() -> JSONResponse:
    scheduler_service.ensure_running()
    with SessionLocal() as session:
        return JSONResponse(_build_dashboard_payload(session), headers=no_cache_headers())


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
def ai_insight(symbol: str | None = None) -> JSONResponse:
    with SessionLocal() as session:
        dashboard_payload = _build_dashboard_payload(session, include_chart_package=True, chart_focus_symbol=symbol)
        result = ai_advisor.generate_market_brief(session, dashboard_payload, symbol=symbol)
    return JSONResponse(result)


@app.post("/api/agent-mode/{mode}")
def set_agent_mode(mode: str) -> JSONResponse:
    with SessionLocal() as session:
        try:
            selected_mode = runtime_state.set_agent_mode(session, mode)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        payload = _build_dashboard_payload(session)
    return JSONResponse({"mode": selected_mode, "dashboard": payload})


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


def _build_dashboard_payload(session, include_chart_package: bool = False, chart_focus_symbol: str | None = None) -> dict[str, object]:
    active_profile = runtime_state.get_active_profile(session)
    display_currency = runtime_state.get_display_currency(session)
    usd_to_display_rate, rate_source = currency_service.get_rate(settings.quote_currency, display_currency)
    market_rows: list[dict[str, object]] = []
    chart_packages: dict[str, dict[str, object]] = {}
    for symbol in settings.tracked_symbols:
        market = load_latest_market_row(session, symbol)
        feature = session.execute(
            select(FeatureSnapshot).where(FeatureSnapshot.symbol == symbol).order_by(FeatureSnapshot.timestamp.desc())
        ).scalars().first()
        decision = session.execute(
            select(Decision).where(Decision.symbol == symbol).order_by(Decision.timestamp.desc())
        ).scalars().first()
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
    system_status = {
        "scheduler": scheduler_service.status(),
        "trading_mode": settings.trading_mode,
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
                f"USDT_{display_currency}": usd_to_display_rate,
            },
            "display_rate_source": rate_source,
            "tracked_symbols": settings.tracked_symbols,
            "symbol_groups": settings.symbol_groups,
            "agent_mode_profiles": settings.agent_mode_profiles,
            "start_balance": settings.starting_balance_quote,
            "fee_rate": settings.fee_rate,
            "slippage": settings.slippage,
            "trading_mode": settings.trading_mode,
            "learning_mode": settings.learning_mode,
            "preferred_trade_quotes": settings.preferred_trade_quotes,
            "dashboard_refresh_seconds": settings.dashboard_refresh_seconds,
            "live_quote_cache_seconds": settings.live_quote_cache_seconds,
        },
    }