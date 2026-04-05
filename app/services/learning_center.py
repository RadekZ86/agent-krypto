from __future__ import annotations

from datetime import date
from datetime import datetime, timedelta
from statistics import mean
from typing import Any

import requests
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Decision, LearningLog, SimulatedTrade
from app.services.analysis_frame import build_indicator_frame
from app.services.market_data import load_symbol_market_rows
from app.services.probability_engine import ProbabilityEngine

_MISS = object()  # sentinel for cache miss


LEARNING_ARTICLES = [
    {
        "title": "RSI: jak czytac momentum bez zgadywania dna",
        "source": "Investopedia",
        "url": "https://www.investopedia.com/terms/r/rsi.asp",
        "summary": "RSI najlepiej dziala razem z trendem. Poziomy 30 i 70 nie sa magiczne, a w silnych trendach trzeba czytac RSI kontekstowo i szukac potwierdzenia z EMA lub MACD.",
        "focus": ["RSI", "trend context", "divergence"],
    },
    {
        "title": "MACD: momentum, crossovers i falszywe sygnaly",
        "source": "Investopedia",
        "url": "https://www.investopedia.com/terms/m/macd.asp",
        "summary": "MACD pokazuje relacje miedzy EMA 12 i EMA 26. Sam crossover nie wystarcza, bo w konsolidacji potrafi generowac falszywe wejscia, wiec trzeba go laczyc z trendem i wolumenem.",
        "focus": ["MACD", "crossovers", "trend confirmation"],
    },
    {
        "title": "Day trading: plan, testy i dziennik decyzji",
        "source": "Investopedia",
        "url": "https://www.investopedia.com/articles/trading/06/daytradingretail.asp",
        "summary": "Kluczowe sa plan wejsc, wyjsc i limit ryzyka. Strategia powinna przejsc backtest, paper trading i regularny przeglad wynikow zanim dostanie realny kapital.",
        "focus": ["paper trading", "backtest", "journal"],
    },
    {
        "title": "Zasady dyscypliny: nie gon trendu, trzymaj plan",
        "source": "Investopedia",
        "url": "https://www.investopedia.com/articles/trading/10/top-ten-rules-for-trading.asp",
        "summary": "Najwiekszym przeciwnikiem systemu jest impulsywna zmiana zasad. Strategia potrzebuje z gory ustalonych warunkow wyjscia, kontroli emocji i przygotowania na zmiennosc.",
        "focus": ["discipline", "exit rules", "volatility"],
    },
    {
        "title": "Risk management in crypto trading",
        "source": "Binance Academy",
        "url": "https://www.binance.com/en/academy/articles/risk-management-in-crypto-trading",
        "summary": "Rozmiar pozycji, stop loss, relacja zysk/ryzyko i ograniczanie ekspozycji do jednego aktywa to podstawa przejscia z eksperymentu do stabilnego procesu.",
        "focus": ["position sizing", "stop loss", "risk-reward"],
    },
    {
        "title": "Support and resistance basics for crypto",
        "source": "Binance Academy",
        "url": "https://www.binance.com/en/academy/articles/support-and-resistance-explained",
        "summary": "Strefy wsparcia i oporu sa bardziej uzyteczne niz pojedyncza linia. Agent powinien uczyc sie reakcji ceny wokol tych stref i patrzec, czy pojawia sie obrona wolumenowa.",
        "focus": ["support", "resistance", "price reaction"],
    },
    {
        "title": "Candlestick patterns without overfitting",
        "source": "Investopedia",
        "url": "https://www.investopedia.com/trading/candlestick-charting-what-is-it/",
        "summary": "Swiece sa przydatne dopiero w kontekscie trendu, wolumenu i poziomow. Agent nie powinien uczyc sie pojedynczych formacji bez potwierdzenia z otoczenia rynkowego.",
        "focus": ["candles", "context", "confirmation"],
    },
    {
        "title": "Volume analysis: when participation matters",
        "source": "Investopedia",
        "url": "https://www.investopedia.com/articles/technical/02/010702.asp",
        "summary": "Wybicia bez wolumenu czesto wygasaja. Agent powinien porownywac swieze ruchy ceny z przyspieszeniem obrotu, a nie tylko z samym kierunkiem swiecy.",
        "focus": ["volume", "breakout", "participation"],
    },
    {
        "title": "How to use moving averages in trend regimes",
        "source": "Binance Academy",
        "url": "https://www.binance.com/en/academy/articles/a-guide-to-the-most-common-technical-indicators",
        "summary": "EMA i SMA najlepiej dzialaja jako filtr reżimu. Agent powinien rozroznic trend, konsolidacje i moment przejscia, zamiast traktowac srednie jako samotny trigger.",
        "focus": ["EMA", "regime", "trend filter"],
    },
    {
        "title": "Trading journal: from intuition to measurable process",
        "source": "Coinbase Learn",
        "url": "https://www.coinbase.com/learn/crypto-basics/what-is-risk-management",
        "summary": "Sam wynik transakcji nie wystarcza. Agent powinien zapisywac setup, kontekst, confidence, powod wejscia i powod wyjscia, zeby po czasie zobaczyc, co dziala naprawde.",
        "focus": ["journal", "process", "review"],
    },
    {
        "title": "Drawdown management for volatile assets",
        "source": "Binance Academy",
        "url": "https://www.binance.com/en/academy/articles/what-is-a-stop-loss-order",
        "summary": "Ochrona kapitalu jest wazniejsza niz maksymalizacja pojedynczego trade'u. Agent powinien mierzyc serie strat, drawdown i czas potrzebny do odrobienia kapitalu.",
        "focus": ["drawdown", "stop loss", "capital preservation"],
    },
    {
        "title": "Market structure: higher highs, lower lows and invalidation",
        "source": "Binance Academy",
        "url": "https://www.binance.com/en/academy/articles/what-is-support-and-resistance",
        "summary": "Struktura rynku pomaga odroznic trend od szumu. Agent powinien rozpoznawac wybicie poprzedniego szczytu, utrate lokalnego dolka i miejsca invalidation setupu.",
        "focus": ["market structure", "break of structure", "invalidation"],
    },
    {
        "title": "Position sizing for systematic trading",
        "source": "Investopedia",
        "url": "https://www.investopedia.com/articles/active-trading/091814/position-sizing-importance-trading.asp",
        "summary": "Wielkosc pozycji ma wiekszy wplyw na przetrwanie systemu niz pojedynczy trigger wejscia. Agent powinien traktowac sizing jako osobna decyzje, nie dodatek do BUY/SELL.",
        "focus": ["position sizing", "risk budget", "survival"],
    },
    {
        "title": "False breakouts and liquidity grabs",
        "source": "Cointelegraph Learn",
        "url": "https://cointelegraph.com/learn/articles/what-is-a-bull-trap-and-how-to-avoid-it",
        "summary": "Nie kazde wybicie ma follow-through. Agent powinien obserwowac, czy cena utrzymuje poziom po wybiciu i czy rosnacy wolumen nie gasnie natychmiast po impulsie.",
        "focus": ["false breakout", "bull trap", "liquidity"],
    },
    {
        "title": "Trend pullback entries instead of chasing green candles",
        "source": "Binance Academy",
        "url": "https://www.binance.com/en/academy/articles/how-to-use-stop-limit-orders-on-binance",
        "summary": "Najgorsze wejscia czesto pojawiaja sie po gonieniu swiecy. Agent powinien preferowac cofniecia do strefy wartosci i szukac potwierdzenia zamiast wejsc na emocji.",
        "focus": ["pullback", "entry quality", "discipline"],
    },
]


KNOWLEDGE_BASE = [
    {
        "title": "Playbook 1: trend continuation",
        "description": "Kupuj tylko wtedy, gdy cena broni EMA20 nad EMA50, MACD jest dodatni lub rosnie, a wolumen nie slabnie. Uczenie: odrozniaj zdrowy trend od przegrzanego po wybiciu.",
    },
    {
        "title": "Playbook 2: mean reversion",
        "description": "Szukaj tylko kontrolowanych cofniec do wsparcia przy niskim RSI i bez paniki wolumenowej. Uczenie: nie lap spadajacego noza w pelnym trendzie DOWN.",
    },
    {
        "title": "Playbook 3: breakout validation",
        "description": "Wybicie ma sens dopiero po wyjsciu nad opor z ponadprzecietnym wolumenem i utrzymaniem ceny nad poziomem. Uczenie: rozpoznawaj falszywe wybicia i szybkie powroty pod opor.",
    },
    {
        "title": "Playbook 4: exit discipline",
        "description": "Wyjscie ma byc planowane przed wejsciem: gdzie bierzesz profit, gdzie tniesz strate i kiedy redukujesz pozycje. Uczenie: nie pozwalaj, by wygrany trade zamienial sie w strate.",
    },
    {
        "title": "Playbook 5: market regime",
        "description": "Agent powinien odroznic trend wzrostowy, spadkowy i boczny. Ten sam sygnal RSI/MACD ma inne znaczenie w kazdym z tych srodowisk.",
    },
    {
        "title": "Playbook 6: portfolio context",
        "description": "Nie kupuj wielu silnie skorelowanych coinow naraz. Uczenie: ekspozycja na jeden motyw rynku moze zwiekszyc ryzyko bardziej niz liczba pozycji.",
    },
    {
        "title": "Playbook 7: structure break",
        "description": "Silny BUY ma wieksza wartosc, gdy cena wybija poprzedni swing high i utrzymuje poziom. Uczenie: odrozniaj prawdziwa zmiane struktury od jednorazowego piku.",
    },
    {
        "title": "Playbook 8: failed breakout",
        "description": "Jesli wybicie wraca szybko pod poziom, agent powinien obnizyc zaufanie do setupu. Uczenie: nie kazde wybicie oznacza nowy trend.",
    },
    {
        "title": "Playbook 9: volatility contraction then expansion",
        "description": "Po okresie uspokojenia zmiennosci rynek czesto daje czytelniejszy impuls. Uczenie: porownuj faze sciskania z ruchem wolumenu i kierunkiem EMA.",
    },
    {
        "title": "Playbook 10: no-trade zones",
        "description": "Brak przewagi to tez decyzja. Uczenie: w srodku chaotycznej konsolidacji agent powinien preferowac HOLD zamiast wymuszac trade.",
    },
    {
        "title": "Playbook 11: scaling out",
        "description": "Nie kazdy zysk trzeba zamykac jednym ruchem. Uczenie: przy przewadze momentum mozna rozwazac czesciowa realizacje i ochrone reszty pozycji.",
    },
    {
        "title": "Playbook 12: drawdown defense",
        "description": "Po serii strat agent powinien schlodzic tempo i podniesc wymagania wejscia. Uczenie: ochrona kapitalu ma pierwszenstwo przed aktywnoscia.",
    },
]


class LearningCenter:
    PRIVATE_LEARNING_TTL = 300      # seconds (5 min)
    TRADE_RANKING_TTL = 900         # seconds (15 min)
    MARKET_SUMMARY_TTL = 120        # seconds (2 min)

    def __init__(self) -> None:
        self.probability_engine = ProbabilityEngine()
        self._lifecycle_cache: dict[str, tuple[datetime, dict[str, Any]]] = {}
        self._private_learning_cache: dict[str, tuple[float, dict[str, Any] | None]] = {}
        self._trade_ranking_cache: dict[str, tuple[float, dict[str, Any] | None]] = {}
        self._market_summary_cache: dict[str, tuple[float, dict[str, Any] | None]] = {}

    def _cache_get(self, cache: dict, key: str, ttl: int):
        """Return cached value if still fresh, otherwise None sentinel."""
        entry = cache.get(key)
        if entry is None:
            return _MISS
        ts, value = entry
        import time
        if time.time() - ts > ttl:
            return _MISS
        return value

    def build_private_learning_state(
        self,
        client,
        tracked_symbols: list[str],
        preferred_quotes: list[str] | None = None,
    ) -> dict[str, Any] | None:
        preferred_quote = (preferred_quotes or ["USDT"])[0].upper()
        cache_key = f"{getattr(client, 'api_key', '')}:{preferred_quote}"
        cached = self._cache_get(self._private_learning_cache, cache_key, self.PRIVATE_LEARNING_TTL)
        if cached is not _MISS:
            return cached
        portfolio = client.get_portfolio_value(preferred_quote)
        if not portfolio or "error" in portfolio:
            return None

        holdings = [holding for holding in portfolio.get("holdings", []) if float(holding.get("value", 0.0)) > 0]
        total_value = float(portfolio.get("total_value", 0.0) or 0.0)
        open_orders = client.get_open_orders()
        if isinstance(open_orders, dict) and "error" in open_orders:
            open_orders = []

        top_holdings = holdings[:5]
        top_weights = []
        tracked_activity: list[dict[str, Any]] = []
        trade_symbols: list[str] = []

        for holding in top_holdings:
            asset = str(holding.get("asset", "")).upper()
            value = float(holding.get("value", 0.0) or 0.0)
            weight = round((value / total_value) * 100, 2) if total_value > 0 else 0.0
            top_weights.append({
                "asset": asset,
                "value": round(value, 2),
                "weight": weight,
            })

            if asset == preferred_quote:
                continue

            pair_symbol = f"{asset}{preferred_quote}"
            trades = client.get_my_trades(pair_symbol, limit=20)
            if not isinstance(trades, list) or (trades and isinstance(trades[0], dict) and "error" in trades[0]):
                continue

            if trades:
                buy_count = sum(1 for trade in trades if trade.get("isBuyer"))
                sell_count = len(trades) - buy_count
                quote_volume = sum(float(trade.get("quoteQty", 0.0) or 0.0) for trade in trades)
                tracked_activity.append(
                    {
                        "symbol": pair_symbol,
                        "trade_count": len(trades),
                        "buy_count": buy_count,
                        "sell_count": sell_count,
                        "quote_volume": round(quote_volume, 2),
                    }
                )
                trade_symbols.append(pair_symbol)

        tracked_symbol_set = {symbol.upper() for symbol in tracked_symbols}
        tracked_holdings = [item for item in top_weights if item["asset"] in tracked_symbol_set]
        concentration = top_weights[0]["weight"] if top_weights else 0.0

        findings = []
        if top_weights:
            leader = top_weights[0]
            findings.append(f"Najwieksza ekspozycja realnego portfela to {leader['asset']} ({leader['weight']:.1f}% wartosci).")
        if concentration >= 55:
            findings.append("Portfel jest mocno skoncentrowany, wiec agent powinien ostrozniej oceniac kolejne wejscia w ten sam motyw rynku.")
        elif top_weights:
            findings.append("Portfel jest bardziej rozproszony, co daje agentowi szerszy material do nauki porownawczej miedzy aktywami.")
        if tracked_activity:
            busiest = tracked_activity[0]
            findings.append(
                f"Najwiecej prywatnej aktywnosci jest na {busiest['symbol']} ({busiest['trade_count']} ostatnich trade'ow, wolumen {busiest['quote_volume']:.2f} {preferred_quote})."
            )
        if open_orders:
            findings.append(f"Na Binance sa teraz {len(open_orders)} otwarte zlecenia, co daje agentowi dodatkowy kontekst intencji portfela.")

        next_steps = [
            "Porownuj realne aktywa z najwyzsza ekspozycja do sygnalow paper tradingu i obnizaj confidence, gdy agent chce dokladac do juz napompowanej pozycji.",
            "Analizuj, czy prywatna aktywnosc BUY/SELL pokrywa sie z momentum na wykresie i ucz sie odrozniania kontynuacji od pogoni za ruchem.",
        ]
        if tracked_holdings:
            next_steps.append("Priorytetyzuj nauke na coinach, ktore rzeczywiscie wystepuja w portfelu Binance, bo tam agent ma najbardziej wartosciowy feedback z realnej ekspozycji.")

        import time as _time
        result = {
            "enabled": True,
            "quote_currency": preferred_quote,
            "total_value": round(total_value, 2),
            "top_holdings": top_weights,
            "tracked_holdings": tracked_holdings,
            "recent_trade_activity": tracked_activity,
            "recent_trade_symbols": trade_symbols,
            "open_orders_count": len(open_orders),
            "findings": findings,
            "next_steps": next_steps,
        }
        self._private_learning_cache[cache_key] = (_time.time(), result)
        return result

    def build_trade_history_ranking(
        self,
        client,
        tracked_symbols: list[str],
        preferred_quotes: list[str] | None = None,
    ) -> dict[str, Any] | None:
        preferred_quote = (preferred_quotes or ["USDT"])[0].upper()
        cache_key = f"{getattr(client, 'api_key', '')}:{preferred_quote}"
        cached = self._cache_get(self._trade_ranking_cache, cache_key, self.TRADE_RANKING_TTL)
        if cached is not _MISS:
            return cached
        ranking_entries: list[dict[str, Any]] = []

        for symbol in tracked_symbols:
            pair = f"{symbol}{preferred_quote}"
            trades = client.get_my_trades(pair, limit=50)
            if not isinstance(trades, list) or not trades:
                continue
            if isinstance(trades[0], dict) and "error" in trades[0]:
                continue

            buys = [t for t in trades if t.get("isBuyer")]
            sells = [t for t in trades if not t.get("isBuyer")]
            total_buy_qty = sum(float(t.get("qty", 0)) for t in buys)
            total_sell_qty = sum(float(t.get("qty", 0)) for t in sells)
            total_buy_quote = sum(float(t.get("quoteQty", 0)) for t in buys)
            total_sell_quote = sum(float(t.get("quoteQty", 0)) for t in sells)
            avg_buy = total_buy_quote / total_buy_qty if total_buy_qty > 0 else 0.0
            avg_sell = total_sell_quote / total_sell_qty if total_sell_qty > 0 else 0.0
            realized_pnl = total_sell_quote - (avg_buy * total_sell_qty) if total_sell_qty > 0 and avg_buy > 0 else 0.0
            trade_count = len(trades)
            commission_total = sum(float(t.get("commission", 0)) for t in trades)

            timestamps = [int(t.get("time", 0)) for t in trades if t.get("time")]
            if len(timestamps) >= 2:
                span_days = max(1, (max(timestamps) - min(timestamps)) / 86400000)
                frequency = round(trade_count / span_days, 2)
            else:
                frequency = 0.0

            ranking_entries.append({
                "symbol": pair,
                "trade_count": trade_count,
                "buy_count": len(buys),
                "sell_count": len(sells),
                "avg_buy_price": round(avg_buy, 4),
                "avg_sell_price": round(avg_sell, 4),
                "total_buy_volume": round(total_buy_quote, 2),
                "total_sell_volume": round(total_sell_quote, 2),
                "realized_pnl": round(realized_pnl, 2),
                "commission": round(commission_total, 6),
                "frequency": frequency,
            })

        if not ranking_entries:
            import time as _time
            self._trade_ranking_cache[cache_key] = (_time.time(), None)
            return None

        ranking_entries.sort(key=lambda e: e["trade_count"], reverse=True)

        total_realized = sum(e["realized_pnl"] for e in ranking_entries)
        total_trades = sum(e["trade_count"] for e in ranking_entries)
        profitable_pairs = sum(1 for e in ranking_entries if e["realized_pnl"] > 0)
        losing_pairs = sum(1 for e in ranking_entries if e["realized_pnl"] < 0)
        best_pair = max(ranking_entries, key=lambda e: e["realized_pnl"]) if ranking_entries else None
        worst_pair = min(ranking_entries, key=lambda e: e["realized_pnl"]) if ranking_entries else None

        insights = []
        if best_pair and best_pair["realized_pnl"] > 0:
            insights.append(f"Najlepszy pair: {best_pair['symbol']} z PnL +{best_pair['realized_pnl']:.2f} {preferred_quote}.")
        if worst_pair and worst_pair["realized_pnl"] < 0:
            insights.append(f"Najgorszy pair: {worst_pair['symbol']} z PnL {worst_pair['realized_pnl']:.2f} {preferred_quote}.")
        if profitable_pairs > losing_pairs:
            insights.append(f"Wiecej par zyskownych ({profitable_pairs}) niz stratnych ({losing_pairs}), co sugeruje dobre selekcjonowanie aktywow.")
        elif losing_pairs > profitable_pairs:
            insights.append(f"Wiecej par stratnych ({losing_pairs}) niz zyskownych ({profitable_pairs}). Agent powinien zaostrzyc kryteria wejscia.")
        high_freq = [e for e in ranking_entries if e["frequency"] > 1.0]
        if high_freq:
            insights.append(f"{len(high_freq)} par z czestotliwoscia > 1 trade/dzien. Sprawdz, czy czeste transakcje nie generuja nadmiernych prowizji.")

        import time as _time
        result = {
            "enabled": True,
            "quote_currency": preferred_quote,
            "total_realized_pnl": round(total_realized, 2),
            "total_trades": total_trades,
            "profitable_pairs": profitable_pairs,
            "losing_pairs": losing_pairs,
            "ranking": ranking_entries[:10],
            "insights": insights,
        }
        self._trade_ranking_cache[cache_key] = (_time.time(), result)
        return result

    def build_market_summary(self, session: Session, symbol: str, limit: int = 60) -> dict[str, Any] | None:
        import time as _time
        cached = self._cache_get(self._market_summary_cache, symbol, self.MARKET_SUMMARY_TTL)
        if cached is not _MISS:
            return cached
        rows = load_symbol_market_rows(session, symbol, limit=limit)
        if len(rows) < 10:
            self._market_summary_cache[symbol] = (_time.time(), None)
            return None

        df = build_indicator_frame(rows)
        summary, insights = self._analyze_frame(df)
        result = {"symbol": symbol, "summary": summary, "insights": insights}
        self._market_summary_cache[symbol] = (_time.time(), result)
        return result

    def build_chart_package(self, session: Session, symbol: str, limit: int = 60) -> dict[str, Any] | None:
        rows = load_symbol_market_rows(session, symbol, limit=limit)
        if len(rows) < 10:
            return None

        df = build_indicator_frame(rows)
        summary, insights = self._analyze_frame(df)

        # Fetch recent decisions for buy/sell markers on chart
        from sqlalchemy import desc as sql_desc
        markers = []
        recent_decisions = session.execute(
            select(Decision)
            .where(Decision.symbol == symbol, Decision.decision.in_(["BUY", "SELL"]))
            .order_by(sql_desc(Decision.timestamp))
            .limit(30)
        ).scalars().all()
        for d in recent_decisions:
            markers.append({
                "time": d.timestamp.strftime("%Y-%m-%d"),
                "action": d.decision,
                "reason": (d.reason or "")[:120],
            })

        return {
            "symbol": symbol,
            "points": [
                {
                    "date": row["timestamp"].strftime("%Y-%m-%d"),
                    "timestamp": row["timestamp"].isoformat(),
                    "open": round(float(row["open"]), 4),
                    "high": round(float(row["high"]), 4),
                    "low": round(float(row["low"]), 4),
                    "close": round(float(row["close"]), 4),
                    "ema20": round(float(row["ema20"]), 4),
                    "ema50": round(float(row["ema50"]), 4),
                    "rsi": round(float(row["rsi"]), 2),
                    "macd": round(float(row["macd"]), 4),
                    "macd_signal": round(float(row["macd_signal"]), 4),
                    "macd_hist": round(float(row["macd_hist"]), 4),
                    "volume": round(float(row["volume"]), 2),
                    "source": row["source"],
                }
                for _, row in df.iterrows()
            ],
            "summary": summary,
            "insights": insights,
            "markers": markers,
        }

    def _analyze_frame(self, df) -> tuple[dict[str, Any], list[str]]:
        latest = df.iloc[-1]
        previous = df.iloc[-2] if len(df) > 1 else latest
        last_20 = df.tail(min(20, len(df)))
        price_change_7d = float(latest["change_7d"])
        price_change_30d = float(latest["change_30d"])
        volatility_14d = float(latest["volatility_14d"])
        support = float(last_20["close"].min())
        resistance = float(last_20["close"].max())
        signal_alignment = self._signal_alignment(latest)
        rsi_zone = self._rsi_zone(float(latest["rsi"]))
        macd_state = "bullish" if float(latest["macd"]) >= float(latest["macd_signal"]) else "bearish"
        trend = str(latest["trend"])
        probabilities = self.probability_engine.estimate(latest, previous)

        insights = [
            f"Trend ceny jest {self._translate_trend(trend)}: EMA20 {'powyzej' if trend == 'UP' else 'ponizej'} EMA50.",
            f"RSI jest w strefie {rsi_zone} ({float(latest['rsi']):.1f}), wiec sygnal trzeba czytac razem z trendem.",
            f"MACD jest {macd_state} i {'potwierdza' if signal_alignment != 'mixed' else 'nie potwierdza jednoznacznie'} kierunek rynku.",
            f"Strefa obserwacji to okolice wsparcia {support:.2f} i oporu {resistance:.2f}.",
            f"Szacunek ruchu w gore: {probabilities['up_probability']:.1f}%, lokalnego dolka: {probabilities['bottom_probability']:.1f}%, lokalnego szczytu: {probabilities['top_probability']:.1f}%.",
            f"Wolumen zmienil sie o {float(latest['volume_change']) * 100:.1f}% vs poprzednia swieca, co pomaga odroznic ruch aktywny od przypadkowego.",
        ]

        summary = {
            "current_price": round(float(latest["close"]), 4),
            "change_7d": round(price_change_7d, 2),
            "change_30d": round(price_change_30d, 2),
            "volatility_14d": round(volatility_14d, 2),
            "support": round(support, 4),
            "resistance": round(resistance, 4),
            "signal_alignment": signal_alignment,
            "rsi_zone": rsi_zone,
            "macd_state": macd_state,
            "trend": trend,
            "ema20": round(float(latest["ema20"]), 4),
            "ema50": round(float(latest["ema50"]), 4),
            "macd": round(float(latest["macd"]), 4),
            "macd_signal": round(float(latest["macd_signal"]), 4),
            "rsi": round(float(latest["rsi"]), 2),
            "volume_change": round(float(latest["volume_change"]) * 100, 2),
            "change_24h": round(float(latest["change_24h"]), 2),
            "up_probability": probabilities["up_probability"],
            "bottom_probability": probabilities["bottom_probability"],
            "top_probability": probabilities["top_probability"],
            "reversal_signal": probabilities["reversal_signal"],
            "probability_explanation": probabilities["explanation"],
            "source": str(latest["source"]),
        }
        return summary, insights

    def build_learning_state(
        self,
        session: Session,
        market_rows: list[dict[str, Any]],
        chart_packages: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        recent_decisions = session.execute(select(Decision).order_by(desc(Decision.timestamp)).limit(40)).scalars().all()
        recent_trades = session.execute(select(SimulatedTrade).order_by(desc(SimulatedTrade.opened_at)).limit(40)).scalars().all()
        recent_logs = session.execute(select(LearningLog).order_by(desc(LearningLog.timestamp)).limit(20)).scalars().all()

        closed_trades = [trade for trade in recent_trades if trade.status == "CLOSED"]
        hold_ratio = (
            sum(1 for row in recent_decisions if row.decision == "HOLD") / len(recent_decisions) * 100
            if recent_decisions
            else 0.0
        )
        downtrend_count = sum(1 for row in market_rows if row["trend"] == "DOWN")
        oversold_count = sum(1 for row in market_rows if row["rsi"] < 30)
        win_rate = (
            sum(1 for trade in closed_trades if (trade.profit or 0.0) > 0) / len(closed_trades) * 100
            if closed_trades
            else 0.0
        )
        avg_profit = mean((trade.profit or 0.0) for trade in closed_trades) if closed_trades else 0.0

        curriculum = [
            {
                "title": "Filtr trendu",
                "description": "Agent ma laczyc RSI i MACD z EMA20/EMA50, zeby nie kupowac agresywnie w silnym trendzie spadkowym.",
            },
            {
                "title": "Jakosc wejscia",
                "description": "Przed BUY system ma sprawdzac zgodnosc momentum, wolumenu i trendu zamiast reagowac na pojedynczy sygnal.",
            },
            {
                "title": "Kontrola ryzyka",
                "description": "Kazda pozycja ma miec ograniczona wielkosc, stop loss i oczekiwany stosunek zysku do ryzyka.",
            },
            {
                "title": "Retrospektywa",
                "description": "Po kazdym zamknieciu pozycji agent ma zapisywac, czy decyzja byla poprawna i w jakim kontekscie rynkowym.",
            },
            {
                "title": "Czytanie swiec",
                "description": "Agent ma analizowac korpus, knoty, lokalny zakres i reakcje na wsparciu/oporze, zamiast patrzec tylko na zamkniecie swiecy.",
            },
            {
                "title": "Wolumen i uczestnictwo",
                "description": "Silny ruch bez potwierdzenia wolumenowego powinien miec nizsza wage niz ruch z rosnacym udzialem rynku.",
            },
            {
                "title": "Rezim rynku",
                "description": "System ma najpierw rozpoznac trend, konsolidacje albo panike, a dopiero potem dobierac odpowiedni setup.",
            },
        ]

        findings: list[dict[str, str]] = []
        if market_rows and downtrend_count >= max(2, len(market_rows) // 2):
            findings.append(
                {
                    "title": "Rynek jest defensywny",
                    "description": f"{downtrend_count} z {len(market_rows)} monitorowanych aktywow jest w trendzie spadkowym. Agent powinien trenowac selekcje BUY tylko przy silnym potwierdzeniu.",
                }
            )
        if oversold_count:
            findings.append(
                {
                    "title": "Oversold nie znaczy automatyczny BUY",
                    "description": f"{oversold_count} aktywa maja RSI ponizej 30. To dobry material do nauki odrozniania paniki od realnego odbicia.",
                }
            )
        if not closed_trades:
            findings.append(
                {
                    "title": "Za malo probek do oceny strategii",
                    "description": "Agent musi zbudowac serie minimum kilkunastu zamknietych transakcji, zanim zacznie stroic progi wejscia i wyjscia.",
                }
            )
        else:
            findings.append(
                {
                    "title": "Skutecznosc ostatnich zamknietych transakcji",
                    "description": f"Win rate wynosi {win_rate:.1f}%, a sredni wynik transakcji to {avg_profit:.2f} PLN. To baza do kalibracji confidence i stop lossu.",
                }
            )
        if hold_ratio > 65:
            findings.append(
                {
                    "title": "Strategia jest ostrozna",
                    "description": f"{hold_ratio:.1f}% ostatnich decyzji to HOLD. Agent powinien nauczyc sie odrozniania braku sygnalu od zbyt twardych progow wejscia.",
                }
            )
        if recent_logs:
            findings.append(
                {
                    "title": "Dziennik nauki jest aktywny",
                    "description": f"W learning_log zapisano {len(recent_logs)} ostatnich wpisow. To mozna wykorzystac do przegladu typowych bledow i warunkow rynku.",
                }
            )
        if not findings:
            findings.append(
                {
                    "title": "System zbiera dane",
                    "description": "Brak jednoznacznych odchylen jeszcze nie znaczy, ze strategia jest gotowa. Agent nadal powinien uczyc sie na kolejnych cyklach.",
                }
            )

        next_steps = [
            "Zbieraj 50-100 probek paper tradingu przed rozluznieniem progow BUY.",
            "Porownuj skutecznosc decyzji przy RSI<30 osobno dla trendu UP i DOWN.",
            "Mierz, czy confidence koreluje z realnym wynikiem transakcji.",
            "Testuj, czy filtr wolumenu poprawia win rate bez pogorszenia drawdown.",
            "Oceniaj, czy reakcja swiecy na wsparciu/oporze poprawia trafnosc wejsc.",
            "Buduj osobne statystyki dla breakout, trend continuation i mean reversion.",
        ]

        requirements = [
            {
                "title": "Dane order book i microstructure",
                "description": "Do lepszej pracy intraday agent potrzebuje glebi rynku, spreadu i szybkich zmian plynnosci, a nie tylko swiec OHLCV.",
            },
            {
                "title": "News i sentyment",
                "description": "Sam wykres nie wychwyci naglych newsow. Warto dodac kalendarz wydarzen, naglowki i filtr sentymentu dla krypto.",
            },
            {
                "title": "Lepsze etykietowanie probek",
                "description": "Do prawdziwej nauki modelowej agent potrzebuje oznaczonych wynikow: ktore setupy dawaly realny follow-through, a ktore byly falszywym sygnalem.",
            },
            {
                "title": "Kontrola portfelowa",
                "description": "Trzeba mierzyc ekspozycje sektorowa, korelacje miedzy coinami i dzienny limit straty dla calego portfela.",
            },
            {
                "title": "Monitoring produkcyjny",
                "description": "Do stabilnej pracy potrzeba alertow, logow błedow API, retry oraz kontroli opoznien pobierania danych z gield.",
            },
        ]

        return {
            "curriculum": curriculum,
            "findings": findings,
            "next_steps": next_steps,
            "requirements": requirements,
            "knowledge_base": KNOWLEDGE_BASE,
            "chart_watchlist": [symbol for symbol, package in chart_packages.items() if package is not None] or [row["symbol"] for row in market_rows],
        }

    def get_articles(self) -> list[dict[str, Any]]:
        return LEARNING_ARTICLES

    def build_lifecycle_history(self, symbol: str, force_refresh: bool = False) -> dict[str, Any]:
        cache_entry = self._lifecycle_cache.get(symbol)
        if not force_refresh and cache_entry is not None and (datetime.utcnow() - cache_entry[0]) < timedelta(hours=6):
            return cache_entry[1]

        coin_id = settings.coingecko_ids.get(symbol)
        points: list[dict[str, Any]] = []
        history_source = "binance"
        try:
            points = self._fetch_binance_lifecycle_history(symbol)
        except requests.RequestException:
            points = []

        if not points and coin_id is not None:
            history_source = "coingecko"
            try:
                points = self._fetch_coingecko_lifecycle_history(coin_id)
            except requests.RequestException:
                points = []

        points = self._apply_history_floor(symbol, points)

        if not points:
            result = {"symbol": symbol, "points": [], "summary": {"history_mode": "max", "history_source": history_source}}
            self._lifecycle_cache[symbol] = (datetime.utcnow(), result)
            return result

        ath_point = max(points, key=lambda item: item["close"])
        atl_point = min(points, key=lambda item: item["close"])
        start_point = points[0]
        end_point = points[-1]
        start_dt = datetime.fromisoformat(start_point["timestamp"])
        end_dt = datetime.fromisoformat(end_point["timestamp"])
        years_listed = round(max((end_dt - start_dt).days / 365.25, 0.0), 2)
        result = {
            "symbol": symbol,
            "points": points,
            "summary": {
                "history_mode": "max",
                "start_date": start_point["date"],
                "end_date": end_point["date"],
                "inception_price": start_point["close"],
                "current_price": end_point["close"],
                "ath_price": ath_point["close"],
                "ath_date": ath_point["date"],
                "atl_price": atl_point["close"],
                "atl_date": atl_point["date"],
                "change_since_inception": round(((end_point["close"] / start_point["close"]) - 1) * 100, 2) if start_point["close"] else 0.0,
                "years_listed": years_listed,
                "points_count": len(points),
                "history_source": history_source,
                "has_ohlc": any(point.get("high") is not None and point.get("low") is not None for point in points),
            },
        }
        self._lifecycle_cache[symbol] = (datetime.utcnow(), result)
        return result

    def _apply_history_floor(self, symbol: str, points: list[dict[str, Any]]) -> list[dict[str, Any]]:
        floor_value = settings.history_start_floors.get(symbol)
        if floor_value is None:
            return points
        floor_date = date.fromisoformat(floor_value)
        filtered = [point for point in points if date.fromisoformat(point["date"]) >= floor_date]
        return filtered or points

    def _fetch_coingecko_lifecycle_history(self, coin_id: str) -> list[dict[str, Any]]:
        response = requests.get(
            f"https://api.coingecko.com/api/v3/coins/{coin_id}/market_chart",
            params={"vs_currency": settings.quote_currency.lower(), "days": "max", "interval": "daily"},
            timeout=30,
            headers={"Accept": "application/json", "User-Agent": "Agent-Krypto/1.0"},
        )
        response.raise_for_status()
        payload = response.json()
        price_rows = payload.get("prices", [])
        volume_rows = payload.get("total_volumes", [])
        market_cap_rows = payload.get("market_caps", [])

        volume_by_date = {int(row[0]): float(row[1]) for row in volume_rows}
        market_cap_by_date = {int(row[0]): float(row[1]) for row in market_cap_rows}
        points: list[dict[str, Any]] = []
        previous_close: float | None = None
        for row in price_rows:
            timestamp = int(row[0])
            close = float(row[1])
            open_price = previous_close if previous_close is not None else close
            high = max(open_price, close)
            low = min(open_price, close)
            points.append(
                {
                    "date": datetime.utcfromtimestamp(timestamp / 1000).strftime("%Y-%m-%d"),
                    "timestamp": datetime.utcfromtimestamp(timestamp / 1000).isoformat(),
                    "open": round(open_price, 8),
                    "high": round(high, 8),
                    "low": round(low, 8),
                    "close": round(close, 8),
                    "volume": round(float(volume_by_date.get(timestamp, 0.0)), 2),
                    "market_cap": round(float(market_cap_by_date.get(timestamp, 0.0)), 2),
                }
            )
            previous_close = close
        return points

    def _fetch_binance_lifecycle_history(self, symbol: str) -> list[dict[str, Any]]:
        pair = settings.binance_symbols.get(symbol)
        if pair is None:
            return []

        points: list[dict[str, Any]] = []
        start_time = 0
        last_open_time: int | None = None
        while True:
            response = requests.get(
                "https://api.binance.com/api/v3/klines",
                params={"symbol": pair, "interval": "1d", "limit": 1000, "startTime": start_time},
                timeout=30,
                headers={"Accept": "application/json", "User-Agent": "Agent-Krypto/1.0"},
            )
            response.raise_for_status()
            rows = response.json()
            if not rows:
                break

            for row in rows:
                open_time = int(row[0])
                if last_open_time is not None and open_time <= last_open_time:
                    continue
                last_open_time = open_time
                points.append(
                    {
                        "date": datetime.utcfromtimestamp(open_time / 1000).strftime("%Y-%m-%d"),
                        "timestamp": datetime.utcfromtimestamp(open_time / 1000).isoformat(),
                        "open": round(float(row[1]), 8),
                        "high": round(float(row[2]), 8),
                        "low": round(float(row[3]), 8),
                        "close": round(float(row[4]), 8),
                        "volume": round(float(row[7]) if float(row[7]) > 0 else float(row[5]), 2),
                        "market_cap": 0.0,
                    }
                )

            if len(rows) < 1000:
                break
            start_time = int(rows[-1][0]) + 86400000

        return points

    def _signal_alignment(self, latest) -> str:
        bullish_rsi = float(latest["rsi"]) < 35
        bullish_macd = float(latest["macd"]) >= float(latest["macd_signal"])
        bullish_trend = float(latest["ema20"]) >= float(latest["ema50"])
        bearish_rsi = float(latest["rsi"]) > 65
        bearish_macd = float(latest["macd"]) < float(latest["macd_signal"])
        bearish_trend = float(latest["ema20"]) < float(latest["ema50"])

        if bullish_rsi and bullish_macd and bullish_trend:
            return "bullish"
        if bearish_rsi and bearish_macd and bearish_trend:
            return "bearish"
        return "mixed"

    def _rsi_zone(self, rsi_value: float) -> str:
        if rsi_value < 30:
            return "oversold"
        if rsi_value > 70:
            return "overbought"
        return "neutral"

    def _translate_trend(self, trend: str) -> str:
        return {"UP": "wzrostowy", "DOWN": "spadkowy"}.get(trend, "boczny")