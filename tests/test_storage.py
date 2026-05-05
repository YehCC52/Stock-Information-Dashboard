import sqlite3
from datetime import date, datetime, timezone
from pathlib import Path

from stock_daily_research.models import (
    DailyReport,
    EarningsDate,
    NewsArticle,
    TickerConfig,
    TickerReport,
    ValuationSnapshot,
)
from stock_daily_research.storage import init_db, load_latest_valuation_snapshot, save_report


def _make_article(ticker: str, url: str = "https://example.com/a") -> NewsArticle:
    return NewsArticle(
        ticker=ticker,
        title="Headline",
        source="Reuters",
        domain="reuters.com",
        published_at=datetime.now(timezone.utc),
        url=url,
        summary="",
        event_type="earnings",
        importance_score=1.0,
    )


def _make_earnings(ticker: str = "NVDA") -> EarningsDate:
    return EarningsDate(
        ticker=ticker,
        company_name="NVIDIA Corporation",
        earnings_date=date(2026, 5, 21),
        time_of_day="unknown",
        fiscal_quarter=None,
        fiscal_year=None,
        eps_estimate=None,
        revenue_estimate=None,
        source="yfinance",
        source_retrieved_at=datetime.now(timezone.utc),
    )


def _make_valuation(ticker: str = "NVDA", as_of: date = date(2026, 4, 27)) -> ValuationSnapshot:
    return ValuationSnapshot(
        ticker=ticker,
        as_of_date=as_of,
        source="yfinance",
        metrics={"market_cap": 100_000_000, "trailing_pe": 25.5, "peg_ratio": None},
        retrieved_at=datetime(2026, 4, 27, 8, 0, tzinfo=timezone.utc),
    )


def _wrap(ticker_symbol: str, articles=None, earnings=None, valuation=None) -> DailyReport:
    return DailyReport(
        report_date=date(2026, 4, 28),
        generated_at=datetime.now(timezone.utc),
        ticker_reports=[
            TickerReport(
                ticker=TickerConfig(symbol=ticker_symbol, company_name=f"{ticker_symbol} Inc"),
                articles=articles or [],
                x_signals=[],
                valuation=valuation,
                earnings=earnings,
            )
        ],
    )


def test_news_articles_unique_per_ticker_not_per_url(tmp_path: Path) -> None:
    db_path = tmp_path / "stock.sqlite3"
    nvda_article = _make_article("NVDA")
    msft_article = _make_article("MSFT")  # same URL, different ticker

    with init_db(db_path) as conn:
        save_report(conn, _wrap("NVDA", articles=[nvda_article]))
        save_report(conn, _wrap("MSFT", articles=[msft_article]))
        rows = conn.execute("SELECT ticker FROM news_articles ORDER BY ticker").fetchall()

    assert [row[0] for row in rows] == ["MSFT", "NVDA"]


def test_earnings_dates_idempotent_across_runs(tmp_path: Path) -> None:
    db_path = tmp_path / "stock.sqlite3"
    earnings = _make_earnings()

    with init_db(db_path) as conn:
        save_report(conn, _wrap("NVDA", earnings=earnings))
        save_report(conn, _wrap("NVDA", earnings=earnings))
        save_report(conn, _wrap("NVDA", earnings=earnings))
        count = conn.execute("SELECT COUNT(*) FROM earnings_dates").fetchone()[0]

    assert count == 1


def test_init_db_migrates_legacy_news_articles_unique(tmp_path: Path) -> None:
    db_path = tmp_path / "stock.sqlite3"
    legacy_schema = """
    CREATE TABLE news_articles (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      ticker TEXT NOT NULL,
      title TEXT NOT NULL,
      source TEXT NOT NULL,
      domain TEXT NOT NULL,
      published_at TEXT,
      url TEXT NOT NULL UNIQUE,
      summary TEXT NOT NULL,
      event_type TEXT NOT NULL,
      importance_score REAL NOT NULL
    );
    """
    with sqlite3.connect(db_path) as conn:
        conn.executescript(legacy_schema)
        conn.execute(
            "INSERT INTO news_articles (ticker, title, source, domain, published_at, url, summary, event_type, importance_score) "
            "VALUES ('NVDA', 't', 's', 'd', NULL, 'https://x/a', '', 'other', 0.3)"
        )

    with init_db(db_path) as conn:
        save_report(conn, _wrap("MSFT", articles=[_make_article("MSFT", url="https://x/a")]))
        tickers = [
            row[0]
            for row in conn.execute("SELECT ticker FROM news_articles ORDER BY ticker").fetchall()
        ]

    assert tickers == ["MSFT", "NVDA"]


def test_init_db_migrates_legacy_earnings_dates_no_unique(tmp_path: Path) -> None:
    db_path = tmp_path / "stock.sqlite3"
    legacy_schema = """
    CREATE TABLE earnings_dates (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      ticker TEXT NOT NULL,
      company_name TEXT NOT NULL,
      earnings_date TEXT,
      time_of_day TEXT NOT NULL,
      fiscal_quarter TEXT,
      fiscal_year INTEGER,
      eps_estimate REAL,
      revenue_estimate REAL,
      source TEXT NOT NULL,
      source_retrieved_at TEXT NOT NULL
    );
    """
    with sqlite3.connect(db_path) as conn:
        conn.executescript(legacy_schema)
        for _ in range(3):
            conn.execute(
                "INSERT INTO earnings_dates (ticker, company_name, earnings_date, time_of_day, source, source_retrieved_at) "
                "VALUES ('NVDA', 'NVIDIA', '2026-05-21', 'unknown', 'yfinance', '2026-04-28T00:00:00+00:00')"
            )

    with init_db(db_path) as conn:
        count = conn.execute("SELECT COUNT(*) FROM earnings_dates").fetchone()[0]
        save_report(conn, _wrap("NVDA", earnings=_make_earnings()))
        count_after = conn.execute("SELECT COUNT(*) FROM earnings_dates").fetchone()[0]

    assert count == 1  # dedup during migration
    assert count_after == 1  # idempotent on subsequent save


def test_load_latest_valuation_snapshot_returns_good_values(tmp_path: Path) -> None:
    db_path = tmp_path / "stock.sqlite3"
    valuation = _make_valuation()

    with init_db(db_path) as conn:
        save_report(conn, _wrap("NVDA", valuation=valuation))
        loaded = load_latest_valuation_snapshot(conn, "NVDA", before_or_on=date(2026, 4, 28))

    assert loaded is not None
    assert loaded.as_of_date == date(2026, 4, 27)
    assert loaded.metrics["market_cap"] == 100_000_000
    assert loaded.metrics["trailing_pe"] == 25.5
