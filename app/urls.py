from django.urls import path

from app import views

urlpatterns = [
    # Dashboard
    path('', views.index, name='index'),
    path('api/dashboard', views.dashboard, name='dashboard'),
    path('api/chart-package', views.chart_package, name='chart_package'),
    path('api/chart-history', views.chart_history, name='chart_history'),
    path('api/calendar', views.calendar_data, name='calendar_data'),

    # Agent cycle
    path('api/run-cycle', views.run_cycle, name='run_cycle'),
    path('api/backtest', views.backtest, name='backtest'),

    # Scheduler
    path('api/scheduler/start', views.scheduler_start, name='scheduler_start'),
    path('api/scheduler/stop', views.scheduler_stop, name='scheduler_stop'),

    # Risk + learning insights
    path('api/risk-status', views.risk_status, name='risk_status'),
    path('api/learning-insights', views.learning_insights, name='learning_insights'),

    # AI
    path('api/ai-insight', views.ai_insight, name='ai_insight'),
    path('api/agent-chat', views.agent_chat, name='agent_chat'),
    path('api/agent-chat/execute', views.agent_chat_execute, name='agent_chat_execute'),

    # Agent mode
    path('api/agent-mode/<str:mode>', views.set_agent_mode, name='set_agent_mode'),

    # Paper trading
    path('api/paper/reset', views.reset_paper_portfolio, name='reset_paper_portfolio'),

    # Auth
    path('api/auth/register', views.register, name='register'),
    path('api/auth/login', views.login_view, name='login'),
    path('api/auth/logout', views.logout_view, name='logout'),
    path('api/auth/me', views.get_me, name='get_me'),

    # User settings
    path('api/user/trading-mode', views.set_trading_mode, name='set_trading_mode'),
    path('api/user/live-allocation', views.set_live_allocation, name='set_live_allocation'),

    # API keys
    path('api/keys', views.list_api_keys, name='list_api_keys'),
    path('api/keys/<int:key_id>', views.delete_api_key, name='delete_api_key'),

    # Binance
    path('api/binance/test', views.test_binance_connection, name='test_binance'),
    path('api/binance/account', views.get_binance_account, name='binance_account'),
    path('api/binance/balances', views.get_binance_balances, name='binance_balances'),
    path('api/binance/portfolio', views.get_binance_portfolio, name='binance_portfolio'),
    path('api/binance/leverage-check', views.check_leverage, name='binance_leverage_check'),
    path('api/binance/dust', views.get_dust_assets, name='binance_dust'),
    path('api/binance/dust/convert', views.convert_dust, name='binance_dust_convert'),

    # Leverage paper trading
    path('api/leverage/snapshot', views.leverage_snapshot_api, name='leverage_snapshot'),
    path('api/leverage/perp/<str:symbol>', views.leverage_perp_data, name='leverage_perp'),
    path('api/leverage/chart/<str:symbol>', views.leverage_chart_api, name='leverage_chart'),

    # Bybit
    path('api/bybit/test', views.test_bybit_connection, name='bybit_test'),
    path('api/bybit/portfolio', views.get_bybit_portfolio, name='bybit_portfolio'),
    path('api/bybit/positions', views.get_bybit_positions, name='bybit_positions'),
    path('api/bybit/leverage/<str:symbol>', views.get_bybit_leverage_info, name='bybit_leverage_info'),
    path('api/bybit/trade', views.place_bybit_trade, name='bybit_trade'),
    path('api/bybit/orders', views.get_bybit_orders, name='bybit_orders'),
    path('api/bybit/history', views.get_bybit_trade_history, name='bybit_history'),
]

# POST for add_api_key shares the same path as list_api_keys (GET)
# Handle both methods on the same URL
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods


@csrf_exempt
@require_http_methods(["GET", "POST"])
def api_keys_dispatch(request):
    if request.method == "GET":
        return views.list_api_keys(request)
    return views.add_api_key(request)


# Replace the two separate paths with a single dispatch
urlpatterns = [p for p in urlpatterns if p.pattern._route != 'api/keys']
urlpatterns.append(path('api/keys', api_keys_dispatch, name='api_keys'))

# Bybit leverage GET/POST on same path
@csrf_exempt
@require_http_methods(["GET", "POST"])
def bybit_leverage_dispatch(request, symbol: str):
    if request.method == "GET":
        return views.get_bybit_leverage_info(request, symbol)
    return views.set_bybit_leverage(request, symbol)

urlpatterns = [p for p in urlpatterns if p.pattern._route != 'api/bybit/leverage/<str:symbol>']
urlpatterns.append(path('api/bybit/leverage/<str:symbol>', bybit_leverage_dispatch, name='bybit_leverage'))
