from datetime import date, datetime, timezone
from pathlib import Path

from stock_daily_research.models import DailyReport, InvestmentPlan, MarketContext, MarketSentiment, PremarketSnapshot, TickerConfig, TickerReport, TickerResearchState, ValuationSnapshot
from stock_daily_research.runner import _apply_plan_defaults, run_daily
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


def test_apply_plan_defaults_db_overrides_yaml() -> None:
    tickers = [
        TickerConfig(
            symbol="NVDA",
            company_name="NVIDIA Corporation",
            plan=InvestmentPlan(bull_case="YAML bull", bear_case="YAML bear"),
        )
    ]
    states = {"NVDA": TickerResearchState(ticker="NVDA", bull_case="DB bull")}
    merged = _apply_plan_defaults(states, tickers)
    # Non-empty DB field wins; empty DB field falls back to YAML.
    assert merged["NVDA"].bull_case == "DB bull"
    assert merged["NVDA"].bear_case == "YAML bear"


def test_apply_plan_defaults_ignores_empty_plan() -> None:
    tickers = [TickerConfig(symbol="NVDA", company_name="NVIDIA Corporation")]
    states = {"NVDA": TickerResearchState(ticker="NVDA", note="keep me")}
    merged = _apply_plan_defaults(states, tickers)
    assert merged["NVDA"].note == "keep me"
    assert merged["NVDA"].bull_case == ""


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
            metrics={"next_fy_revenue": 110.0, "next_q_revenue": 55.0},
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
