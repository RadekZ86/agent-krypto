from __future__ import annotations

from datetime import datetime
import unittest

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import MarketData
from app.services.market_data import MarketDataService, load_symbol_market_rows


class MarketDataNormalizationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite:///:memory:", future=True)
        Base.metadata.create_all(self.engine)
        self.SessionLocal = sessionmaker(bind=self.engine, future=True)

    def tearDown(self) -> None:
        self.engine.dispose()

    def test_load_symbol_market_rows_prefers_highest_priority_within_interval_bucket(self) -> None:
        with self.SessionLocal() as session:
            session.add_all(
                [
                    MarketData(
                        symbol="BTC",
                        timestamp=datetime(2026, 3, 29, 17, 0, 0),
                        open=67000.0,
                        high=67150.0,
                        low=66950.0,
                        close=67025.0,
                        volume=1000.0,
                        source="binance",
                    ),
                    MarketData(
                        symbol="BTC",
                        timestamp=datetime(2026, 3, 29, 17, 53, 4),
                        open=245000.0,
                        high=246500.0,
                        low=244500.0,
                        close=246225.61,
                        volume=900.0,
                        source="coingecko",
                    ),
                    MarketData(
                        symbol="BTC",
                        timestamp=datetime(2026, 3, 29, 18, 0, 0),
                        open=67025.0,
                        high=67200.0,
                        low=66980.0,
                        close=67120.0,
                        volume=1200.0,
                        source="binance",
                    ),
                ]
            )
            session.commit()

            rows = load_symbol_market_rows(session, "BTC", limit=2)

            self.assertEqual([row.source for row in rows], ["binance", "binance"])
            self.assertEqual([round(row.close, 2) for row in rows], [67025.0, 67120.0])

    def test_persist_records_normalizes_timestamps_to_interval_bucket(self) -> None:
        with self.SessionLocal() as session:
            service = MarketDataService()
            service._persist_records(
                session,
                "ETH",
                [
                    {
                        "timestamp": datetime(2026, 3, 29, 17, 35, 51),
                        "open": 2050.0,
                        "high": 2060.0,
                        "low": 2040.0,
                        "close": 2055.0,
                        "volume": 100.0,
                        "source": "coingecko",
                    },
                    {
                        "timestamp": datetime(2026, 3, 29, 17, 53, 4),
                        "open": 2055.0,
                        "high": 2065.0,
                        "low": 2050.0,
                        "close": 2061.0,
                        "volume": 140.0,
                        "source": "coingecko",
                    },
                ],
            )
            session.commit()

            rows = session.execute(select(MarketData).where(MarketData.symbol == "ETH")).scalars().all()

            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0].timestamp, datetime(2026, 3, 29, 17, 0, 0))
            self.assertEqual(rows[0].close, 2061.0)


if __name__ == "__main__":
    unittest.main()