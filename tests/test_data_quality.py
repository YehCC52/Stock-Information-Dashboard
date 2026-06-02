from datetime import date, datetime, timezone

from stock_daily_research.data_quality import (
    confidence,
    detect_market_cap_drift,
    detect_news_overflow,
    detect_pe_anomaly,
    detect_price_anomaly,
    detect_stale_data,
)
from stock_daily_research.models import (
    NewsArticle,
    TickerConfig,
    TickerReport,
    ValuationSnapshot,
)


def _news(symbol: str) -> NewsArticle:
    return NewsArticle(
        ticker=symbol, title="t", source="s", domain="d",
        published_at=None, url="u", summary="", event_type="general",
        importance_score=0.5,
    )


def _item(metrics=None, *, articles=0, warnings=None, retrieved=None):
    snapshot = None
    if metrics is not None:
        snapshot = ValuationSnapshot(
            ticker="NVDA", as_of_date=date(2026, 4, 28), source="yfinance",
            metrics=metrics,
            retrieved_at=retrieved or datetime(2026, 4, 28, tzinfo=timezone.utc),
        )
    return TickerReport(
        ticker=TickerConfig(symbol="NVDA", company_name="NVIDIA"),
        articles=[_news("NVDA") for _ in range(articles)],
        x_signals=[],
        valuation=snapshot,
        earnings=None,
        warnings=warnings or [],
    )


def test_detect_price_anomaly_flags_large_move() -> None:
    item = _item({"last_close": 130.0, "previous_close": 100.0})
    assert detect_price_anomaly(item) is not None
    calm = _item({"last_close": 105.0, "previous_close": 100.0})
    assert detect_price_anomaly(calm) is None


def test_detect_market_cap_drift() -> None:
    assert detect_market_cap_drift({"market_cap": 130.0}, {"market_cap": 100.0}) is not None
    assert detect_market_cap_drift({"market_cap": 105.0}, {"market_cap": 100.0}) is None


def test_detect_pe_anomaly_negative_and_huge() -> None:
    assert detect_pe_anomaly(_item({"forward_pe": -5.0})) is not None
    assert detect_pe_anomaly(_item({"forward_pe": 5000.0})) is not None
    assert detect_pe_anomaly(_item({"forward_pe": 28.0})) is None


def test_detect_stale_data() -> None:
    fresh = _item({"last_close": 100.0}, retrieved=datetime(2026, 4, 28, tzinfo=timezone.utc))
    assert detect_stale_data(fresh.valuation, date(2026, 4, 28)) is None
    old = _item({"last_close": 100.0}, retrieved=datetime(2026, 4, 25, tzinfo=timezone.utc))
    assert detect_stale_data(old.valuation, date(2026, 4, 28)) is not None


def test_detect_news_overflow() -> None:
    assert detect_news_overflow(_item({}, articles=15)) is not None
    assert detect_news_overflow(_item({}, articles=5)) is None


def test_confidence_high_when_clean() -> None:
    item = _item(
        {"last_close": 100.0, "previous_close": 99.0, "market_cap": 1e12, "forward_pe": 30.0},
        articles=4,
    )
    result = confidence(item, date(2026, 4, 28))
    assert result["score"] == 100
    assert result["tag"] == "high"
    assert result["flags"] == []


def test_confidence_low_when_multiple_flags() -> None:
    item = _item(
        {"last_close": 200.0, "previous_close": 100.0, "forward_pe": -5.0},  # +100% move + neg P/E
        articles=20,                                                          # overflow
        warnings=["Valuation fallback used for NVDA"],
        retrieved=datetime(2026, 4, 25, tzinfo=timezone.utc),                 # stale
    )
    result = confidence(item, date(2026, 4, 28))
    assert result["score"] < 50
    assert result["tag"] == "low"
    assert result["fallback"] is True
    assert "market_cap" in result["missing_fields"]


def test_confidence_medium_band() -> None:
    item = _item(
        {"last_close": 100.0, "previous_close": 99.0, "forward_pe": 30.0},  # market_cap missing → -10
        articles=20,                                                         # overflow → -20
    )
    result = confidence(item, date(2026, 4, 28))
    assert result["score"] == 70
    assert result["tag"] == "medium"
