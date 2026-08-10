from __future__ import annotations

import json
import sys
from types import SimpleNamespace
from dataclasses import asdict
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd
import pytest

from stock_daily_research.backtest import (
    _apply_data_quality_status,
    _OpenPosition,
    _benchmark_returns_at,
    _benchmark_returns_reference,
    _build_benchmark_history,
    _close_position,
    _simulate_portfolio,
    _is_taiwan_locked_limit_bar,
    benchmark_tickers,
    default_market_assumptions,
    generate_signals,
    run_market_backtest,
)
from stock_daily_research.backtest_data import (
    HistoricalPriceProvider,
    _load_yfinance_history,
    normalize_history_frame,
    price_history_quality,
)
from stock_daily_research.backtest_runner import _fingerprint, run_backtest
from stock_daily_research.models import (
    BacktestSettings,
    BacktestSignal,
    TickerConfig,
)
from stock_daily_research.storage import (
    init_db,
    load_backtest_price_bars,
    load_backtest_price_coverage,
    load_backtest_run,
)


def _trend_frame(periods: int = 360, *, freq: str = "B") -> pd.DataFrame:
    dates = pd.date_range("2023-01-02", periods=periods, freq=freq)
    closes = [80.0 + index * 0.09 + (index % 9) * 0.03 for index in range(periods)]
    volumes = [1_000_000.0] * periods
    for index in range(145, periods - 5, 42):
        closes[index] = max(value + 0.45 for value in closes[index - 20:index]) + 0.9
        volumes[index] = 2_200_000.0
    return pd.DataFrame(
        {
            "Open": closes,
            "High": [value + 0.45 for value in closes],
            "Low": [value - 0.45 for value in closes],
            "Close": closes,
            "Volume": volumes,
        },
        index=dates,
    )


def _benchmark_frame(periods: int = 360, *, freq: str = "B") -> pd.DataFrame:
    dates = pd.date_range("2023-01-02", periods=periods, freq=freq)
    closes = [100.0 + index * 0.025 for index in range(periods)]
    return pd.DataFrame(
        {
            "Open": closes,
            "High": [value + 0.25 for value in closes],
            "Low": [value - 0.25 for value in closes],
            "Close": closes,
            "Volume": [2_000_000.0] * periods,
        },
        index=dates,
    )


def _bars(ticker: TickerConfig, frame: pd.DataFrame):
    return normalize_history_frame(
        ticker,
        frame,
        retrieved_at=datetime(2026, 8, 10, tzinfo=timezone.utc),
    )


def _settings(frame: pd.DataFrame) -> BacktestSettings:
    return BacktestSettings(
        start_date=frame.index[140].date(),
        end_date=frame.index[-1].date(),
        warmup_sessions=120,
        lookback_sessions=180,
        max_holding_sessions=25,
    )


@pytest.mark.parametrize(
    "overrides",
    [
        {"initial_capital": 0.0},
        {"commission_bps": -0.1},
        {"slippage_bps": float("nan")},
    ],
)
def test_market_assumptions_reject_invalid_execution_inputs(
    overrides: dict[str, float],
) -> None:
    with pytest.raises(ValueError):
        default_market_assumptions("us", **overrides)



@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("max_volume_participation_pct", 0.0),
        ("max_volume_participation_pct", 101.0),
        ("walk_forward_folds", 1),
        ("walk_forward_folds", 13),
    ],
)
def test_backtest_settings_reject_invalid_robustness_inputs(
    field_name: str,
    value: float,
) -> None:
    values = {
        "start_date": date(2025, 1, 1),
        "end_date": date(2026, 1, 1),
        "warmup_sessions": 120,
        "lookback_sessions": 120,
        field_name: value,
    }

    with pytest.raises(ValueError):
        BacktestSettings(**values)


def test_yfinance_history_requests_repair_and_adjustment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected = pd.DataFrame({"Close": [100.0]})
    calls: dict[str, object] = {}

    class FakeTicker:
        def __init__(self, symbol: str) -> None:
            calls["symbol"] = symbol

        def history(self, **kwargs: object) -> pd.DataFrame:
            calls.update(kwargs)
            return expected

    monkeypatch.setitem(
        sys.modules,
        "yfinance",
        SimpleNamespace(Ticker=FakeTicker),
    )

    actual = _load_yfinance_history(
        "TEST",
        date(2025, 1, 1),
        date(2026, 1, 1),
    )

    assert actual is expected
    assert calls["symbol"] == "TEST"
    assert calls["repair"] is True
    assert calls["auto_adjust"] is True
    assert calls["actions"] is False
    assert calls["raise_errors"] is True


def test_price_history_quality_flags_sparse_stale_and_suspicious_rows() -> None:
    ticker = TickerConfig("TEST", "Test")
    closes = [100.0, 200.0, 201.0]
    frame = pd.DataFrame(
        {
            "Open": closes,
            "High": [value + 1.0 for value in closes],
            "Low": [value - 1.0 for value in closes],
            "Close": closes,
            "Volume": [0.0, 0.0, 1_000.0],
        },
        index=pd.to_datetime(["2026-01-02", "2026-01-20", "2026-01-21"]),
    )

    quality = price_history_quality(
        ticker,
        _bars(ticker, frame),
        requested_end=date(2026, 2, 10),
    )

    assert quality["status"] == "warning"
    assert quality["score"] < 50
    assert set(quality["reasons"]) == {
        "stale",
        "sparse",
        "extreme_returns",
        "zero_volume",
    }



@pytest.mark.parametrize(
    ("quality", "expected"),
    [
        ({"unavailable_count": 1, "warning_count": 0}, "insufficient"),
        (
            {
                "unavailable_count": 0,
                "warning_count": 1,
                "median_score": 40,
            },
            "fragile",
        ),
        (
            {
                "unavailable_count": 0,
                "warning_count": 1,
                "median_score": 80,
            },
            "mixed",
        ),
    ],
)
def test_data_quality_can_downgrade_overall_robustness(
    quality: dict[str, object], expected: str
) -> None:
    robustness = {"status": "stable"}
    _apply_data_quality_status(robustness, quality)
    assert robustness["status"] == expected


def test_history_provider_caches_validated_bars(tmp_path: Path) -> None:

    ticker = TickerConfig("TEST", "Test")
    frame = _trend_frame(180)
    calls: list[str] = []

    def loader(symbol: str, _start: date, _end: date):
        calls.append(symbol)
        return frame

    provider = HistoricalPriceProvider(loader)
    db_path = tmp_path / "prices.sqlite3"
    start = frame.index[0].date()
    end = frame.index[-1].date()
    with init_db(db_path) as conn:
        first = provider.load(
            conn,
            [ticker],
            start_date=start,
            end_date=end,
            max_workers=1,
        )
        second = provider.load(
            conn,
            [ticker],
            start_date=start,
            end_date=end,
            max_workers=1,
        )
        stored = load_backtest_price_bars(
            conn,
            ticker.symbol,
            start_date=start,
            end_date=end,
        )
        coverage = load_backtest_price_coverage(conn, ticker.symbol)

    assert calls == ["TEST"]
    assert first.fetched_symbols == ("TEST",)
    assert second.cache_hits == ("TEST",)
    assert len(stored) == len(frame)
    assert coverage is not None
    assert coverage["status"] == "success"
    assert coverage["coverage_start"] == start
    assert coverage["coverage_end"] == end


def test_normalize_history_rejects_impossible_candles() -> None:
    ticker = TickerConfig("TEST", "Test")
    frame = pd.DataFrame(
        {
            "Open": [100.0, 100.0, 100.0],
            "High": [101.0, 99.0, 101.0],
            "Low": [99.0, 98.0, 102.0],
            "Close": [100.5, 100.5, 100.5],
            "Volume": [1_000.0, 1_000.0, 1_000.0],
        },
        index=pd.date_range("2026-01-02", periods=3, freq="B"),
    )

    bars = normalize_history_frame(ticker, frame)

    assert len(bars) == 1
    assert bars[0].close == 100.5


def test_signal_generation_does_not_change_when_future_rows_change() -> None:
    ticker = TickerConfig("TEST", "Test")
    frame = _trend_frame()
    benchmark = _benchmark_frame()
    settings = _settings(frame)
    cutoff = frame.index[250].date()

    original = generate_signals(
        [ticker],
        {"TEST": frame},
        {"SPY": benchmark, "QQQ": benchmark},
        settings,
    ).signals
    changed = frame.copy()
    future_mask = changed.index.date > cutoff
    changed.loc[future_mask, ["Open", "High", "Low", "Close"]] *= 5.0
    changed.loc[future_mask, "Volume"] *= 20.0
    replay = generate_signals(
        [ticker],
        {"TEST": changed},
        {"SPY": benchmark, "QQQ": benchmark},
        settings,
    ).signals

    original_early = [
        asdict(signal) for signal in original if signal.signal_date <= cutoff
    ]
    replay_early = [
        asdict(signal) for signal in replay if signal.signal_date <= cutoff
    ]
    assert original_early
    assert replay_early == original_early


def test_cached_benchmark_returns_match_reference_path() -> None:
    frames = {
        "SPY": _benchmark_frame(),
        "QQQ": _benchmark_frame(),
    }
    history = _build_benchmark_history(frames)

    for index in (20, 60, 120, 180, 250):
        as_of_date = frames["SPY"].index[index].date()
        assert _benchmark_returns_at(history, as_of_date) == (
            _benchmark_returns_reference(frames, as_of_date)
        )


def test_entry_is_next_session_and_ambiguous_bar_stops_first() -> None:
    ticker = TickerConfig("TEST", "Test")
    signal_date = date(2026, 1, 5)
    entry_date = date(2026, 1, 6)
    signal = BacktestSignal(
        signal_id="sig-test",
        ticker="TEST",
        company_name="Test",
        market="us",
        currency="USD",
        signal_date=signal_date,
        entry_session=entry_date,
        setup="breakout",
        trigger_price=100.0,
        entry_reference=100.0,
        stop_price=95.0,
        risk_pct=5.0,
        score=70.0,
        rs_average=3.0,
        rule_version="test",
    )
    frame = pd.DataFrame(
        {
            "Open": [100.0],
            "High": [120.0],
            "Low": [90.0],
            "Close": [105.0],
            "Volume": [1_000_000.0],
        },
        index=pd.to_datetime([entry_date]),
    )
    settings = BacktestSettings(
        start_date=signal_date,
        end_date=entry_date,
        warmup_sessions=120,
        lookback_sessions=120,
    )

    _curve, trades, _diagnostics = _simulate_portfolio(
        [ticker],
        {"TEST": frame},
        [signal],
        settings,
        default_market_assumptions("us"),
    )

    assert len(trades) == 1
    trade = trades[0]
    assert trade.signal_date == signal_date
    assert trade.entry_date == entry_date
    assert trade.entry_date > trade.signal_date
    assert trade.exit_reason == "stop_first_ambiguous"
    assert trade.net_pnl < 0



def test_volume_participation_caps_position_size() -> None:
    ticker = TickerConfig("TEST", "Test")
    signal_date = date(2026, 1, 5)
    entry_date = date(2026, 1, 6)
    signal = BacktestSignal(
        signal_id="sig-volume",
        ticker=ticker.symbol,
        company_name=ticker.company_name,
        market=ticker.market,
        currency=ticker.currency,
        signal_date=signal_date,
        entry_session=entry_date,
        setup="breakout",
        trigger_price=100.0,
        entry_reference=100.0,
        stop_price=95.0,
        risk_pct=5.0,
        score=70.0,
        rs_average=3.0,
        rule_version="test",
    )
    frame = pd.DataFrame(
        {
            "Open": [100.0],
            "High": [101.0],
            "Low": [99.0],
            "Close": [100.0],
            "Volume": [1_000.0],
        },
        index=pd.to_datetime([entry_date]),
    )
    settings = BacktestSettings(
        start_date=signal_date,
        end_date=entry_date,
        warmup_sessions=120,
        lookback_sessions=120,
        max_volume_participation_pct=5.0,
    )

    _curve, trades, diagnostics = _simulate_portfolio(
        [ticker],
        {ticker.symbol: frame},
        [signal],
        settings,
        default_market_assumptions("us"),
    )

    assert len(trades) == 1
    assert trades[0].units == 50.0
    assert diagnostics["execution_adjustments"] == {
        "volume_capped_entries": 1
    }


def test_taiwan_locked_limit_bar_rejects_entry() -> None:
    ticker = TickerConfig(
        "2330.TW", "台積電", market="twse", currency="TWD"
    )
    signal = BacktestSignal(
        signal_id="sig-limit-entry",
        ticker=ticker.symbol,
        company_name=ticker.company_name,
        market=ticker.market,
        currency=ticker.currency,
        signal_date=date(2026, 1, 5),
        entry_session=date(2026, 1, 6),
        setup="breakout",
        trigger_price=100.0,
        entry_reference=100.0,
        stop_price=95.0,
        risk_pct=5.0,
        score=70.0,
        rs_average=3.0,
        rule_version="test",
    )
    frame = pd.DataFrame(
        {
            "Open": [100.0, 110.0],
            "High": [101.0, 110.0],
            "Low": [99.0, 110.0],
            "Close": [100.0, 110.0],
            "Volume": [1_000_000.0, 1_000_000.0],
        },
        index=pd.to_datetime(["2026-01-05", "2026-01-06"]),
    )
    settings = BacktestSettings(
        start_date=date(2026, 1, 5),
        end_date=date(2026, 1, 6),
        warmup_sessions=120,
        lookback_sessions=120,
    )

    assert _is_taiwan_locked_limit_bar(
        ticker, frame.loc[pd.Timestamp("2026-01-06")], 100.0
    )
    _curve, trades, diagnostics = _simulate_portfolio(
        [ticker],
        {ticker.symbol: frame},
        [signal],
        settings,
        default_market_assumptions("taiwan"),
    )

    assert trades == []
    assert diagnostics["simulation_rejections"]["locked_limit_entry"] == 1


def test_taiwan_locked_limit_down_defers_stop_exit() -> None:
    ticker = TickerConfig(
        "2330.TW", "台積電", market="twse", currency="TWD"
    )
    signal = BacktestSignal(
        signal_id="sig-limit-exit",
        ticker=ticker.symbol,
        company_name=ticker.company_name,
        market=ticker.market,
        currency=ticker.currency,
        signal_date=date(2026, 1, 5),
        entry_session=date(2026, 1, 6),
        setup="pullback",
        trigger_price=100.0,
        entry_reference=100.0,
        stop_price=95.0,
        risk_pct=5.0,
        score=70.0,
        rs_average=3.0,
        rule_version="test",
    )
    frame = pd.DataFrame(
        {
            "Open": [100.0, 100.0, 90.0, 91.0],
            "High": [101.0, 101.0, 90.0, 92.0],
            "Low": [99.0, 99.0, 90.0, 89.0],
            "Close": [100.0, 100.0, 90.0, 90.5],
            "Volume": [1_000_000.0] * 4,
        },
        index=pd.to_datetime(
            ["2026-01-05", "2026-01-06", "2026-01-07", "2026-01-08"]
        ),
    )
    settings = BacktestSettings(
        start_date=date(2026, 1, 5),
        end_date=date(2026, 1, 8),
        warmup_sessions=120,
        lookback_sessions=120,
    )

    _curve, trades, diagnostics = _simulate_portfolio(
        [ticker],
        {ticker.symbol: frame},
        [signal],
        settings,
        default_market_assumptions("taiwan"),
    )

    assert len(trades) == 1
    assert trades[0].exit_date == date(2026, 1, 8)
    assert trades[0].exit_reason == "gap_stop"
    assert diagnostics["execution_adjustments"] == {
        "locked_limit_exit_deferred": 1
    }

def test_taiwan_stock_and_etf_sell_tax_are_distinct() -> None:
    assumptions = default_market_assumptions("taiwan")
    signal = BacktestSignal(
        signal_id="sig-tax",
        ticker="2330.TW",
        company_name="Test",
        market="twse",
        currency="TWD",
        signal_date=date(2026, 1, 2),
        entry_session=date(2026, 1, 5),
        setup="pullback",
        trigger_price=100.0,
        entry_reference=100.0,
        stop_price=95.0,
        risk_pct=5.0,
        score=70.0,
        rs_average=2.0,
        rule_version="test",
    )

    def position(ticker: TickerConfig) -> _OpenPosition:
        return _OpenPosition(
            ticker=ticker,
            signal=signal,
            units=1_000.0,
            entry_date=date(2026, 1, 5),
            entry_reference=100.0,
            entry_price=100.0,
            initial_stop=95.0,
            target_price=110.0,
            entry_commission=142.5,
            entry_slippage=0.0,
            holding_sessions=5,
        )

    stock, _ = _close_position(
        position(TickerConfig("2330.TW", "TSMC", market="twse", currency="TWD")),
        date(2026, 1, 12),
        105.0,
        "time_exit",
        assumptions,
    )
    etf, _ = _close_position(
        position(
            TickerConfig(
                "0050.TW",
                "ETF",
                market="twse",
                currency="TWD",
                has_fundamentals=False,
            )
        ),
        date(2026, 1, 12),
        105.0,
        "time_exit",
        assumptions,
    )

    assert stock.sell_tax == pytest.approx(stock.exit_price * 1_000 * 0.003)
    assert etf.sell_tax == pytest.approx(etf.exit_price * 1_000 * 0.001)
    assert stock.sell_tax == pytest.approx(etf.sell_tax * 3)



def test_taiwan_uses_investable_benchmark_and_index_for_relative_strength() -> None:
    assumptions = default_market_assumptions("taiwan")
    references = {
        ticker.symbol: ticker for ticker in benchmark_tickers(("taiwan",))
    }

    assert assumptions.benchmark_symbol == "0050.TW"
    assert assumptions.rs_benchmark_symbols == ("^TWII",)
    assert set(references) == {"0050.TW", "^TWII"}
    assert references["0050.TW"].market == "twse"
    assert references["0050.TW"].currency == "TWD"
    assert references["^TWII"].market == "twse"

def test_market_backtest_isolated_and_deterministic() -> None:
    frame = _trend_frame()
    benchmark = _benchmark_frame()
    us = TickerConfig("US1", "US")
    tw = TickerConfig("2330.TW", "TW", market="twse", currency="TWD")
    spy = TickerConfig("SPY", "SPY", has_fundamentals=False)
    qqq = TickerConfig("QQQ", "QQQ", has_fundamentals=False)
    bars = {
        "US1": _bars(us, frame),
        "2330.TW": _bars(tw, frame),
        "SPY": _bars(spy, benchmark),
        "QQQ": _bars(qqq, benchmark),
    }
    settings = _settings(frame)

    first = run_market_backtest(
        [us, tw],
        bars,
        settings,
        default_market_assumptions("us"),
    )
    second = run_market_backtest(
        [us, tw],
        bars,
        settings,
        default_market_assumptions("us"),
    )

    assert first.diagnostics["configured_symbols"] == 1
    assert all(trade.ticker == "US1" for trade in first.trades)
    assert asdict(first) == asdict(second)
    assert first.robustness["status"] in {
        "stable", "mixed", "fragile", "insufficient"
    }
    assert first.robustness["walk_forward"]["summary"]["requested_folds"] == 5
    assert first.robustness["sensitivity"]["summary"]["scenario_count"] == 9
    assert len(first.robustness["sensitivity"]["rows"]) == 9



def test_full_runner_writes_auditable_reports_and_storage(tmp_path: Path) -> None:
    frame = _trend_frame(300)
    benchmark = _benchmark_frame(300)
    frames = {"TEST": frame, "SPY": benchmark, "QQQ": benchmark}

    def loader(symbol: str, _start: date, _end: date):
        return frames[symbol]

    config_path = tmp_path / "watchlist.yaml"
    config_path.write_text(
        """
settings:
  report_timezone: Asia/Taipei
tickers:
  - symbol: TEST
    company_name: Test Company
    market: us
    currency: USD
""".strip()
        + "\n",
        encoding="utf-8",
    )
    settings = BacktestSettings(
        start_date=frame.index[140].date(),
        end_date=frame.index[-1].date(),
        warmup_sessions=120,
        lookback_sessions=180,
        max_holding_sessions=20,
    )
    db_path = tmp_path / "stock.sqlite3"
    artifacts = run_backtest(
        config_path=config_path,
        settings=settings,
        markets=("us",),
        output_dir=tmp_path / "reports",
        db_path=db_path,
        provider=HistoricalPriceProvider(loader),
        generated_at=datetime(2026, 8, 10, 9, 30, tzinfo=timezone.utc),
        max_workers=1,
        verify_replay=True,
        progress=False,
    )
    expected_result_fingerprint = _fingerprint(
        {
            "rule_version": artifacts.result.rule_version,
            "markets": [asdict(market) for market in artifacts.result.markets],
        }
    )
    assert artifacts.result.result_fingerprint == expected_result_fingerprint


    assert artifacts.result.deterministic_replay_passed is True
    assert artifacts.result.universe_source == "current_watchlist"
    assert [member.ticker for member in artifacts.result.universe] == ["TEST"]
    assert artifacts.result.markets[0].diagnostics["data_quality"]["symbol_count"] == 1
    assert set(artifacts.paths) == {"html", "markdown", "json"}
    assert all(path.exists() for path in artifacts.paths.values())
    assert "backtests" in artifacts.paths["html"].parts
    html = artifacts.paths["html"].read_text(encoding="utf-8")
    markdown = artifacts.paths["markdown"].read_text(encoding="utf-8")
    assert "右側交易回測" in html
    assert "右側交易回測" in markdown
    assert "????" not in html + markdown
    assert "穩健度驗證" in html + markdown
    assert "查看驗證明細" in html
    assert 'data-market="us"' in html
    assert 'data-market="taiwan"' not in html
    payload = json.loads(artifacts.paths["json"].read_text(encoding="utf-8"))
    assert payload["run_id"] == artifacts.result.run_id
    assert payload["deterministic_replay_passed"] is True
    assert payload["universe_source"] == "current_watchlist"
    assert payload["universe"][0]["ticker"] == "TEST"
    assert payload["markets"][0]["robustness"]["sensitivity"]["rows"]

    with init_db(db_path) as conn:
        stored = load_backtest_run(conn, artifacts.result.run_id)
        trade_count = conn.execute(
            "SELECT COUNT(*) FROM backtest_trades WHERE run_id = ?",
            (artifacts.result.run_id,),
        ).fetchone()[0]
        universe_count = conn.execute(
            "SELECT COUNT(*) FROM backtest_universe_members WHERE run_id = ?",
            (artifacts.result.run_id,),
        ).fetchone()[0]

    assert stored is not None
    assert stored["deterministic_replay_passed"] is True
    assert trade_count == len(artifacts.result.markets[0].trades)
    assert stored["universe_source"] == "current_watchlist"
    assert stored["universe"][0]["ticker"] == "TEST"
    assert universe_count == 1
