from stock_daily_research.models import TickerConfig
from stock_daily_research.premarket import fetch_overnight_premarket


def test_fetch_overnight_premarket_ranks_watchlist_gaps(monkeypatch) -> None:
    data = {
        "ES=F": {"regularMarketPrice": 5000.0, "regularMarketPreviousClose": 4950.0},
        "NQ=F": {"regularMarketPrice": 18000.0, "regularMarketPreviousClose": 18100.0},
        "SPY": {"preMarketPrice": 505.0, "regularMarketPreviousClose": 500.0},
        "QQQ": {"preMarketPrice": 460.0, "regularMarketPreviousClose": 450.0},
        "NVDA": {"preMarketPrice": 107.0, "regularMarketPreviousClose": 100.0},
        "MSFT": {"preMarketPrice": 401.0, "regularMarketPreviousClose": 400.0},
    }

    class FakeTicker:
        def __init__(self, symbol):
            self.symbol = symbol

        def get_info(self):
            return data[self.symbol]

    monkeypatch.setattr("stock_daily_research.premarket.yf.Ticker", FakeTicker)

    snapshot = fetch_overnight_premarket([
        TickerConfig(symbol="NVDA", company_name="NVIDIA"),
        TickerConfig(symbol="MSFT", company_name="Microsoft"),
    ])

    assert len(snapshot.benchmarks) == 4
    assert snapshot.watchlist_movers[0].symbol == "NVDA"
    assert snapshot.watchlist_movers[0].change_pct == 7.0
    assert [move.symbol for move in snapshot.gap_movers] == ["NVDA"]
