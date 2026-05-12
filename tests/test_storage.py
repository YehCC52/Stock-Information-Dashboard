import sqlite3
from datetime import date, datetime, timezone
from pathlib import Path

from stock_daily_research.models import (
    DailyReport,
    EarningsDate,
    NewsArticle,
    PostEarningsReview,
    TickerConfig,
    TickerHistoryPoint,
    TickerResearchState,
    TickerReport,
    ValuationSnapshot,
)
from stock_daily_research.storage import (
    export_research_state_payload,
    import_research_state_payload,
    init_db,
    load_latest_valuation_snapshot,
    load_ticker_history,
    load_ticker_research_states,
    load_post_earnings_reviews,
    save_report,
    save_report_run,
)


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


def test_research_state_export_import_roundtrip(tmp_path: Path) -> None:
    db_path = tmp_path / "stock.sqlite3"
    report = DailyReport(
        report_date=date(2026, 4, 28),
        generated_at=datetime(2026, 4, 28, 8, 0, tzinfo=timezone.utc),
        ticker_reports=[
            TickerReport(
                ticker=TickerConfig(symbol="NVDA", company_name="NVIDIA Corporation"),
                articles=[],
                x_signals=[],
                valuation=None,
                earnings=None,
            )
        ],
        research_states={
            "NVDA": TickerResearchState(
                ticker="NVDA",
                tag="High conviction",
                thesis_state="active",
                thesis_trigger="guidance",
                note="Demand still broadening.",
                checklist=["earnings", "valuation", "news", "thesis"],
                revisit_date=date(2026, 5, 1),
                pinned=True,
                review_status="reviewed",
                last_reviewed_at=datetime(2026, 4, 28, 7, 30, tzinfo=timezone.utc),
            )
        },
        post_earnings_reviews={
            "NVDA": PostEarningsReview(
                ticker="NVDA",
                earnings_date=date(2026, 4, 27),
                eps="beat",
                revenue="beat",
                guide="up",
                eps_surprise_pct=8.2,
                revenue_surprise_pct=3.1,
                conclusion="Thesis intact.",
                next_step="Watch valuation reaction.",
            )
        },
    )

    with init_db(db_path) as conn:
        save_report(conn, report)
        payload = export_research_state_payload(conn)

    with init_db(tmp_path / "import.sqlite3") as conn:
        import_research_state_payload(conn, payload)
        state = load_ticker_research_states(conn, ["NVDA"])["NVDA"]
        review = load_post_earnings_reviews(conn, ["NVDA"])["NVDA"]

    assert payload["tickers"]["NVDA"]["thesis_state"] == "active"
    assert state.tag == "High conviction"
    assert state.checklist == ["earnings", "news", "thesis", "valuation"]
    assert state.pinned is True
    assert review.guide == "up"
    assert review.conclusion == "Thesis intact."


def test_save_report_run_persists_history_points(tmp_path: Path) -> None:
    db_path = tmp_path / "stock.sqlite3"
    ticker = TickerConfig(symbol="NVDA", company_name="NVIDIA Corporation")
    valuation_old = _make_valuation(as_of=date(2026, 4, 27))
    valuation_new = ValuationSnapshot(
        ticker="NVDA",
        as_of_date=date(2026, 4, 28),
        source="yfinance",
        metrics={
            "market_cap": 100_000_000,
            "trailing_pe": 120.0,
            "rsi_14": 73.0,
            "last_close": 110.0,
            "previous_close": 100.0,
        },
        retrieved_at=datetime(2026, 4, 28, 8, 0, tzinfo=timezone.utc),
    )
    old_report = DailyReport(
        report_date=date(2026, 4, 27),
        generated_at=datetime(2026, 4, 27, 8, 0, tzinfo=timezone.utc),
        ticker_reports=[
            TickerReport(ticker=ticker, articles=[], x_signals=[], valuation=valuation_old, earnings=None)
        ],
        research_states={"NVDA": TickerResearchState(ticker="NVDA", thesis_state="building", review_status="in-progress")},
    )
    article = _make_article("NVDA")
    new_report = DailyReport(
        report_date=date(2026, 4, 28),
        generated_at=datetime(2026, 4, 28, 8, 0, tzinfo=timezone.utc),
        ticker_reports=[
            TickerReport(ticker=ticker, articles=[article], x_signals=[], valuation=valuation_new, earnings=_make_earnings())
        ],
        research_states={"NVDA": TickerResearchState(ticker="NVDA", thesis_state="active", review_status="reviewed")},
    )

    with init_db(db_path) as conn:
        save_report(conn, old_report)
        save_report_run(conn, old_report)
        save_report(conn, new_report)
        save_report_run(conn, new_report)
        history = load_ticker_history(conn, ["NVDA"], report_date=date(2026, 4, 28), history_days=30)["NVDA"]

    assert len(history) == 2
    assert history[0].report_date == date(2026, 4, 28)
    assert history[0].thesis_state == "active"
    assert history[0].top_news_count == 1
    assert history[0].valuation_risk == "High"
    assert history[0].daily_change_pct == 10.0
    assert history[0].earnings_days == 23
    assert history[1].thesis_state == "building"
