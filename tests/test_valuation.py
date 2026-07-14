from datetime import date, datetime, timezone

import pandas as pd

from stock_daily_research.valuation import (
    coerce_date,
    compute_move_quality_metrics,
    compute_right_side_setup_metrics,
    compute_trend_structure_metrics,
    compute_rsi,
    fetch_yfinance_eps_metrics,
    format_metric_value,
    normalize_yfinance_metrics,
)


def test_normalize_yfinance_metrics_maps_known_fields() -> None:
    metrics = normalize_yfinance_metrics(
        {
            "marketCap": 1_500_000_000_000,
            "enterpriseValue": 1_450_000_000_000,
            "trailingPE": 44.2,
            "forwardPE": 26.6,
            "trailingEps": 8.1,
            "forwardEps": 9.4,
            "pegRatio": 0.77,
            "priceToSalesTrailing12Months": 24.5,
            "priceToBook": 33.4,
            "enterpriseToRevenue": 24.1,
            "enterpriseToEbitda": 36.0,
        }
    )

    assert metrics["market_cap"] == 1_500_000_000_000
    assert metrics["ttm_eps"] == 8.1
    assert metrics["forward_eps"] == 9.4
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


def test_compute_move_quality_metrics_volume_gap_and_atr() -> None:
    rows = []
    for idx in range(25):
        close = 100.0 + idx
        rows.append({
            "Open": close - 0.5,
            "High": close + 1.0,
            "Low": close - 1.0,
            "Close": close,
            "Volume": 1_000_000,
        })
    rows[-1]["Open"] = rows[-2]["Close"] * 1.03
    rows[-1]["Close"] = rows[-2]["Close"] * 1.04
    rows[-1]["High"] = rows[-1]["Close"] + 1.0
    rows[-1]["Low"] = rows[-1]["Open"] - 1.0
    rows[-1]["Volume"] = 2_000_000
    hist = pd.DataFrame(rows)

    metrics = compute_move_quality_metrics(hist)

    assert metrics["volume_vs_20d"] == 2.0
    assert metrics["gap_percent"] == 3.0
    assert metrics["atr_20_percent"] is not None
    assert metrics["move_vs_atr"] is not None


def test_compute_right_side_setup_metrics_detects_base_contraction() -> None:
    rows = []
    for idx in range(50):
        if idx < 30:
            close = 105.0 if idx % 2 else 95.0
            spread = 2.0
            volume = 1_000_000
        else:
            close = 100.1 if idx % 2 else 100.0
            spread = 0.2
            volume = 500_000 if idx >= 45 else 1_000_000
        rows.append({
            "Open": close,
            "High": close + spread,
            "Low": close - spread,
            "Close": close,
            "Volume": volume,
        })

    metrics = compute_right_side_setup_metrics(pd.DataFrame(rows))

    assert metrics["atr_contraction_ratio"] is not None
    assert metrics["atr_contraction_ratio"] < 0.8
    assert metrics["bb_width_20_percentile"] is not None
    assert metrics["bb_width_20_percentile"] <= 20.0
    assert metrics["volume_5d_vs_20d"] == 0.5


def test_compute_right_side_setup_metrics_tracks_breakout_retention() -> None:
    rows = [
        {"Open": 100.0, "High": 101.0, "Low": 99.0, "Close": 100.0, "Volume": 1_000_000}
        for _ in range(45)
    ]
    rows.extend([
        {"Open": 100.5, "High": 104.0, "Low": 100.0, "Close": 103.0, "Volume": 2_000_000},
        {"Open": 103.0, "High": 104.0, "Low": 102.0, "Close": 102.5, "Volume": 1_000_000},
        {"Open": 102.5, "High": 104.0, "Low": 102.0, "Close": 103.0, "Volume": 1_000_000},
        {"Open": 103.0, "High": 104.0, "Low": 102.5, "Close": 103.2, "Volume": 1_000_000},
        {"Open": 103.2, "High": 104.0, "Low": 102.8, "Close": 103.5, "Volume": 1_000_000},
    ])

    metrics = compute_right_side_setup_metrics(pd.DataFrame(rows))

    assert metrics["breakout_days_ago"] == 4.0
    assert metrics["breakout_pivot"] == 101.0
    assert metrics["breakout_hold_pct"] == 2.48
    assert metrics["breakout_volume_vs_20d"] == 2.0

def test_fetch_yfinance_eps_metrics_extracts_estimates_and_revisions() -> None:
    class FakeAnalysis:
        eps_trend = pd.DataFrame(
            [{"current": 11.0, "30daysAgo": 10.0}],
            index=pd.Index(["+1y"], name="period"),
        )
        eps_revisions = pd.DataFrame(
            [{"upLast30days": 12, "downLast30days": 3}],
            index=pd.Index(["+1y"], name="period"),
        )

    class FakeTicker:
        _analysis = FakeAnalysis()

        def get_earnings_estimate(self):
            return pd.DataFrame(
                [{"avg": 11.0, "growth": 0.22}],
                index=pd.Index(["+1y"], name="period"),
            )

        @property
        def revenue_estimate(self):
            return pd.DataFrame(
                [
                    {"avg": 22_000_000_000, "growth": 0.08},
                    {"avg": 100_000_000_000, "growth": 0.15},
                ],
                index=pd.Index(["+1q", "+1y"], name="period"),
            )

        def get_earnings_history(self):
            return pd.DataFrame(
                [
                    {
                        "quarter": "2026-04-27",
                        "epsActual": 1.12,
                        "epsEstimate": 1.00,
                        "surprisePercent": 12.0,
                        "reportedRevenue": 112_000_000_000,
                        "revenueEstimate": 110_000_000_000,
                    }
                ]
            )

    metrics = fetch_yfinance_eps_metrics(FakeTicker(), {"ttm_eps": 9.0, "forward_eps": 10.0})

    assert metrics["next_fy_eps"] == 11.0
    assert metrics["eps_growth_pct"] == 22.0
    assert metrics["fy1_eps_revision_30d"] == 10.0
    assert metrics["fy1_eps_revision_up_30d"] == 12
    assert metrics["fy1_eps_revision_down_30d"] == 3
    assert metrics["next_q_revenue"] == 22_000_000_000
    assert metrics["next_q_revenue_growth_pct"] == 8.0
    assert metrics["next_fy_revenue"] == 100_000_000_000
    assert metrics["revenue_growth_pct"] == 15.0
    assert metrics["latest_eps_surprise_pct"] == 12.0
    assert metrics["latest_revenue_surprise_pct"] == 1.82


def test_fetch_yfinance_eps_metrics_falls_back_to_forward_eps_and_growth_calc() -> None:
    class FakeTicker:
        def get_earnings_estimate(self):
            return None

    metrics = fetch_yfinance_eps_metrics(FakeTicker(), {"ttm_eps": 8.0, "forward_eps": 10.0})

    assert metrics["next_fy_eps"] == 10.0
    assert metrics["eps_growth_pct"] == 25.0


def test_fetch_yfinance_valuation_skips_estimate_fetch_for_crypto(monkeypatch) -> None:
    import stock_daily_research.valuation as valuation_mod
    from stock_daily_research.models import TickerConfig

    class FakeYfTicker:
        def get_info(self):
            return {
                "regularMarketPrice": 60000.0,
                "regularMarketPreviousClose": 59000.0,
                "marketCap": 1_200_000_000_000,
            }

    monkeypatch.setattr(valuation_mod.yf, "Ticker", lambda _symbol: FakeYfTicker())
    monkeypatch.setattr(valuation_mod, "fetch_technical_indicators", lambda _t: {"rsi_14": 55.0})

    def boom(*_args, **_kwargs):
        raise AssertionError("analyst-estimate fetch should be skipped for crypto")

    monkeypatch.setattr(valuation_mod, "fetch_yfinance_eps_metrics", boom)

    ticker = TickerConfig(symbol="BTC-USD", company_name="Bitcoin", market="crypto")
    snapshot = valuation_mod.fetch_yfinance_valuation(ticker)

    assert snapshot.metrics["last_close"] == 60000.0
    assert snapshot.metrics["market_cap"] == 1_200_000_000_000
    # Estimate keys stay present (as None) so the metrics shape is consistent.
    assert snapshot.metrics["next_fy_eps"] is None
    assert snapshot.metrics["latest_eps_surprise_pct"] is None

def test_fetch_yfinance_valuation_skips_fundamentals_for_etf(monkeypatch) -> None:
    import stock_daily_research.valuation as valuation_mod
    from stock_daily_research.models import TickerConfig

    class FakeYfTicker:
        def get_info(self):
            raise AssertionError("ETF fundamentals endpoint should not be called")

    monkeypatch.setattr(valuation_mod.yf, "Ticker", lambda _symbol: FakeYfTicker())
    monkeypatch.setattr(
        valuation_mod,
        "fetch_technical_indicators",
        lambda _ticker: {"last_close": 52.4, "rsi_14": 51.0},
    )

    def boom(*_args, **_kwargs):
        raise AssertionError("ETF analyst-estimate endpoint should not be called")

    monkeypatch.setattr(valuation_mod, "fetch_yfinance_eps_metrics", boom)

    ticker = TickerConfig(
        symbol="0050.TW",
        company_name="元大台灣50",
        market="twse",
        has_fundamentals=False,
    )
    snapshot = valuation_mod.fetch_yfinance_valuation(ticker)

    assert snapshot.metrics["last_close"] == 52.4
    assert snapshot.metrics["rsi_14"] == 51.0
    assert snapshot.metrics["next_fy_eps"] is None


def test_compute_trend_structure_metrics_uses_prior_sessions_for_breakout_levels() -> None:
    rows = []
    for idx in range(25):
        close = 100.0 + idx
        rows.append({"Open": close - 1, "High": close + 1, "Low": close - 2, "Close": close})
    rows[-1] = {"Open": 139.0, "High": 142.0, "Low": 138.0, "Close": 140.0}
    hist = pd.DataFrame(rows)

    metrics = compute_trend_structure_metrics(hist)

    assert metrics["prior_20d_high"] == 124.0
    assert metrics["prior_20d_low"] == 102.0
    assert metrics["sma_20_slope_5d"] is not None
    assert metrics["sma_20_slope_5d"] > 0