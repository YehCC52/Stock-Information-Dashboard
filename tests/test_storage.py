import sqlite3
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from stock_daily_research.models import (
    DailyReport,
    EarningsDate,
    NewsArticle,
    PostEarningsReview,
    PositionConfig,
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
    load_fresh_valuation_snapshot,
    load_latest_valuation_snapshot,
    load_next_earnings_date,
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


def test_save_article_preserves_row_id_on_refetch(tmp_path: Path) -> None:
    """Re-saving the same (ticker, url) must UPDATE in place, keeping the row id
    stable (the old INSERT OR REPLACE deleted + reinserted, churning the id)."""
    db_path = tmp_path / "stock.sqlite3"

    with init_db(db_path) as conn:
        save_report(conn, _wrap("NVDA", articles=[_make_article("NVDA", url="https://x/a")]))
        first_id = conn.execute("SELECT id FROM news_articles WHERE ticker='NVDA'").fetchone()[0]

        refetched = NewsArticle(
            ticker="NVDA", title="Updated headline", source="Reuters", domain="reuters.com",
            published_at=datetime.now(timezone.utc), url="https://x/a", summary="now with detail",
            event_type="earnings", importance_score=2.5,
        )
        save_report(conn, _wrap("NVDA", articles=[refetched]))
        rows = conn.execute(
            "SELECT id, title, importance_score FROM news_articles WHERE ticker='NVDA'"
        ).fetchall()

    assert len(rows) == 1
    assert rows[0][0] == first_id          # id preserved
    assert rows[0][1] == "Updated headline"  # fields updated
    assert rows[0][2] == 2.5


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


def test_news_daily_summary_upserts_on_same_day(tmp_path: Path) -> None:
    """Two runs on the same report_date for the same ticker should collapse to
    one row in news_daily_summary (last write wins), not produce duplicates."""
    db_path = tmp_path / "stock.sqlite3"

    same_day = date(2026, 5, 29)
    report_a = DailyReport(
        report_date=same_day,
        generated_at=datetime(2026, 5, 29, 8, 0, tzinfo=timezone.utc),
        ticker_reports=[
            TickerReport(
                ticker=TickerConfig(symbol="NVDA", company_name="NVIDIA Corporation"),
                articles=[_make_article("NVDA", url="https://reuters.com/n1")],
                x_signals=[], valuation=None, earnings=None,
            )
        ],
    )
    report_b = DailyReport(
        report_date=same_day,
        generated_at=datetime(2026, 5, 29, 14, 0, tzinfo=timezone.utc),
        ticker_reports=[
            TickerReport(
                ticker=TickerConfig(symbol="NVDA", company_name="NVIDIA Corporation"),
                articles=[
                    _make_article("NVDA", url="https://reuters.com/n1"),
                    _make_article("NVDA", url="https://reuters.com/n2"),
                ],
                x_signals=[], valuation=None, earnings=None,
            )
        ],
    )

    with init_db(db_path) as conn:
        save_report_run(conn, report_a, html_path=str(tmp_path / "a.html"))
        save_report_run(conn, report_b, html_path=str(tmp_path / "b.html"))

        rows = conn.execute(
            "SELECT report_date, ticker, news_count, generated_at "
            "FROM news_daily_summary WHERE ticker = 'NVDA' ORDER BY generated_at"
        ).fetchall()

    assert len(rows) == 1, f"Expected single row after upsert, got {len(rows)}: {rows}"
    assert rows[0][2] == 2  # later run's news_count wins
    assert rows[0][3].startswith("2026-05-29T14")  # later generated_at


def test_news_daily_summary_dedup_migration(tmp_path: Path) -> None:
    """Pre-existing duplicate rows from before the UNIQUE index should be
    collapsed during init_db migration, keeping the latest generated_at."""
    db_path = tmp_path / "stock.sqlite3"
    # Open once to create base schema
    with init_db(db_path) as conn:
        pass

    # Drop the new unique index so we can insert duplicates simulating legacy state
    with sqlite3.connect(db_path) as raw:
        raw.execute("DROP INDEX IF EXISTS idx_summary_date_ticker_unique")
        for run_id, gen_at, count in [
            (1, "2026-05-29T08:00:00+00:00", 1),
            (2, "2026-05-29T12:00:00+00:00", 3),  # newer — should win
            (3, "2026-05-29T10:00:00+00:00", 2),
        ]:
            raw.execute(
                "INSERT INTO report_runs (report_date, generated_at, html_path, warning_count, created_at) "
                "VALUES (?, ?, '', 0, ?)",
                ("2026-05-29", gen_at, gen_at),
            )
            raw.execute(
                "INSERT INTO news_daily_summary "
                "(report_run_id, report_date, generated_at, ticker, news_count) "
                "VALUES (?, ?, ?, 'NVDA', ?)",
                (run_id, "2026-05-29", gen_at, count),
            )
        raw.commit()
        # Confirm the duplicates landed
        assert raw.execute(
            "SELECT COUNT(*) FROM news_daily_summary WHERE ticker='NVDA'"
        ).fetchone()[0] == 3

    # init_db should dedup
    with init_db(db_path) as conn:
        rows = conn.execute(
            "SELECT generated_at, news_count FROM news_daily_summary WHERE ticker='NVDA'"
        ).fetchall()

    assert len(rows) == 1
    assert rows[0][0].startswith("2026-05-29T12")
    assert rows[0][1] == 3


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


def test_research_state_plan_fields_roundtrip(tmp_path: Path) -> None:
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
                bull_case="AI capex still rising into 2026",
                bear_case="Margin compression if Blackwell yield slips",
                entry_plan="Add on 20MA pullback, only if RSI < 65",
                add_zone="20MA retest, >= 1.5x avg volume",
                reduce_zone="RSI > 80 with volume divergence",
                stop_loss="Daily close below 50MA",
            )
        },
    )

    with init_db(db_path) as conn:
        save_report(conn, report)
        loaded = load_ticker_research_states(conn, ["NVDA"])["NVDA"]
        payload = export_research_state_payload(conn)

    assert loaded.bull_case == "AI capex still rising into 2026"
    assert loaded.stop_loss == "Daily close below 50MA"
    assert payload["tickers"]["NVDA"]["entry_plan"] == "Add on 20MA pullback, only if RSI < 65"

    with init_db(tmp_path / "import.sqlite3") as conn:
        import_research_state_payload(conn, payload)
        reimported = load_ticker_research_states(conn, ["NVDA"])["NVDA"]

    assert reimported.bear_case == "Margin compression if Blackwell yield slips"
    assert reimported.add_zone == "20MA retest, >= 1.5x avg volume"
    assert reimported.reduce_zone == "RSI > 80 with volume divergence"


def test_research_state_position_roundtrip(tmp_path: Path) -> None:
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
                position=PositionConfig(
                    status="holding",
                    shares=12.5,
                    avg_cost=100.0,
                    portfolio_weight=6.25,
                    position_size=1400.0,
                    stop_loss=92.0,
                ),
            )
        },
    )

    with init_db(db_path) as conn:
        save_report(conn, report)
        loaded = load_ticker_research_states(conn, ["NVDA"])["NVDA"]
        payload = export_research_state_payload(conn)

    assert loaded.position is not None
    assert loaded.position.status == "holding"
    assert loaded.position.shares == 12.5
    assert payload["tickers"]["NVDA"]["position"]["portfolio_weight"] == 6.25

    with init_db(tmp_path / "import.sqlite3") as conn:
        import_research_state_payload(conn, payload)
        reimported = load_ticker_research_states(conn, ["NVDA"])["NVDA"]

    assert reimported.position is not None
    assert reimported.position.avg_cost == 100.0
    assert reimported.position.stop_loss == 92.0


def test_earnings_card_fields_roundtrip(tmp_path: Path) -> None:
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
                earnings_questions=["Data center growth?", "Margin trajectory?", "China exposure?"],
            )
        },
        post_earnings_reviews={
            "NVDA": PostEarningsReview(
                ticker="NVDA",
                earnings_date=date(2026, 4, 27),
                eps="beat",
                gross_margin_change="Up 120bps QoQ",
                management_keywords="demand, backlog, pricing",
                thesis_changed="no",
            )
        },
    )

    with init_db(db_path) as conn:
        save_report(conn, report)
        state = load_ticker_research_states(conn, ["NVDA"])["NVDA"]
        review = load_post_earnings_reviews(conn, ["NVDA"])["NVDA"]
        payload = export_research_state_payload(conn)

    assert state.earnings_questions == ["Data center growth?", "Margin trajectory?", "China exposure?"]
    assert review.gross_margin_change == "Up 120bps QoQ"
    assert review.management_keywords == "demand, backlog, pricing"
    assert review.thesis_changed == "no"

    with init_db(tmp_path / "import.sqlite3") as conn:
        import_research_state_payload(conn, payload)
        reimported_state = load_ticker_research_states(conn, ["NVDA"])["NVDA"]
        reimported_review = load_post_earnings_reviews(conn, ["NVDA"])["NVDA"]

    assert reimported_state.earnings_questions == ["Data center growth?", "Margin trajectory?", "China exposure?"]
    assert reimported_review.gross_margin_change == "Up 120bps QoQ"
    assert reimported_review.thesis_changed == "no"


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
        save_report_run(
            conn,
            new_report,
            right_side_signals={
                "NVDA": {
                    "status": "Right-side ready",
                    "tone": "up",
                    "ready_count": 4,
                    "check_count": 4,
                }
            },
        )
        history = load_ticker_history(conn, ["NVDA"], report_date=date(2026, 4, 28), history_days=30)["NVDA"]

    assert len(history) == 2
    assert history[0].report_date == date(2026, 4, 28)
    assert history[0].thesis_state == "active"
    assert history[0].top_news_count == 1
    assert history[0].valuation_risk == "High"
    assert history[0].daily_change_pct == 10.0
    assert history[0].earnings_days == 23
    assert history[0].last_close == 110.0
    assert history[0].right_side_status == "Right-side ready"
    assert history[0].right_side_ready_count == 4
    assert history[0].right_side_check_count == 4
    assert history[1].thesis_state == "building"


def _insert_valuation_row(conn, ticker: str, retrieved_at: datetime, last_close: float | None = 150.0) -> None:
    as_of = retrieved_at.date().isoformat()
    ts = retrieved_at.isoformat()
    rows = [
        (ticker, as_of, "yfinance", ts, "last_close", last_close),
        (ticker, as_of, "yfinance", ts, "market_cap", 1_000_000.0),
    ]
    conn.executemany(
        "INSERT OR IGNORE INTO valuation_snapshots (ticker, as_of_date, source, retrieved_at, metric_name, metric_value) VALUES (?,?,?,?,?,?)",
        rows,
    )
    conn.commit()


def test_load_fresh_valuation_snapshot_returns_fresh(tmp_path) -> None:
    db_path = tmp_path / "test.sqlite3"
    now = datetime.now(timezone.utc)
    fresh_at = now.replace(microsecond=0) - timedelta(hours=1)
    with init_db(db_path) as conn:
        _insert_valuation_row(conn, "NVDA", fresh_at)
        result = load_fresh_valuation_snapshot(conn, "NVDA", max_age_hours=4)
    assert result is not None
    assert result.ticker == "NVDA"
    assert result.metrics["last_close"] == 150.0


def test_load_fresh_valuation_snapshot_returns_none_for_stale(tmp_path) -> None:
    db_path = tmp_path / "test.sqlite3"
    now = datetime.now(timezone.utc)
    stale_at = now.replace(microsecond=0) - timedelta(hours=5)
    with init_db(db_path) as conn:
        _insert_valuation_row(conn, "NVDA", stale_at)
        result = load_fresh_valuation_snapshot(conn, "NVDA", max_age_hours=4)
    assert result is None


def test_load_fresh_valuation_snapshot_returns_none_when_empty(tmp_path) -> None:
    db_path = tmp_path / "test.sqlite3"
    with init_db(db_path) as conn:
        result = load_fresh_valuation_snapshot(conn, "NVDA", max_age_hours=4)
    assert result is None


def test_load_fresh_valuation_snapshot_skips_all_null_metrics(tmp_path) -> None:
    db_path = tmp_path / "test.sqlite3"
    now = datetime.now(timezone.utc).replace(microsecond=0)
    ts = now.isoformat()
    as_of = now.date().isoformat()
    with init_db(db_path) as conn:
        conn.execute(
            "INSERT INTO valuation_snapshots (ticker, as_of_date, source, retrieved_at, metric_name, metric_value) VALUES (?,?,?,?,?,?)",
            ("NVDA", as_of, "yfinance", ts, "market_cap", None),
        )
        conn.commit()
        result = load_fresh_valuation_snapshot(conn, "NVDA", max_age_hours=4)
    assert result is None


def _earnings_on(ticker: str, when: date) -> EarningsDate:
    return EarningsDate(
        ticker=ticker, company_name=f"{ticker} Inc", earnings_date=when, time_of_day="unknown",
        fiscal_quarter=None, fiscal_year=None, eps_estimate=None, revenue_estimate=None,
        source="yfinance", source_retrieved_at=datetime.now(timezone.utc),
    )


def test_load_next_earnings_date_prefers_upcoming(tmp_path: Path) -> None:
    db_path = tmp_path / "stock.sqlite3"
    with init_db(db_path) as conn:
        save_report(conn, _wrap("AVGO", earnings=_earnings_on("AVGO", date(2026, 6, 4))))
        save_report(conn, _wrap("AVGO", earnings=_earnings_on("AVGO", date(2026, 9, 4))))
        result = load_next_earnings_date(conn, "AVGO", on_or_after=date(2026, 6, 8))
    assert result is not None
    assert result.earnings_date == date(2026, 9, 4)


def test_load_next_earnings_date_falls_back_to_past(tmp_path: Path) -> None:
    db_path = tmp_path / "stock.sqlite3"
    with init_db(db_path) as conn:
        save_report(conn, _wrap("AVGO", earnings=_earnings_on("AVGO", date(2026, 6, 4))))
        result = load_next_earnings_date(conn, "AVGO", on_or_after=date(2026, 6, 8))
    assert result is not None
    assert result.earnings_date == date(2026, 6, 4)


def test_load_next_earnings_date_none_when_empty(tmp_path: Path) -> None:
    db_path = tmp_path / "stock.sqlite3"
    with init_db(db_path) as conn:
        result = load_next_earnings_date(conn, "AVGO", on_or_after=date(2026, 6, 8))
    assert result is None


def test_load_fresh_valuation_snapshot_requires_last_close(tmp_path) -> None:
    db_path = tmp_path / "test.sqlite3"
    now = datetime.now(timezone.utc).replace(microsecond=0)
    ts = now.isoformat()
    as_of = now.date().isoformat()
    with init_db(db_path) as conn:
        conn.execute(
            "INSERT INTO valuation_snapshots (ticker, as_of_date, source, retrieved_at, metric_name, metric_value) VALUES (?,?,?,?,?,?)",
            ("NVDA", as_of, "yfinance", ts, "market_cap", 1_000_000.0),
        )
        conn.commit()
        result = load_fresh_valuation_snapshot(conn, "NVDA", max_age_hours=4)
    assert result is None
