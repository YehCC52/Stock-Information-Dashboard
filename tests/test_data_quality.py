from datetime import date, datetime, timezone

from stock_daily_research.data_quality import (
    confidence,
    detect_market_cap_drift,
    detect_market_cap_price_mismatch,
    detect_news_overflow,
    detect_pe_anomaly,
    detect_google_redirect_source,
    detect_premarket_label_inconsistency,
    detect_price_anomaly,
    detect_stale_data,
)
from stock_daily_research.models import (
    NewsArticle,
    PremarketMove,
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
        articles=1,
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
    assert result["score"] == 65
    assert result["tag"] == "medium"


def test_confidence_deducts_lighter_source_quality_flags() -> None:
    item = _item(
        {
            "last_close": 100.0,
            "previous_close": 99.5,
            "market_cap": 130.0,
            "previous_market_cap": 100.0,
            "forward_pe": -5.0,
        },
        articles=1,
    )
    google_article = NewsArticle(
        ticker="NVDA",
        title="Nvidia headline",
        source="Google News",
        domain="google.com",
        published_at=None,
        url="https://news.google.com/rss/articles/x",
        summary="",
        event_type="general",
        importance_score=0.5,
    )
    item = TickerReport(
        ticker=item.ticker,
        articles=[google_article],
        x_signals=[],
        valuation=item.valuation,
        earnings=item.earnings,
        warnings=[],
    )
    move = PremarketMove("NVDA", "NVIDIA", 100.0, 99.5, 0.5, "after-hours quote")

    result = confidence(item, date(2026, 4, 28), premarket_move=move)

    assert result["score"] == 65
    assert detect_market_cap_price_mismatch(item.valuation.metrics) is not None
    assert detect_google_redirect_source(item) is not None
    assert detect_premarket_label_inconsistency(move) is not None


def test_confidence_does_not_require_forward_pe_for_crypto() -> None:
    snapshot = ValuationSnapshot(
        ticker="BTC-USD", as_of_date=date(2026, 4, 28), source="yfinance",
        metrics={"last_close": 60000.0, "previous_close": 59500.0, "market_cap": 1_200_000_000_000},
        retrieved_at=datetime(2026, 4, 28, tzinfo=timezone.utc),
    )
    item = TickerReport(
        ticker=TickerConfig(symbol="BTC-USD", company_name="Bitcoin", market="crypto"),
        articles=[],
        x_signals=[],
        valuation=snapshot,
        earnings=None,
    )

    result = confidence(item, date(2026, 4, 28))

    assert result["missing_fields"] == []
    assert result["score"] == 100
