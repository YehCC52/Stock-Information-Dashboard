from datetime import date, datetime, timezone

from stock_daily_research.valuation import coerce_date, compute_rsi, format_metric_value, normalize_yfinance_metrics


def test_normalize_yfinance_metrics_maps_known_fields() -> None:
    metrics = normalize_yfinance_metrics(
        {
            "marketCap": 1_500_000_000_000,
            "enterpriseValue": 1_450_000_000_000,
            "trailingPE": 44.2,
            "forwardPE": 26.6,
            "pegRatio": 0.77,
            "priceToSalesTrailing12Months": 24.5,
            "priceToBook": 33.4,
            "enterpriseToRevenue": 24.1,
            "enterpriseToEbitda": 36.0,
        }
    )

    assert metrics["market_cap"] == 1_500_000_000_000
    assert metrics["peg_ratio"] == 0.77
    assert metrics["ev_to_ebitda"] == 36.0


def test_format_metric_value_compacts_large_numbers() -> None:
    assert format_metric_value(1_250_000_000_000) == "1.25T"
    assert format_metric_value(44.2123) == "44.21"
    assert format_metric_value(None) == "N/A"
    assert format_metric_value(float("nan")) == "N/A"


def test_normalize_yfinance_metrics_replaces_nan_with_none() -> None:
    metrics = normalize_yfinance_metrics({"trailingPE": float("nan"), "marketCap": 1_000})

    assert metrics["trailing_pe"] is None
    assert metrics["market_cap"] == 1_000


def test_normalize_yfinance_metrics_extracts_last_close() -> None:
    """Most recent traded price comes from regularMarketPrice."""
    metrics = normalize_yfinance_metrics({
        "regularMarketPrice": 138.40,
        "regularMarketPreviousClose": 135.10,
    })
    assert metrics["last_close"] == 138.40
    assert metrics["previous_close"] == 135.10


def test_normalize_yfinance_metrics_falls_back_when_regularMarketPrice_missing() -> None:
    """Delisted/halted symbols may not have regularMarketPrice; fall back."""
    metrics = normalize_yfinance_metrics({"previousClose": 12.34})
    assert metrics["last_close"] == 12.34


def test_coerce_date_handles_datetime_and_iso() -> None:
    assert coerce_date(datetime(2026, 4, 28, tzinfo=timezone.utc)) == date(2026, 4, 28)
    assert coerce_date("2026-04-28T00:00:00+00:00") == date(2026, 4, 28)


def test_compute_rsi_buckets_recent_closes() -> None:
    rising = [100 + idx for idx in range(20)]
    falling = [120 - idx for idx in range(20)]
    mixed = [100, 101, 102, 101, 103, 104, 103, 105, 106, 104, 107, 108, 106, 109, 110]

    assert compute_rsi(rising, 14) == 100.0
    assert compute_rsi(falling, 14) == 0.0
    assert compute_rsi(mixed, 14) is not None
    assert compute_rsi([100, 101], 14) is None
