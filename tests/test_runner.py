from datetime import date, datetime, timezone
from pathlib import Path

from unittest.mock import patch

from stock_daily_research.models import DailyReport, InvestmentPlan, MarketContext, MarketSentiment, PositionConfig, PremarketSnapshot, ResearchDefaults, TickerConfig, TickerReport, TickerResearchState, ValuationSnapshot
from stock_daily_research.runner import _apply_plan_defaults, _apply_position_overrides, _has_usable_valuation, run_daily
from stock_daily_research.storage import init_db, save_report


CONFIG_BODY = """
settings:
  report_timezone: UTC
  news:
    lookback_days: 3
    max_articles_per_ticker: 5
tickers:
  - symbol: NVDA
    company_name: NVIDIA Corporation
    trusted_news_domains:
      - reuters.com
"""


def _sentiment() -> MarketSentiment:
    return MarketSentiment(
        score=50,
        label="Neutral",
        source="test",
        retrieved_at=datetime(2026, 4, 28, tzinfo=timezone.utc),
    )


def _premarket() -> PremarketSnapshot:
    return PremarketSnapshot(
        retrieved_at=datetime(2026, 4, 28, tzinfo=timezone.utc),
    )


def _market_context() -> MarketContext:
    return MarketContext(retrieved_at=datetime(2026, 4, 28, tzinfo=timezone.utc))


def _write_config(tmp_path: Path) -> Path:
    config = tmp_path / "watchlist.yaml"
    config.write_text(CONFIG_BODY, encoding="utf-8")
    return config


def test_apply_plan_defaults_seeds_from_yaml() -> None:
    tickers = [
        TickerConfig(
            symbol="NVDA",
            company_name="NVIDIA Corporation",
            plan=InvestmentPlan(bull_case="AI capex", stop_loss="Close below 50MA"),
        )
    ]
    merged = _apply_plan_defaults({}, tickers)
    assert merged["NVDA"].bull_case == "AI capex"
    assert merged["NVDA"].stop_loss == "Close below 50MA"
    assert merged["NVDA"].bear_case == ""


def test_apply_plan_defaults_seeds_research_defaults_from_yaml() -> None:
    tickers = [
        TickerConfig(
            symbol="NVDA",
            company_name="NVIDIA Corporation",
            research=ResearchDefaults(
                thesis_state="active",
                thesis_trigger="execution",
                thesis_text="AI data-center execution.",
                revisit_date=date(2026, 6, 4),
            ),
        )
    ]
    merged = _apply_plan_defaults({}, tickers)
    assert merged["NVDA"].thesis_state == "active"
    assert merged["NVDA"].thesis_trigger == "execution"
    assert merged["NVDA"].thesis_text == "AI data-center execution."
    assert merged["NVDA"].revisit_date == date(2026, 6, 4)


def test_apply_plan_defaults_db_overrides_yaml() -> None:
    tickers = [
        TickerConfig(
            symbol="NVDA",
            company_name="NVIDIA Corporation",
            plan=InvestmentPlan(bull_case="YAML bull", bear_case="YAML bear"),
            research=ResearchDefaults(thesis_state="active", thesis_trigger="execution"),
        )
    ]
    states = {"NVDA": TickerResearchState(ticker="NVDA", bull_case="DB bull", thesis_state="weakening")}
    merged = _apply_plan_defaults(states, tickers)
    # Non-empty DB field wins; empty DB field falls back to YAML.
    assert merged["NVDA"].bull_case == "DB bull"
    assert merged["NVDA"].bear_case == "YAML bear"
    assert merged["NVDA"].thesis_state == "weakening"
    assert merged["NVDA"].thesis_trigger == "execution"


def test_apply_plan_defaults_ignores_empty_plan() -> None:
    tickers = [TickerConfig(symbol="NVDA", company_name="NVIDIA Corporation")]
    states = {"NVDA": TickerResearchState(ticker="NVDA", note="keep me")}
    merged = _apply_plan_defaults(states, tickers)
    assert merged["NVDA"].note == "keep me"
    assert merged["NVDA"].bull_case == ""


def test_apply_position_overrides_merges_research_state_position() -> None:
    tickers = [
        TickerConfig(
            symbol="NVDA",
            company_name="NVIDIA Corporation",
            position=PositionConfig(status="watchlist", portfolio_weight=2.0),
        )
    ]
    states = {
        "NVDA": TickerResearchState(
            ticker="NVDA",
            position=PositionConfig(status="holding", shares=10.0, avg_cost=120.0),
        )
    }

    merged = _apply_position_overrides(tickers, states)

    assert merged[0].position.status == "holding"
    assert merged[0].position.shares == 10.0
    assert merged[0].position.avg_cost == 120.0
    assert merged[0].position.portfolio_weight == 2.0


def test_run_daily_writes_report_and_db(tmp_path: Path, monkeypatch) -> None:
    config_path = _write_config(tmp_path)
    output_dir = tmp_path / "reports"
    db_path = tmp_path / "stock.sqlite3"

    def fake_fetch_for_ticker(self, ticker, lookback_days, max_articles):
        return [], []

    monkeypatch.setattr(
        "stock_daily_research.runner.GoogleNewsRssProvider.fetch_for_ticker",
        fake_fetch_for_ticker,
    )

    report = run_daily(
        config_path=config_path,
        report_date=date(2026, 4, 28),
        output_dir=output_dir,
        db_path=db_path,
        fetch_news=True,
        fetch_valuation=False,
        fetch_macro=False,
        notify_telegram=False,
    )

    assert (output_dir / "2026-04-28.md").exists()
    assert db_path.exists()
    assert report.report_date == date(2026, 4, 28)
    assert len(report.ticker_reports) == 1


def test_run_daily_records_valuation_failure_as_warning(tmp_path: Path, monkeypatch) -> None:
    config_path = _write_config(tmp_path)

    def boom_valuation(_ticker):
        raise RuntimeError("yfinance offline")

    def boom_earnings(_ticker):
        raise RuntimeError("no earnings")

    monkeypatch.setattr("stock_daily_research.runner.fetch_yfinance_valuation", boom_valuation)
    monkeypatch.setattr("stock_daily_research.runner.fetch_yfinance_earnings_date", boom_earnings)
    monkeypatch.setattr("stock_daily_research.runner.fetch_market_sentiment", _sentiment)
    monkeypatch.setattr("stock_daily_research.runner.fetch_overnight_premarket", lambda *_args, **_kwargs: _premarket())

    report = run_daily(
        config_path=config_path,
        report_date=date(2026, 4, 28),
        output_dir=tmp_path / "reports",
        db_path=tmp_path / "stock.sqlite3",
        fetch_news=False,
        fetch_valuation=True,
        fetch_macro=False,
    )

    warnings = report.ticker_reports[0].warnings
    assert any("Valuation fetch failed" in w for w in warnings)
    assert any("Earnings date fetch failed" in w for w in warnings)


def test_run_daily_uses_last_good_valuation_when_current_fetch_is_empty(tmp_path: Path, monkeypatch) -> None:
    config_path = _write_config(tmp_path)
    db_path = tmp_path / "stock.sqlite3"
    previous = ValuationSnapshot(
        ticker="NVDA",
        as_of_date=date(2026, 4, 27),
        source="yfinance",
        metrics={"market_cap": 123_000_000, "trailing_pe": 25.5},
        retrieved_at=datetime(2026, 4, 27, 8, 0, tzinfo=timezone.utc),
    )
    previous_report = DailyReport(
        report_date=date(2026, 4, 27),
        generated_at=datetime(2026, 4, 27, 8, 0, tzinfo=timezone.utc),
        ticker_reports=[
            TickerReport(
                ticker=TickerConfig(symbol="NVDA", company_name="NVIDIA Corporation"),
                articles=[],
                x_signals=[],
                valuation=previous,
                earnings=None,
            )
        ],
    )
    with init_db(db_path) as conn:
        save_report(conn, previous_report)

    def empty_valuation(_ticker):
        return ValuationSnapshot(
            ticker="NVDA",
            as_of_date=date(2026, 4, 28),
            source="yfinance",
            metrics={"market_cap": None, "trailing_pe": None},
            retrieved_at=datetime(2026, 4, 28, 8, 0, tzinfo=timezone.utc),
        )

    monkeypatch.setattr("stock_daily_research.runner.fetch_yfinance_valuation", empty_valuation)
    monkeypatch.setattr("stock_daily_research.runner.fetch_yfinance_earnings_date", lambda _ticker: None)
    monkeypatch.setattr("stock_daily_research.runner.fetch_market_sentiment", _sentiment)
    monkeypatch.setattr("stock_daily_research.runner.fetch_overnight_premarket", lambda *_args, **_kwargs: _premarket())

    report = run_daily(
        config_path=config_path,
        report_date=date(2026, 4, 28),
        output_dir=tmp_path / "reports",
        db_path=db_path,
        fetch_news=False,
        fetch_valuation=True,
        fetch_macro=False,
    )

    ticker_report = report.ticker_reports[0]
    assert ticker_report.valuation is not None
    assert ticker_report.valuation.as_of_date == date(2026, 4, 27)
    assert ticker_report.valuation.metrics["market_cap"] == 123_000_000
    assert any("Valuation fallback used" in warning for warning in ticker_report.warnings)


def test_run_daily_derives_revenue_revisions_from_valuation_history(tmp_path: Path, monkeypatch) -> None:
    config_path = _write_config(tmp_path)
    db_path = tmp_path / "stock.sqlite3"
    previous = ValuationSnapshot(
        ticker="NVDA",
        as_of_date=date(2026, 3, 20),
        source="yfinance",
        metrics={"next_fy_revenue": 100.0, "next_q_revenue": 50.0},
        retrieved_at=datetime(2026, 3, 20, 8, 0, tzinfo=timezone.utc),
    )
    previous_report = DailyReport(
        report_date=date(2026, 3, 20),
        generated_at=datetime(2026, 3, 20, 8, 0, tzinfo=timezone.utc),
        ticker_reports=[
            TickerReport(
                ticker=TickerConfig(symbol="NVDA", company_name="NVIDIA Corporation"),
                articles=[],
                x_signals=[],
                valuation=previous,
                earnings=None,
            )
        ],
    )
    with init_db(db_path) as conn:
        save_report(conn, previous_report)

    def current_valuation(_ticker):
        return ValuationSnapshot(
            ticker="NVDA",
            as_of_date=date(2026, 4, 28),
            source="yfinance",
            metrics={"last_close": 900.0, "next_fy_revenue": 110.0, "next_q_revenue": 55.0},
            retrieved_at=datetime(2026, 4, 28, 8, 0, tzinfo=timezone.utc),
        )

    monkeypatch.setattr("stock_daily_research.runner.fetch_yfinance_valuation", current_valuation)
    monkeypatch.setattr("stock_daily_research.runner.fetch_yfinance_earnings_date", lambda _ticker: None)
    monkeypatch.setattr("stock_daily_research.runner.fetch_market_sentiment", _sentiment)
    monkeypatch.setattr("stock_daily_research.runner.fetch_market_context", _market_context)
    monkeypatch.setattr("stock_daily_research.runner.fetch_overnight_premarket", lambda *_args, **_kwargs: _premarket())

    report = run_daily(
        config_path=config_path,
        report_date=date(2026, 4, 28),
        output_dir=tmp_path / "reports",
        db_path=db_path,
        fetch_news=False,
        fetch_valuation=True,
        fetch_macro=False,
    )

    metrics = report.ticker_reports[0].valuation.metrics
    assert metrics["fy1_revenue_revision_30d"] == 10.0
    assert metrics["next_q_revenue_revision_30d"] == 10.0


def test_run_daily_records_skipped_fetches_as_global_warnings(tmp_path: Path) -> None:
    config_path = _write_config(tmp_path)

    report = run_daily(
        config_path=config_path,
        report_date=date(2026, 4, 28),
        output_dir=tmp_path / "reports",
        db_path=tmp_path / "stock.sqlite3",
        fetch_news=False,
        fetch_valuation=False,
        fetch_macro=False,
    )

    assert "News fetching skipped by --no-news." in report.warnings
    assert "Valuation and earnings fetching skipped by --no-valuation." in report.warnings
    assert "Macro calendar fetching skipped by --no-macro." in report.warnings


def test_has_usable_valuation_requires_last_close() -> None:
    assert _has_usable_valuation({"last_close": 150.0, "trailing_pe": None}) is True
    assert _has_usable_valuation({"last_close": None, "trailing_pe": 25.0}) is False
    assert _has_usable_valuation({"last_close": None}) is False
    assert _has_usable_valuation({}) is False


def test_valuation_retry_succeeds_on_third_attempt(tmp_path: Path, monkeypatch) -> None:
    config_path = _write_config(tmp_path)
    db_path = tmp_path / "stock.sqlite3"
    attempts = {"count": 0}

    def flaky_valuation(_ticker):
        attempts["count"] += 1
        if attempts["count"] < 3:
            raise RuntimeError("transient error")
        return ValuationSnapshot(
            ticker="NVDA",
            as_of_date=date(2026, 4, 28),
            source="yfinance",
            metrics={"last_close": 900.0},
            retrieved_at=datetime(2026, 4, 28, 8, 0, tzinfo=timezone.utc),
        )

    monkeypatch.setattr("stock_daily_research.runner.fetch_yfinance_valuation", flaky_valuation)
    monkeypatch.setattr("stock_daily_research.runner.fetch_yfinance_earnings_date", lambda _: None)
    monkeypatch.setattr("stock_daily_research.runner.fetch_market_sentiment", _sentiment)
    monkeypatch.setattr("stock_daily_research.runner.fetch_market_context", _market_context)
    monkeypatch.setattr("stock_daily_research.runner.fetch_overnight_premarket", lambda *_a, **_k: _premarket())
    monkeypatch.setattr("stock_daily_research.runner.time.sleep", lambda _: None)

    report = run_daily(
        config_path=config_path,
        report_date=date(2026, 4, 28),
        output_dir=tmp_path / "reports",
        db_path=db_path,
        fetch_news=False,
        fetch_valuation=True,
        fetch_macro=False,
    )

    assert attempts["count"] == 3
    assert report.ticker_reports[0].valuation is not None
    warnings_text = " ".join(report.ticker_reports[0].warnings)
    assert "failed" not in warnings_text


def test_valuation_all_retries_exhausted_produces_warning(tmp_path: Path, monkeypatch) -> None:
    config_path = _write_config(tmp_path)
    db_path = tmp_path / "stock.sqlite3"

    monkeypatch.setattr("stock_daily_research.runner.fetch_yfinance_valuation", lambda _: (_ for _ in ()).throw(RuntimeError("always fails")))
    monkeypatch.setattr("stock_daily_research.runner.fetch_yfinance_earnings_date", lambda _: None)
    monkeypatch.setattr("stock_daily_research.runner.fetch_market_sentiment", _sentiment)
    monkeypatch.setattr("stock_daily_research.runner.fetch_market_context", _market_context)
    monkeypatch.setattr("stock_daily_research.runner.fetch_overnight_premarket", lambda *_a, **_k: _premarket())
    monkeypatch.setattr("stock_daily_research.runner.time.sleep", lambda _: None)

    report = run_daily(
        config_path=config_path,
        report_date=date(2026, 4, 28),
        output_dir=tmp_path / "reports",
        db_path=db_path,
        fetch_news=False,
        fetch_valuation=True,
        fetch_macro=False,
    )

    warnings_text = " ".join(report.ticker_reports[0].warnings)
    assert "failed after 4 attempts" in warnings_text
