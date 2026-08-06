from __future__ import annotations

import json
import math
import sqlite3
from contextlib import closing
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .models import (
    DailyReport,
    EarningsDate,
    NewsArticle,
    PostEarningsReview,
    PositionConfig,
    TaiwanFuturesPosition,
    TaiwanInstitutionalMarketSnapshot,
    TaiwanMarketOverview,
    TickerHistoryPoint,
    TickerResearchState,
    TradeFill,
    TradeJournalEntry,
    ValuationSnapshot,
    XSignal,
)


SCHEMA = """
CREATE TABLE IF NOT EXISTS news_articles (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ticker TEXT NOT NULL,
  title TEXT NOT NULL,
  source TEXT NOT NULL,
  domain TEXT NOT NULL,
  published_at TEXT,
  url TEXT NOT NULL,
  summary TEXT NOT NULL,
  event_type TEXT NOT NULL,
  importance_score REAL NOT NULL,
  UNIQUE(ticker, url)
);

CREATE TABLE IF NOT EXISTS x_signals (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ticker TEXT NOT NULL,
  author_handle TEXT NOT NULL,
  author_category TEXT NOT NULL,
  text TEXT NOT NULL,
  created_at TEXT,
  url TEXT NOT NULL UNIQUE,
  like_count INTEGER NOT NULL,
  repost_count INTEGER NOT NULL,
  reply_count INTEGER NOT NULL,
  quote_count INTEGER NOT NULL,
  credibility_score REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS valuation_snapshots (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ticker TEXT NOT NULL,
  as_of_date TEXT NOT NULL,
  source TEXT NOT NULL,
  metric_name TEXT NOT NULL,
  metric_value TEXT,
  retrieved_at TEXT NOT NULL,
  UNIQUE(ticker, as_of_date, source, metric_name)
);

CREATE TABLE IF NOT EXISTS taiwan_market_overviews (
  as_of_date TEXT PRIMARY KEY,
  margin_maintenance_ratio_estimate REAL NOT NULL,
  collateral_value_thousand_twd REAL NOT NULL,
  financing_balance_thousand_twd REAL NOT NULL,
  previous_financing_balance_thousand_twd REAL,
  priced_margin_units REAL NOT NULL,
  total_margin_units REAL NOT NULL,
  price_coverage_pct REAL NOT NULL,
  priced_security_count INTEGER NOT NULL,
  margin_security_count INTEGER NOT NULL,
  source TEXT NOT NULL,
  retrieved_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS taiwan_institutional_market_snapshots (
  as_of_date TEXT NOT NULL,
  market TEXT NOT NULL,
  foreign_net_twd REAL NOT NULL,
  investment_trust_net_twd REAL NOT NULL,
  dealer_net_twd REAL NOT NULL,
  total_net_twd REAL NOT NULL,
  source TEXT NOT NULL,
  retrieved_at TEXT NOT NULL,
  PRIMARY KEY (as_of_date, market)
);

CREATE TABLE IF NOT EXISTS taiwan_futures_positions (
  as_of_date TEXT NOT NULL,
  contract_code TEXT NOT NULL,
  institution TEXT NOT NULL,
  trading_long INTEGER NOT NULL,
  trading_short INTEGER NOT NULL,
  trading_net INTEGER NOT NULL,
  open_interest_long INTEGER NOT NULL,
  open_interest_short INTEGER NOT NULL,
  open_interest_net INTEGER NOT NULL,
  source TEXT NOT NULL,
  retrieved_at TEXT NOT NULL,
  PRIMARY KEY (as_of_date, contract_code, institution)
);

CREATE INDEX IF NOT EXISTS idx_taiwan_institutional_market_date
  ON taiwan_institutional_market_snapshots(as_of_date, market);
CREATE INDEX IF NOT EXISTS idx_taiwan_futures_position_date
  ON taiwan_futures_positions(as_of_date, contract_code, institution);

CREATE TABLE IF NOT EXISTS earnings_dates (
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
  source_retrieved_at TEXT NOT NULL,
  UNIQUE(ticker, earnings_date, source)
);

CREATE TABLE IF NOT EXISTS report_runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  report_date TEXT NOT NULL,
  generated_at TEXT NOT NULL,
  html_path TEXT NOT NULL DEFAULT '',
  warning_count INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ticker_research_state (
  ticker TEXT PRIMARY KEY,
  tag TEXT NOT NULL DEFAULT '',
  thesis_state TEXT NOT NULL DEFAULT '',
  thesis_trigger TEXT NOT NULL DEFAULT '',
  thesis_text TEXT NOT NULL DEFAULT '',
  note TEXT NOT NULL DEFAULT '',
  checklist_json TEXT NOT NULL DEFAULT '[]',
  revisit_date TEXT,
  pinned INTEGER NOT NULL DEFAULT 0,
  review_status TEXT NOT NULL DEFAULT 'not-reviewed',
  last_reviewed_at TEXT,
  updated_at TEXT NOT NULL,
  bull_case TEXT NOT NULL DEFAULT '',
  bear_case TEXT NOT NULL DEFAULT '',
  entry_plan TEXT NOT NULL DEFAULT '',
  add_zone TEXT NOT NULL DEFAULT '',
  reduce_zone TEXT NOT NULL DEFAULT '',
  stop_loss TEXT NOT NULL DEFAULT '',
  earnings_questions_json TEXT NOT NULL DEFAULT '[]',
  position_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS ticker_notes_history (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ticker TEXT NOT NULL,
  note TEXT NOT NULL DEFAULT '',
  thesis_state TEXT NOT NULL DEFAULT '',
  thesis_trigger TEXT NOT NULL DEFAULT '',
  review_status TEXT NOT NULL DEFAULT 'not-reviewed',
  changed_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS post_earnings_reviews (
  ticker TEXT PRIMARY KEY,
  earnings_date TEXT,
  eps TEXT NOT NULL DEFAULT '',
  revenue TEXT NOT NULL DEFAULT '',
  guide TEXT NOT NULL DEFAULT '',
  eps_surprise_pct REAL,
  revenue_surprise_pct REAL,
  fy1_eps_revision_after REAL,
  fy1_revenue_revision_after REAL,
  conclusion TEXT NOT NULL DEFAULT '',
  next_step TEXT NOT NULL DEFAULT '',
  gross_margin_change TEXT NOT NULL DEFAULT '',
  management_keywords TEXT NOT NULL DEFAULT '',
  thesis_changed TEXT NOT NULL DEFAULT '',
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS trade_journal (
  trade_id TEXT PRIMARY KEY,
  ticker TEXT NOT NULL,
  market TEXT NOT NULL DEFAULT 'us',
  currency TEXT NOT NULL DEFAULT 'USD',
  status TEXT NOT NULL DEFAULT 'open',
  entry_date TEXT,
  entry_price REAL,
  shares REAL,
  initial_stop REAL,
  current_stop REAL,
  initial_risk REAL,
  exit_date TEXT,
  exit_price REAL,
  fees REAL NOT NULL DEFAULT 0,
  fx_rate_to_base REAL NOT NULL DEFAULT 1,
  fills_json TEXT NOT NULL DEFAULT '[]',
  setup TEXT NOT NULL DEFAULT '',
  note TEXT NOT NULL DEFAULT '',
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS news_daily_summary (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  report_run_id INTEGER NOT NULL,
  report_date TEXT NOT NULL,
  generated_at TEXT NOT NULL,
  ticker TEXT NOT NULL,
  thesis_state TEXT NOT NULL DEFAULT '',
  review_status TEXT NOT NULL DEFAULT 'not-reviewed',
  last_reviewed_at TEXT,
  news_count INTEGER NOT NULL DEFAULT 0,
  top_news_count INTEGER NOT NULL DEFAULT 0,
  valuation_risk TEXT NOT NULL DEFAULT 'None',
  rsi REAL,
  daily_change_pct REAL,
  premarket_change_pct REAL,
  earnings_days INTEGER,
  warning_count INTEGER NOT NULL DEFAULT 0,
  attention_score REAL NOT NULL DEFAULT 0,
  news_burst_score REAL NOT NULL DEFAULT 0,
  last_close REAL,
  right_side_status TEXT NOT NULL DEFAULT '',
  right_side_tone TEXT NOT NULL DEFAULT '',
  right_side_ready_count INTEGER NOT NULL DEFAULT 0,
  right_side_check_count INTEGER NOT NULL DEFAULT 0,
  score_data_date TEXT,
  health_score REAL,
  health_trend_score REAL,
  health_momentum_score REAL,
  health_volume_score REAL,
  health_fundamental_score REAL,
  health_risk_score REAL,
  health_status TEXT NOT NULL DEFAULT '',
  health_coverage INTEGER NOT NULL DEFAULT 0,
  health_rule_version TEXT NOT NULL DEFAULT '',
  right_side_score REAL,
  right_side_rule_version TEXT NOT NULL DEFAULT '',
  signal_entry REAL,
  signal_stop REAL,
  signal_risk_pct REAL,
  UNIQUE(report_run_id, ticker)
);

CREATE INDEX IF NOT EXISTS idx_news_articles_ticker ON news_articles(ticker);
CREATE INDEX IF NOT EXISTS idx_news_articles_published_at ON news_articles(published_at);
CREATE INDEX IF NOT EXISTS idx_x_signals_ticker ON x_signals(ticker);
CREATE INDEX IF NOT EXISTS idx_valuation_ticker_date ON valuation_snapshots(ticker, as_of_date);
CREATE INDEX IF NOT EXISTS idx_earnings_ticker ON earnings_dates(ticker);
CREATE UNIQUE INDEX IF NOT EXISTS idx_earnings_ticker_date_source_expr
  ON earnings_dates(ticker, IFNULL(earnings_date, ''), source);
CREATE INDEX IF NOT EXISTS idx_report_runs_report_date ON report_runs(report_date, generated_at);
CREATE INDEX IF NOT EXISTS idx_notes_history_ticker ON ticker_notes_history(ticker, changed_at);
CREATE INDEX IF NOT EXISTS idx_trade_journal_ticker_date ON trade_journal(ticker, entry_date);
CREATE INDEX IF NOT EXISTS idx_summary_ticker_date ON news_daily_summary(ticker, report_date, generated_at);
CREATE UNIQUE INDEX IF NOT EXISTS idx_summary_date_ticker_unique ON news_daily_summary(report_date, ticker);
"""


def init_db(path: str | Path) -> sqlite3.Connection:
    db_path = Path(path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    _migrate_schema(conn)
    conn.executescript(SCHEMA)
    conn.commit()
    return conn


def _migrate_schema(conn: sqlite3.Connection) -> None:
    """Migrate legacy schemas that lack the current UNIQUE constraints."""
    with closing(conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='news_articles'"
    )) as cursor:
        row = cursor.fetchone()
    if row and "url TEXT NOT NULL UNIQUE" in row[0]:
        conn.executescript(
            """
            CREATE TABLE news_articles_new (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              ticker TEXT NOT NULL,
              title TEXT NOT NULL,
              source TEXT NOT NULL,
              domain TEXT NOT NULL,
              published_at TEXT,
              url TEXT NOT NULL,
              summary TEXT NOT NULL,
              event_type TEXT NOT NULL,
              importance_score REAL NOT NULL,
              UNIQUE(ticker, url)
            );
            INSERT INTO news_articles_new
              (id, ticker, title, source, domain, published_at, url, summary, event_type, importance_score)
            SELECT id, ticker, title, source, domain, published_at, url, summary, event_type, importance_score
            FROM news_articles;
            DROP TABLE news_articles;
            ALTER TABLE news_articles_new RENAME TO news_articles;
            """
        )

    with closing(conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='earnings_dates'"
    )) as cursor:
        row = cursor.fetchone()
    if row and "UNIQUE(ticker, earnings_date, source)" not in row[0]:
        conn.executescript(
            """
            CREATE TABLE earnings_dates_new (
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
              source_retrieved_at TEXT NOT NULL,
              UNIQUE(ticker, earnings_date, source)
            );
            INSERT OR IGNORE INTO earnings_dates_new
              (ticker, company_name, earnings_date, time_of_day, fiscal_quarter, fiscal_year,
               eps_estimate, revenue_estimate, source, source_retrieved_at)
            SELECT ticker, company_name, earnings_date, time_of_day, fiscal_quarter, fiscal_year,
                   eps_estimate, revenue_estimate, source, source_retrieved_at
            FROM earnings_dates;
            DROP TABLE earnings_dates;
            ALTER TABLE earnings_dates_new RENAME TO earnings_dates;
            """
        )

    _ensure_column(conn, "ticker_research_state", "note", "TEXT NOT NULL DEFAULT ''")
    for plan_column in ("bull_case", "bear_case", "entry_plan", "add_zone", "reduce_zone", "stop_loss"):
        _ensure_column(conn, "ticker_research_state", plan_column, "TEXT NOT NULL DEFAULT ''")
    _ensure_column(conn, "ticker_research_state", "earnings_questions_json", "TEXT NOT NULL DEFAULT '[]'")
    _ensure_column(conn, "ticker_research_state", "thesis_text", "TEXT NOT NULL DEFAULT ''")
    _ensure_column(conn, "ticker_research_state", "position_json", "TEXT NOT NULL DEFAULT '{}'")
    for pe_column in ("gross_margin_change", "management_keywords", "thesis_changed"):
        _ensure_column(conn, "post_earnings_reviews", pe_column, "TEXT NOT NULL DEFAULT ''")
    _ensure_column(conn, "trade_journal", "current_stop", "REAL")
    _ensure_column(conn, "trade_journal", "initial_risk", "REAL")
    _ensure_column(conn, "trade_journal", "fx_rate_to_base", "REAL NOT NULL DEFAULT 1")
    _ensure_column(conn, "trade_journal", "fills_json", "TEXT NOT NULL DEFAULT '[]'")
    _ensure_column(conn, "news_daily_summary", "generated_at", "TEXT NOT NULL DEFAULT ''")
    _ensure_column(conn, "news_daily_summary", "last_close", "REAL")
    _ensure_column(conn, "news_daily_summary", "right_side_status", "TEXT NOT NULL DEFAULT ''")
    _ensure_column(conn, "news_daily_summary", "right_side_tone", "TEXT NOT NULL DEFAULT ''")
    _ensure_column(conn, "news_daily_summary", "right_side_ready_count", "INTEGER NOT NULL DEFAULT 0")
    _ensure_column(conn, "news_daily_summary", "right_side_check_count", "INTEGER NOT NULL DEFAULT 0")
    _ensure_column(conn, "news_daily_summary", "score_data_date", "TEXT")
    _ensure_column(conn, "news_daily_summary", "health_score", "REAL")
    _ensure_column(conn, "news_daily_summary", "health_trend_score", "REAL")
    _ensure_column(conn, "news_daily_summary", "health_momentum_score", "REAL")
    _ensure_column(conn, "news_daily_summary", "health_volume_score", "REAL")
    _ensure_column(conn, "news_daily_summary", "health_fundamental_score", "REAL")
    _ensure_column(conn, "news_daily_summary", "health_risk_score", "REAL")
    _ensure_column(conn, "news_daily_summary", "health_status", "TEXT NOT NULL DEFAULT ''")
    _ensure_column(conn, "news_daily_summary", "health_coverage", "INTEGER NOT NULL DEFAULT 0")
    _ensure_column(conn, "news_daily_summary", "health_rule_version", "TEXT NOT NULL DEFAULT ''")
    _ensure_column(conn, "news_daily_summary", "right_side_score", "REAL")
    _ensure_column(conn, "news_daily_summary", "right_side_rule_version", "TEXT NOT NULL DEFAULT ''")
    _ensure_column(conn, "news_daily_summary", "signal_entry", "REAL")
    _ensure_column(conn, "news_daily_summary", "signal_stop", "REAL")
    _ensure_column(conn, "news_daily_summary", "signal_risk_pct", "REAL")
    _cleanup_earnings_duplicates(conn)
    _dedupe_news_daily_summary(conn)
    conn.commit()


def _dedupe_news_daily_summary(conn: sqlite3.Connection) -> None:
    """Collapse multiple (report_date, ticker) rows down to the latest snapshot.

    Multiple runs of the pipeline on the same day used to create one
    `news_daily_summary` row per `report_run_id`, polluting the Research timeline
    on each ticker card. Keep only the row with the latest `generated_at` per
    `(report_date, ticker)`, then add a UNIQUE index so future writes upsert.
    """
    has_table = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='news_daily_summary'"
    ).fetchone()
    if not has_table:
        return
    conn.execute(
        """
        DELETE FROM news_daily_summary
        WHERE id NOT IN (
          SELECT id FROM (
            SELECT id,
                   ROW_NUMBER() OVER (
                     PARTITION BY report_date, ticker
                     ORDER BY generated_at DESC, id DESC
                   ) AS rn
            FROM news_daily_summary
          )
          WHERE rn = 1
        )
        """
    )
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_summary_date_ticker_unique "
        "ON news_daily_summary(report_date, ticker)"
    )


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    exists = conn.execute(
        f"SELECT 1 FROM pragma_table_info('{table}') WHERE name = ?",
        (column,),
    ).fetchone()
    if exists:
        return
    table_exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name = ?",
        (table,),
    ).fetchone()
    if not table_exists:
        return
    conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def _cleanup_earnings_duplicates(conn: sqlite3.Connection) -> None:
    table_exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name = 'earnings_dates'"
    ).fetchone()
    if not table_exists:
        return
    conn.execute(
        """
        DELETE FROM earnings_dates
        WHERE rowid NOT IN (
          SELECT MIN(rowid)
          FROM earnings_dates
          GROUP BY ticker, IFNULL(earnings_date, ''), source
        )
        """
    )


def save_report(conn: sqlite3.Connection, report: DailyReport) -> None:
    for ticker_report in report.ticker_reports:
        for article in ticker_report.articles:
            save_article(conn, article)
        for signal in ticker_report.x_signals:
            save_x_signal(conn, signal)
        if ticker_report.valuation:
            save_valuation(conn, ticker_report.valuation)
        if ticker_report.earnings:
            save_earnings(conn, ticker_report.earnings)
    if report.taiwan_market_overview:
        save_taiwan_market_overview(conn, report.taiwan_market_overview)
    for snapshot in report.taiwan_institutional_market:
        save_taiwan_institutional_market_snapshot(conn, snapshot)
    for position in report.taiwan_futures_positions:
        save_taiwan_futures_position(conn, position)
    for state in report.research_states.values():
        upsert_ticker_research_state(conn, state)
    for review in report.post_earnings_reviews.values():
        upsert_post_earnings_review(conn, review)
    for trade in report.trade_journal:
        upsert_trade_journal_entry(conn, trade)
    # No commit here: this stays in the caller's transaction so it commits
    # atomically with save_report_run, avoiding a half-saved run if the process
    # dies between the two. (`with init_db(...) as conn` blocks still commit on
    # exit for standalone callers.)


def save_article(conn: sqlite3.Connection, article: NewsArticle) -> None:
    conn.execute(
        """
        INSERT INTO news_articles
        (ticker, title, source, domain, published_at, url, summary, event_type, importance_score)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(ticker, url) DO UPDATE SET
          title = excluded.title,
          source = excluded.source,
          domain = excluded.domain,
          published_at = excluded.published_at,
          summary = excluded.summary,
          event_type = excluded.event_type,
          importance_score = excluded.importance_score
        """,
        (
            article.ticker,
            article.title,
            article.source,
            article.domain,
            article.published_at.isoformat() if article.published_at else None,
            article.url,
            article.summary,
            article.event_type,
            article.importance_score,
        ),
    )


def save_x_signal(conn: sqlite3.Connection, signal: XSignal) -> None:
    if not signal.url:
        return
    conn.execute(
        """
        INSERT OR IGNORE INTO x_signals
        (ticker, author_handle, author_category, text, created_at, url, like_count, repost_count, reply_count, quote_count, credibility_score)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            signal.ticker,
            signal.author_handle,
            signal.author_category,
            signal.text,
            signal.created_at.isoformat() if signal.created_at else None,
            signal.url,
            signal.like_count,
            signal.repost_count,
            signal.reply_count,
            signal.quote_count,
            signal.credibility_score,
        ),
    )


def save_valuation(conn: sqlite3.Connection, valuation: ValuationSnapshot) -> None:
    for metric_name, metric_value in valuation.metrics.items():
        conn.execute(
            """
            INSERT OR REPLACE INTO valuation_snapshots
            (ticker, as_of_date, source, metric_name, metric_value, retrieved_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                valuation.ticker,
                valuation.as_of_date.isoformat(),
                valuation.source,
                metric_name,
                _serialize_metric_value(metric_value),
                valuation.retrieved_at.isoformat(),
            ),
        )


def save_taiwan_market_overview(
    conn: sqlite3.Connection,
    overview: TaiwanMarketOverview,
) -> None:
    conn.execute(
        """
        INSERT INTO taiwan_market_overviews
        (as_of_date, margin_maintenance_ratio_estimate,
         collateral_value_thousand_twd, financing_balance_thousand_twd,
         previous_financing_balance_thousand_twd, priced_margin_units,
         total_margin_units, price_coverage_pct, priced_security_count,
         margin_security_count, source, retrieved_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(as_of_date) DO UPDATE SET
          margin_maintenance_ratio_estimate = excluded.margin_maintenance_ratio_estimate,
          collateral_value_thousand_twd = excluded.collateral_value_thousand_twd,
          financing_balance_thousand_twd = excluded.financing_balance_thousand_twd,
          previous_financing_balance_thousand_twd = excluded.previous_financing_balance_thousand_twd,
          priced_margin_units = excluded.priced_margin_units,
          total_margin_units = excluded.total_margin_units,
          price_coverage_pct = excluded.price_coverage_pct,
          priced_security_count = excluded.priced_security_count,
          margin_security_count = excluded.margin_security_count,
          source = excluded.source,
          retrieved_at = excluded.retrieved_at
        """,
        (
            overview.as_of_date.isoformat(),
            overview.margin_maintenance_ratio_estimate,
            overview.collateral_value_thousand_twd,
            overview.financing_balance_thousand_twd,
            overview.previous_financing_balance_thousand_twd,
            overview.priced_margin_units,
            overview.total_margin_units,
            overview.price_coverage_pct,
            overview.priced_security_count,
            overview.margin_security_count,
            overview.source,
            overview.retrieved_at.isoformat(),
        ),
    )


def load_fresh_taiwan_market_overview(
    conn: sqlite3.Connection,
    *,
    before_or_on: date,
    max_age_hours: int = 4,
) -> TaiwanMarketOverview | None:
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=max_age_hours)).isoformat()
    return _load_taiwan_market_overview(conn, before_or_on=before_or_on, cutoff=cutoff)


def load_latest_taiwan_market_overview(
    conn: sqlite3.Connection,
    *,
    before_or_on: date,
) -> TaiwanMarketOverview | None:
    return _load_taiwan_market_overview(conn, before_or_on=before_or_on)


def _load_taiwan_market_overview(
    conn: sqlite3.Connection,
    *,
    before_or_on: date,
    cutoff: str | None = None,
) -> TaiwanMarketOverview | None:
    sql = """
        SELECT as_of_date, margin_maintenance_ratio_estimate,
               collateral_value_thousand_twd, financing_balance_thousand_twd,
               previous_financing_balance_thousand_twd, priced_margin_units,
               total_margin_units, price_coverage_pct, priced_security_count,
               margin_security_count, source, retrieved_at
        FROM taiwan_market_overviews
        WHERE as_of_date <= ?
    """
    params: list[object] = [before_or_on.isoformat()]
    if cutoff is not None:
        sql += " AND retrieved_at >= ?"
        params.append(cutoff)
    sql += " ORDER BY as_of_date DESC, retrieved_at DESC LIMIT 1"
    row = conn.execute(sql, params).fetchone()
    if row is None:
        return None
    return TaiwanMarketOverview(
        as_of_date=date.fromisoformat(row[0]),
        margin_maintenance_ratio_estimate=float(row[1]),
        collateral_value_thousand_twd=float(row[2]),
        financing_balance_thousand_twd=float(row[3]),
        previous_financing_balance_thousand_twd=(float(row[4]) if row[4] is not None else None),
        priced_margin_units=float(row[5]),
        total_margin_units=float(row[6]),
        price_coverage_pct=float(row[7]),
        priced_security_count=int(row[8]),
        margin_security_count=int(row[9]),
        source=str(row[10]),
        retrieved_at=datetime.fromisoformat(row[11]),
    )


def save_taiwan_institutional_market_snapshot(
    conn: sqlite3.Connection,
    snapshot: TaiwanInstitutionalMarketSnapshot,
) -> None:
    conn.execute(
        """
        INSERT INTO taiwan_institutional_market_snapshots
        (as_of_date, market, foreign_net_twd, investment_trust_net_twd,
         dealer_net_twd, total_net_twd, source, retrieved_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(as_of_date, market) DO UPDATE SET
          foreign_net_twd = excluded.foreign_net_twd,
          investment_trust_net_twd = excluded.investment_trust_net_twd,
          dealer_net_twd = excluded.dealer_net_twd,
          total_net_twd = excluded.total_net_twd,
          source = excluded.source,
          retrieved_at = excluded.retrieved_at
        """,
        (
            snapshot.as_of_date.isoformat(),
            snapshot.market,
            snapshot.foreign_net_twd,
            snapshot.investment_trust_net_twd,
            snapshot.dealer_net_twd,
            snapshot.total_net_twd,
            snapshot.source,
            snapshot.retrieved_at.isoformat(),
        ),
    )


def load_fresh_taiwan_institutional_market(
    conn: sqlite3.Connection,
    *,
    before_or_on: date,
    max_age_hours: int = 4,
) -> list[TaiwanInstitutionalMarketSnapshot]:
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=max_age_hours)).isoformat()
    return _load_taiwan_institutional_market(
        conn,
        before_or_on=before_or_on,
        cutoff=cutoff,
    )


def load_latest_taiwan_institutional_market(
    conn: sqlite3.Connection,
    *,
    before_or_on: date,
) -> list[TaiwanInstitutionalMarketSnapshot]:
    return _load_taiwan_institutional_market(
        conn,
        before_or_on=before_or_on,
    )


def _load_taiwan_institutional_market(
    conn: sqlite3.Connection,
    *,
    before_or_on: date,
    cutoff: str | None = None,
) -> list[TaiwanInstitutionalMarketSnapshot]:
    sql = """
        SELECT as_of_date, market, foreign_net_twd,
               investment_trust_net_twd, dealer_net_twd, total_net_twd,
               source, retrieved_at
        FROM taiwan_institutional_market_snapshots
        WHERE as_of_date <= ?
    """
    params: list[object] = [before_or_on.isoformat()]
    if cutoff is not None:
        sql += " AND retrieved_at >= ?"
        params.append(cutoff)
    sql += " ORDER BY as_of_date DESC, retrieved_at DESC"

    output: list[TaiwanInstitutionalMarketSnapshot] = []
    seen_markets: set[str] = set()
    for row in conn.execute(sql, params).fetchall():
        market = str(row[1])
        if market in seen_markets:
            continue
        seen_markets.add(market)
        output.append(
            TaiwanInstitutionalMarketSnapshot(
                as_of_date=date.fromisoformat(row[0]),
                market=market,
                foreign_net_twd=float(row[2]),
                investment_trust_net_twd=float(row[3]),
                dealer_net_twd=float(row[4]),
                total_net_twd=float(row[5]),
                source=str(row[6]),
                retrieved_at=datetime.fromisoformat(row[7]),
            )
        )
    return output


def save_taiwan_futures_position(
    conn: sqlite3.Connection,
    position: TaiwanFuturesPosition,
) -> None:
    conn.execute(
        """
        INSERT INTO taiwan_futures_positions
        (as_of_date, contract_code, institution, trading_long, trading_short,
         trading_net, open_interest_long, open_interest_short,
         open_interest_net, source, retrieved_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(as_of_date, contract_code, institution) DO UPDATE SET
          trading_long = excluded.trading_long,
          trading_short = excluded.trading_short,
          trading_net = excluded.trading_net,
          open_interest_long = excluded.open_interest_long,
          open_interest_short = excluded.open_interest_short,
          open_interest_net = excluded.open_interest_net,
          source = excluded.source,
          retrieved_at = excluded.retrieved_at
        """,
        (
            position.as_of_date.isoformat(),
            position.contract_code,
            position.institution,
            position.trading_long,
            position.trading_short,
            position.trading_net,
            position.open_interest_long,
            position.open_interest_short,
            position.open_interest_net,
            position.source,
            position.retrieved_at.isoformat(),
        ),
    )


def load_fresh_taiwan_futures_positions(
    conn: sqlite3.Connection,
    *,
    before_or_on: date,
    max_age_hours: int = 4,
    session_limit: int = 5,
) -> list[TaiwanFuturesPosition]:
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=max_age_hours)).isoformat()
    return _load_taiwan_futures_positions(
        conn,
        before_or_on=before_or_on,
        cutoff=cutoff,
        session_limit=session_limit,
    )


def load_latest_taiwan_futures_positions(
    conn: sqlite3.Connection,
    *,
    before_or_on: date,
    session_limit: int = 5,
) -> list[TaiwanFuturesPosition]:
    return _load_taiwan_futures_positions(
        conn,
        before_or_on=before_or_on,
        session_limit=session_limit,
    )


def _load_taiwan_futures_positions(
    conn: sqlite3.Connection,
    *,
    before_or_on: date,
    session_limit: int,
    cutoff: str | None = None,
) -> list[TaiwanFuturesPosition]:
    sql = """
        SELECT as_of_date, contract_code, institution,
               trading_long, trading_short, trading_net,
               open_interest_long, open_interest_short, open_interest_net,
               source, retrieved_at
        FROM taiwan_futures_positions
        WHERE as_of_date <= ?
    """
    params: list[object] = [before_or_on.isoformat()]
    if cutoff is not None:
        sql += " AND retrieved_at >= ?"
        params.append(cutoff)
    sql += " ORDER BY as_of_date DESC, contract_code, institution"

    output: list[TaiwanFuturesPosition] = []
    included_dates: list[str] = []
    for row in conn.execute(sql, params).fetchall():
        as_of_text = str(row[0])
        if as_of_text not in included_dates:
            if len(included_dates) >= max(1, session_limit):
                break
            included_dates.append(as_of_text)
        output.append(
            TaiwanFuturesPosition(
                as_of_date=date.fromisoformat(as_of_text),
                contract_code=str(row[1]),
                institution=str(row[2]),
                trading_long=int(row[3]),
                trading_short=int(row[4]),
                trading_net=int(row[5]),
                open_interest_long=int(row[6]),
                open_interest_short=int(row[7]),
                open_interest_net=int(row[8]),
                source=str(row[9]),
                retrieved_at=datetime.fromisoformat(row[10]),
            )
        )
    return output


def save_earnings(conn: sqlite3.Connection, earnings: EarningsDate) -> None:
    earnings_date = earnings.earnings_date.isoformat() if earnings.earnings_date else None
    conn.execute(
        """
        DELETE FROM earnings_dates
        WHERE ticker = ?
          AND source = ?
          AND IFNULL(earnings_date, '') = IFNULL(?, '')
        """,
        (earnings.ticker, earnings.source, earnings_date),
    )
    conn.execute(
        """
        INSERT INTO earnings_dates
        (ticker, company_name, earnings_date, time_of_day, fiscal_quarter, fiscal_year, eps_estimate, revenue_estimate, source, source_retrieved_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            earnings.ticker,
            earnings.company_name,
            earnings_date,
            earnings.time_of_day,
            earnings.fiscal_quarter,
            earnings.fiscal_year,
            earnings.eps_estimate,
            earnings.revenue_estimate,
            earnings.source,
            earnings.source_retrieved_at.isoformat(),
        ),
    )


def load_next_earnings_date(
    conn: sqlite3.Connection,
    ticker: str,
    *,
    on_or_after: date,
) -> EarningsDate | None:
    """Best-known earnings date for a ticker from prior runs.

    Prefers the soonest upcoming date (earnings_date >= on_or_after); if none are
    upcoming, returns the most recent past date. Used as a fallback when the live
    fetch returns nothing.
    """
    row = conn.execute(
        """
        SELECT ticker, company_name, earnings_date, time_of_day, fiscal_quarter,
               fiscal_year, eps_estimate, revenue_estimate, source, source_retrieved_at
        FROM earnings_dates
        WHERE ticker = ? AND earnings_date IS NOT NULL AND earnings_date >= ?
        ORDER BY earnings_date ASC, source_retrieved_at DESC
        LIMIT 1
        """,
        (ticker, on_or_after.isoformat()),
    ).fetchone()
    if row is None:
        row = conn.execute(
            """
            SELECT ticker, company_name, earnings_date, time_of_day, fiscal_quarter,
                   fiscal_year, eps_estimate, revenue_estimate, source, source_retrieved_at
            FROM earnings_dates
            WHERE ticker = ? AND earnings_date IS NOT NULL
            ORDER BY earnings_date DESC, source_retrieved_at DESC
            LIMIT 1
            """,
            (ticker,),
        ).fetchone()
    if row is None:
        return None
    (tkr, company, ed, tod, fq, fy, eps, rev, source, retrieved) = row
    return EarningsDate(
        ticker=tkr,
        company_name=company,
        earnings_date=date.fromisoformat(ed),
        time_of_day=tod,
        fiscal_quarter=fq,
        fiscal_year=fy,
        eps_estimate=eps,
        revenue_estimate=rev,
        source=source,
        source_retrieved_at=datetime.fromisoformat(retrieved),
    )


def load_latest_valuation_snapshot(
    conn: sqlite3.Connection,
    ticker: str,
    *,
    before_or_on: date,
) -> ValuationSnapshot | None:
    row = conn.execute(
        """
        SELECT as_of_date, source, retrieved_at
        FROM valuation_snapshots
        WHERE ticker = ?
          AND as_of_date <= ?
          AND metric_value IS NOT NULL
        GROUP BY as_of_date, source, retrieved_at
        ORDER BY as_of_date DESC, retrieved_at DESC
        LIMIT 1
        """,
        (ticker, before_or_on.isoformat()),
    ).fetchone()
    if not row:
        return None

    as_of_date_text, source, retrieved_at_text = row
    metric_rows = conn.execute(
        """
        SELECT metric_name, metric_value
        FROM valuation_snapshots
        WHERE ticker = ?
          AND as_of_date = ?
          AND source = ?
          AND retrieved_at = ?
        ORDER BY metric_name
        """,
        (ticker, as_of_date_text, source, retrieved_at_text),
    ).fetchall()
    metrics = {name: _coerce_metric_value(value) for name, value in metric_rows}
    return ValuationSnapshot(
        ticker=ticker,
        as_of_date=date.fromisoformat(as_of_date_text),
        source=source,
        metrics=metrics,
        retrieved_at=datetime.fromisoformat(retrieved_at_text),
    )


def load_fresh_valuation_snapshot(
    conn: sqlite3.Connection,
    ticker: str,
    *,
    max_age_hours: int = 4,
) -> ValuationSnapshot | None:
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=max_age_hours)).isoformat()
    row = conn.execute(
        """
        SELECT vs.as_of_date, vs.source, vs.retrieved_at
        FROM valuation_snapshots AS vs
        WHERE vs.ticker = ?
          AND vs.retrieved_at >= ?
          AND EXISTS (
              SELECT 1
              FROM valuation_snapshots AS lc
              WHERE lc.ticker = vs.ticker
                AND lc.as_of_date = vs.as_of_date
                AND lc.source = vs.source
                AND lc.retrieved_at = vs.retrieved_at
                AND lc.metric_name = 'last_close'
                AND lc.metric_value IS NOT NULL
          )
        GROUP BY vs.as_of_date, vs.source, vs.retrieved_at
        ORDER BY retrieved_at DESC
        LIMIT 1
        """,
        (ticker, cutoff),
    ).fetchone()
    if not row:
        return None
    as_of_date_text, source, retrieved_at_text = row
    metric_rows = conn.execute(
        """
        SELECT metric_name, metric_value FROM valuation_snapshots
        WHERE ticker = ? AND as_of_date = ? AND source = ? AND retrieved_at = ?
        ORDER BY metric_name
        """,
        (ticker, as_of_date_text, source, retrieved_at_text),
    ).fetchall()
    metrics = {name: _coerce_metric_value(value) for name, value in metric_rows}
    return ValuationSnapshot(
        ticker=ticker,
        as_of_date=date.fromisoformat(as_of_date_text),
        source=source,
        metrics=metrics,
        retrieved_at=datetime.fromisoformat(retrieved_at_text),
    )


def load_ticker_research_states(
    conn: sqlite3.Connection,
    tickers: list[str] | None = None,
) -> dict[str, TickerResearchState]:
    sql = """
        SELECT ticker, tag, thesis_state, thesis_trigger, thesis_text, note, checklist_json,
               revisit_date, pinned, review_status, last_reviewed_at, updated_at,
               bull_case, bear_case, entry_plan, add_zone, reduce_zone, stop_loss,
               earnings_questions_json, position_json
        FROM ticker_research_state
    """
    params: list[Any] = []
    if tickers:
        placeholders = ", ".join("?" for _ in tickers)
        sql += f" WHERE ticker IN ({placeholders})"
        params.extend(tickers)
    sql += " ORDER BY ticker"
    rows = conn.execute(sql, params).fetchall()
    return {
        row[0]: TickerResearchState(
            ticker=row[0],
            tag=row[1] or "",
            thesis_state=row[2] or "",
            thesis_trigger=row[3] or "",
            thesis_text=row[4] or "",
            note=row[5] or "",
            checklist=_loads_json_list(row[6]),
            revisit_date=date.fromisoformat(row[7]) if row[7] else None,
            pinned=bool(row[8]),
            review_status=row[9] or "not-reviewed",
            last_reviewed_at=datetime.fromisoformat(row[10]) if row[10] else None,
            updated_at=datetime.fromisoformat(row[11]) if row[11] else None,
            bull_case=row[12] or "",
            bear_case=row[13] or "",
            entry_plan=row[14] or "",
            add_zone=row[15] or "",
            reduce_zone=row[16] or "",
            stop_loss=row[17] or "",
            earnings_questions=_loads_json_list(row[18]),
            position=_load_position_json(row[19]),
        )
        for row in rows
    }


def load_post_earnings_reviews(
    conn: sqlite3.Connection,
    tickers: list[str] | None = None,
) -> dict[str, PostEarningsReview]:
    sql = """
        SELECT ticker, earnings_date, eps, revenue, guide, eps_surprise_pct,
               revenue_surprise_pct, fy1_eps_revision_after, fy1_revenue_revision_after,
               conclusion, next_step, gross_margin_change, management_keywords,
               thesis_changed, updated_at
        FROM post_earnings_reviews
    """
    params: list[Any] = []
    if tickers:
        placeholders = ", ".join("?" for _ in tickers)
        sql += f" WHERE ticker IN ({placeholders})"
        params.extend(tickers)
    sql += " ORDER BY ticker"
    rows = conn.execute(sql, params).fetchall()
    return {
        row[0]: PostEarningsReview(
            ticker=row[0],
            earnings_date=date.fromisoformat(row[1]) if row[1] else None,
            eps=row[2] or "",
            revenue=row[3] or "",
            guide=row[4] or "",
            eps_surprise_pct=row[5],
            revenue_surprise_pct=row[6],
            fy1_eps_revision_after=row[7],
            fy1_revenue_revision_after=row[8],
            conclusion=row[9] or "",
            next_step=row[10] or "",
            gross_margin_change=row[11] or "",
            management_keywords=row[12] or "",
            thesis_changed=row[13] or "",
            updated_at=datetime.fromisoformat(row[14]) if row[14] else None,
        )
        for row in rows
    }


def upsert_ticker_research_state(conn: sqlite3.Connection, state: TickerResearchState) -> None:
    existing = load_ticker_research_states(conn, [state.ticker]).get(state.ticker)
    updated_at = state.updated_at or datetime.now(timezone.utc)
    review_status = state.review_status or _review_status_from_checklist(state.checklist)
    # Only append a history row when a field that history actually records has
    # changed. Comparing the whole dataclass (incl. updated_at) would log a row
    # on every run even when nothing substantive changed.
    if existing is None:
        changed = True
    else:
        existing_status = existing.review_status or _review_status_from_checklist(existing.checklist)
        changed = (
            existing.note != state.note
            or existing.thesis_state != state.thesis_state
            or existing.thesis_trigger != state.thesis_trigger
            or existing_status != review_status
        )
    conn.execute(
        """
        INSERT INTO ticker_research_state
        (ticker, tag, thesis_state, thesis_trigger, thesis_text, note, checklist_json, revisit_date,
         pinned, review_status, last_reviewed_at, updated_at,
         bull_case, bear_case, entry_plan, add_zone, reduce_zone, stop_loss,
         earnings_questions_json, position_json)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(ticker) DO UPDATE SET
          tag = excluded.tag,
          thesis_state = excluded.thesis_state,
          thesis_trigger = excluded.thesis_trigger,
          thesis_text = excluded.thesis_text,
          note = excluded.note,
          checklist_json = excluded.checklist_json,
          revisit_date = excluded.revisit_date,
          pinned = excluded.pinned,
          review_status = excluded.review_status,
          last_reviewed_at = excluded.last_reviewed_at,
          updated_at = excluded.updated_at,
          bull_case = excluded.bull_case,
          bear_case = excluded.bear_case,
          entry_plan = excluded.entry_plan,
          add_zone = excluded.add_zone,
          reduce_zone = excluded.reduce_zone,
          stop_loss = excluded.stop_loss,
          earnings_questions_json = excluded.earnings_questions_json,
          position_json = excluded.position_json
        """,
        (
            state.ticker,
            state.tag,
            state.thesis_state,
            state.thesis_trigger,
            state.thesis_text,
            state.note,
            json.dumps(sorted(set(state.checklist))),
            state.revisit_date.isoformat() if state.revisit_date else None,
            1 if state.pinned else 0,
            review_status,
            state.last_reviewed_at.isoformat() if state.last_reviewed_at else None,
            updated_at.isoformat(),
            state.bull_case,
            state.bear_case,
            state.entry_plan,
            state.add_zone,
            state.reduce_zone,
            state.stop_loss,
            json.dumps([str(q) for q in state.earnings_questions]),
            json.dumps(_position_payload(state.position)),
        ),
    )
    if changed:
        conn.execute(
            """
            INSERT INTO ticker_notes_history
            (ticker, note, thesis_state, thesis_trigger, review_status, changed_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                state.ticker,
                state.note,
                state.thesis_state,
                state.thesis_trigger,
                review_status,
                updated_at.isoformat(),
            ),
        )


def upsert_post_earnings_review(conn: sqlite3.Connection, review: PostEarningsReview) -> None:
    updated_at = review.updated_at or datetime.now(timezone.utc)
    conn.execute(
        """
        INSERT INTO post_earnings_reviews
        (ticker, earnings_date, eps, revenue, guide, eps_surprise_pct, revenue_surprise_pct,
         fy1_eps_revision_after, fy1_revenue_revision_after, conclusion, next_step,
         gross_margin_change, management_keywords, thesis_changed, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(ticker) DO UPDATE SET
          earnings_date = excluded.earnings_date,
          eps = excluded.eps,
          revenue = excluded.revenue,
          guide = excluded.guide,
          eps_surprise_pct = excluded.eps_surprise_pct,
          revenue_surprise_pct = excluded.revenue_surprise_pct,
          fy1_eps_revision_after = excluded.fy1_eps_revision_after,
          fy1_revenue_revision_after = excluded.fy1_revenue_revision_after,
          conclusion = excluded.conclusion,
          next_step = excluded.next_step,
          gross_margin_change = excluded.gross_margin_change,
          management_keywords = excluded.management_keywords,
          thesis_changed = excluded.thesis_changed,
          updated_at = excluded.updated_at
        """,
        (
            review.ticker,
            review.earnings_date.isoformat() if review.earnings_date else None,
            review.eps,
            review.revenue,
            review.guide,
            review.eps_surprise_pct,
            review.revenue_surprise_pct,
            review.fy1_eps_revision_after,
            review.fy1_revenue_revision_after,
            review.conclusion,
            review.next_step,
            review.gross_margin_change,
            review.management_keywords,
            review.thesis_changed,
            updated_at.isoformat(),
        ),
    )


def _trade_fill_payload(fill: TradeFill) -> dict[str, Any]:
    return {
        "fill_id": fill.fill_id,
        "side": fill.side,
        "fill_date": fill.fill_date.isoformat() if fill.fill_date else None,
        "price": fill.price,
        "shares": fill.shares,
        "fees": fill.fees,
        "note": fill.note,
    }


def _trade_fills_from_payload(raw: Any) -> list[TradeFill]:
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (TypeError, json.JSONDecodeError):
            return []
    if not isinstance(raw, list):
        return []
    fills: list[TradeFill] = []
    for index, row in enumerate(raw):
        if not isinstance(row, dict):
            continue
        side = str(row.get("side") or "").strip().lower()
        if side not in {"buy", "sell"}:
            continue
        fill_id = str(row.get("fill_id") or f"fill-{index + 1}").strip()
        fills.append(TradeFill(
            fill_id=fill_id,
            side=side,
            fill_date=_parse_date(row.get("fill_date")),
            price=_parse_float(row.get("price")),
            shares=_parse_float(row.get("shares")),
            fees=_parse_float(row.get("fees")) or 0.0,
            note=str(row.get("note") or ""),
        ))
    return fills


def load_trade_journal_entries(
    conn: sqlite3.Connection,
    tickers: list[str] | None = None,
    *,
    include_cancelled: bool = True,
) -> list[TradeJournalEntry]:
    sql = """
        SELECT trade_id, ticker, market, currency, status, entry_date,
               entry_price, shares, initial_stop, current_stop, initial_risk, exit_date,
               exit_price, fees, fx_rate_to_base, fills_json, setup, note,
               updated_at
        FROM trade_journal
    """
    conditions: list[str] = []
    params: list[Any] = []
    if tickers:
        placeholders = ", ".join("?" for _ in tickers)
        conditions.append(f"ticker IN ({placeholders})")
        params.extend(tickers)
    if not include_cancelled:
        conditions.append("status != 'cancelled'")
    if conditions:
        sql += " WHERE " + " AND ".join(conditions)
    sql += " ORDER BY COALESCE(entry_date, '') DESC, updated_at DESC, trade_id"
    rows = conn.execute(sql, params).fetchall()
    return [
        TradeJournalEntry(
            trade_id=row[0],
            ticker=row[1],
            market=row[2] or "us",
            currency=row[3] or "USD",
            status=row[4] or "open",
            entry_date=_parse_date(row[5]),
            entry_price=row[6],
            shares=row[7],
            initial_stop=row[8],
            current_stop=row[9],
            initial_risk=row[10],
            exit_date=_parse_date(row[11]),
            exit_price=row[12],
            fees=float(row[13] or 0.0),
            fx_rate_to_base=float(row[14] or 1.0),
            fills=_trade_fills_from_payload(row[15]),
            setup=row[16] or "",
            note=row[17] or "",
            updated_at=_parse_datetime(row[18]),
        )
        for row in rows
    ]


def upsert_trade_journal_entry(conn: sqlite3.Connection, trade: TradeJournalEntry) -> None:
    trade_id = trade.trade_id.strip()
    if not trade_id:
        raise ValueError("Trade journal entry requires a trade_id.")
    status = trade.status.strip().lower()
    if status not in {"planned", "open", "closed", "cancelled"}:
        status = "open"
    updated_at = trade.updated_at or datetime.now(timezone.utc)
    fills_json = json.dumps(
        [_trade_fill_payload(fill) for fill in trade.fills],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    conn.execute(
        """
        INSERT INTO trade_journal
        (trade_id, ticker, market, currency, status, entry_date, entry_price,
         shares, initial_stop, current_stop, initial_risk, exit_date, exit_price, fees,
         fx_rate_to_base, fills_json, setup, note, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(trade_id) DO UPDATE SET
          ticker = excluded.ticker,
          market = excluded.market,
          currency = excluded.currency,
          status = excluded.status,
          entry_date = excluded.entry_date,
          entry_price = excluded.entry_price,
          shares = excluded.shares,
          initial_stop = excluded.initial_stop,
          current_stop = excluded.current_stop,
          initial_risk = excluded.initial_risk,
          exit_date = excluded.exit_date,
          exit_price = excluded.exit_price,
          fees = excluded.fees,
          fx_rate_to_base = excluded.fx_rate_to_base,
          fills_json = excluded.fills_json,
          setup = excluded.setup,
          note = excluded.note,
          updated_at = excluded.updated_at
        """,
        (
            trade_id,
            trade.ticker.strip().upper(),
            trade.market.strip().lower() or "us",
            trade.currency.strip().upper() or "USD",
            status,
            trade.entry_date.isoformat() if trade.entry_date else None,
            trade.entry_price,
            trade.shares,
            trade.initial_stop,
            trade.current_stop,
            trade.initial_risk,
            trade.exit_date.isoformat() if trade.exit_date else None,
            trade.exit_price,
            trade.fees,
            trade.fx_rate_to_base if trade.fx_rate_to_base > 0 else 1.0,
            fills_json,
            trade.setup,
            trade.note,
            updated_at.isoformat(),
        ),
    )


def _trade_payload(trade: TradeJournalEntry) -> dict[str, Any]:
    return {
        "trade_id": trade.trade_id,
        "ticker": trade.ticker,
        "market": trade.market,
        "currency": trade.currency,
        "status": trade.status,
        "entry_date": trade.entry_date.isoformat() if trade.entry_date else None,
        "entry_price": trade.entry_price,
        "shares": trade.shares,
        "initial_stop": trade.initial_stop,
        "current_stop": trade.current_stop,
        "initial_risk": trade.initial_risk,
        "exit_date": trade.exit_date.isoformat() if trade.exit_date else None,
        "exit_price": trade.exit_price,
        "fees": trade.fees,
        "fx_rate_to_base": trade.fx_rate_to_base,
        "fills": [_trade_fill_payload(fill) for fill in trade.fills],
        "setup": trade.setup,
        "note": trade.note,
        "updated_at": trade.updated_at.isoformat() if trade.updated_at else None,
    }

def export_research_state_payload(conn: sqlite3.Connection) -> dict[str, Any]:
    states = load_ticker_research_states(conn)
    reviews = load_post_earnings_reviews(conn)
    trades = load_trade_journal_entries(conn)
    payload: dict[str, Any] = {
        "version": 2,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "tickers": {},
        "trades": [_trade_payload(trade) for trade in trades],
    }
    symbols = sorted(set(states) | set(reviews))
    for symbol in symbols:
        state = states.get(symbol)
        review = reviews.get(symbol)
        row: dict[str, Any] = {}
        if state is not None:
            row.update({
                "tag": state.tag,
                "thesis_state": state.thesis_state,
                "thesis_trigger": state.thesis_trigger,
                "thesis_text": state.thesis_text,
                "note": state.note,
                "checklist": list(state.checklist),
                "revisit_date": state.revisit_date.isoformat() if state.revisit_date else None,
                "pinned": state.pinned,
                "review_status": state.review_status,
                "last_reviewed_at": state.last_reviewed_at.isoformat() if state.last_reviewed_at else None,
                "bull_case": state.bull_case,
                "bear_case": state.bear_case,
                "entry_plan": state.entry_plan,
                "add_zone": state.add_zone,
                "reduce_zone": state.reduce_zone,
                "stop_loss": state.stop_loss,
                "earnings_questions": list(state.earnings_questions),
                "position": _position_payload(state.position),
            })
        if review is not None:
            row["post_earnings_review"] = {
                "earnings_date": review.earnings_date.isoformat() if review.earnings_date else None,
                "eps": review.eps,
                "revenue": review.revenue,
                "guide": review.guide,
                "eps_surprise_pct": review.eps_surprise_pct,
                "revenue_surprise_pct": review.revenue_surprise_pct,
                "fy1_eps_revision_after": review.fy1_eps_revision_after,
                "fy1_revenue_revision_after": review.fy1_revenue_revision_after,
                "conclusion": review.conclusion,
                "next_step": review.next_step,
                "gross_margin_change": review.gross_margin_change,
                "management_keywords": review.management_keywords,
                "thesis_changed": review.thesis_changed,
            }
        payload["tickers"][symbol] = row
    return payload


def export_research_state_file(conn: sqlite3.Connection, path: str | Path) -> Path:
    export_path = Path(path)
    export_path.parent.mkdir(parents=True, exist_ok=True)
    export_path.write_text(
        json.dumps(export_research_state_payload(conn), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return export_path


def import_research_state_payload(conn: sqlite3.Connection, payload: dict[str, Any]) -> None:
    exported = payload.get("tickers", {})
    if not isinstance(exported, dict):
        raise ValueError("Research state payload must contain a 'tickers' object.")

    for symbol, row in exported.items():
        if not isinstance(row, dict):
            continue
        checklist = row.get("checklist", [])
        checklist_values = [str(value) for value in checklist] if isinstance(checklist, list) else []
        review_status = str(row.get("review_status") or _review_status_from_checklist(checklist_values))
        last_reviewed_at = _parse_datetime(row.get("last_reviewed_at"))
        if review_status == "reviewed" and last_reviewed_at is None:
            last_reviewed_at = datetime.now(timezone.utc)
        state = TickerResearchState(
            ticker=str(symbol).upper(),
            tag=str(row.get("tag") or ""),
            thesis_state=str(row.get("thesis_state") or ""),
            thesis_trigger=str(row.get("thesis_trigger") or ""),
            thesis_text=str(row.get("thesis_text") or ""),
            note=str(row.get("note") or ""),
            checklist=checklist_values,
            revisit_date=_parse_date(row.get("revisit_date")),
            pinned=bool(row.get("pinned", False)),
            review_status=review_status,
            last_reviewed_at=last_reviewed_at,
            updated_at=datetime.now(timezone.utc),
            bull_case=str(row.get("bull_case") or ""),
            bear_case=str(row.get("bear_case") or ""),
            entry_plan=str(row.get("entry_plan") or ""),
            add_zone=str(row.get("add_zone") or ""),
            reduce_zone=str(row.get("reduce_zone") or ""),
            stop_loss=str(row.get("stop_loss") or ""),
            earnings_questions=_import_questions(row.get("earnings_questions")),
            position=_position_from_payload(row.get("position")),
        )
        upsert_ticker_research_state(conn, state)

        review_row = row.get("post_earnings_review")
        if isinstance(review_row, dict):
            upsert_post_earnings_review(
                conn,
                PostEarningsReview(
                    ticker=str(symbol).upper(),
                    earnings_date=_parse_date(review_row.get("earnings_date")),
                    eps=str(review_row.get("eps") or ""),
                    revenue=str(review_row.get("revenue") or ""),
                    guide=str(review_row.get("guide") or ""),
                    eps_surprise_pct=_parse_float(review_row.get("eps_surprise_pct")),
                    revenue_surprise_pct=_parse_float(review_row.get("revenue_surprise_pct")),
                    fy1_eps_revision_after=_parse_float(review_row.get("fy1_eps_revision_after")),
                    fy1_revenue_revision_after=_parse_float(review_row.get("fy1_revenue_revision_after")),
                    conclusion=str(review_row.get("conclusion") or ""),
                    next_step=str(review_row.get("next_step") or ""),
                    gross_margin_change=str(review_row.get("gross_margin_change") or ""),
                    management_keywords=str(review_row.get("management_keywords") or ""),
                    thesis_changed=str(review_row.get("thesis_changed") or ""),
                    updated_at=datetime.now(timezone.utc),
                ),
            )

    trades = payload.get("trades", [])
    if trades is not None and not isinstance(trades, list):
        raise ValueError("Research state payload 'trades' must be an array.")
    for index, row in enumerate(trades or []):
        if not isinstance(row, dict):
            continue
        ticker = str(row.get("ticker") or "").strip().upper()
        if not ticker:
            continue
        entry_date = _parse_date(row.get("entry_date"))
        trade_id = str(row.get("trade_id") or "").strip()
        if not trade_id:
            trade_id = f"{ticker}-{entry_date.isoformat() if entry_date else 'undated'}-{index + 1}"
        exit_date = _parse_date(row.get("exit_date"))
        exit_price = _parse_float(row.get("exit_price"))
        status = str(row.get("status") or ("closed" if exit_date or exit_price is not None else "open"))
        upsert_trade_journal_entry(
            conn,
            TradeJournalEntry(
                trade_id=trade_id,
                ticker=ticker,
                market=str(row.get("market") or "us"),
                currency=str(row.get("currency") or "USD"),
                status=status,
                entry_date=entry_date,
                entry_price=_parse_float(row.get("entry_price")),
                shares=_parse_float(row.get("shares")),
                initial_stop=_parse_float(row.get("initial_stop")),
                current_stop=_parse_float(row.get("current_stop")),
                initial_risk=_parse_float(row.get("initial_risk")),
                exit_date=exit_date,
                exit_price=exit_price,
                fees=_parse_float(row.get("fees")) or 0.0,
                fx_rate_to_base=_parse_float(row.get("fx_rate_to_base")) or 1.0,
                fills=_trade_fills_from_payload(row.get("fills")),
                setup=str(row.get("setup") or ""),
                note=str(row.get("note") or ""),
                updated_at=_parse_datetime(row.get("updated_at")) or datetime.now(timezone.utc),
            ),
        )
    conn.commit()


def import_research_state_file(conn: sqlite3.Connection, path: str | Path) -> None:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Research state file must contain a JSON object.")
    import_research_state_payload(conn, payload)


def save_report_run(
    conn: sqlite3.Connection,
    report: DailyReport,
    *,
    html_path: str | Path = "",
    right_side_signals: dict[str, dict[str, object]] | None = None,
    score_snapshots: dict[str, dict[str, object]] | None = None,
) -> int:
    html_text = str(html_path)
    created_at = datetime.now(timezone.utc).isoformat()
    cursor = conn.execute(
        """
        INSERT INTO report_runs (report_date, generated_at, html_path, warning_count, created_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            report.report_date.isoformat(),
            report.generated_at.isoformat(),
            html_text,
            len(report.warnings),
            created_at,
        ),
    )
    run_id = int(cursor.lastrowid)
    premarket_changes = {
        move.symbol: move.change_pct
        for move in (report.premarket.watchlist_movers if report.premarket else [])
    }
    signals = right_side_signals or {}
    scores = score_snapshots or {}
    for item in report.ticker_reports:
        state = report.research_states.get(item.ticker.symbol, TickerResearchState(ticker=item.ticker.symbol))
        signal = signals.get(item.ticker.symbol, {})
        score = scores.get(item.ticker.symbol, {})
        score_data_date = score.get("data_date")
        if isinstance(score_data_date, date):
            score_data_date_text = score_data_date.isoformat()
        elif score_data_date:
            score_data_date_text = str(score_data_date)
        else:
            score_data_date_text = None
        baseline_top_news = _load_prior_top_news_baseline(conn, item.ticker.symbol, report.report_date, days=30)
        top_news_count = sum(1 for article in item.articles if article.importance_score >= 1.0)
        news_burst_score = float(top_news_count) - baseline_top_news
        attention_score = _attention_score(
            news_count=len(item.articles),
            top_news_count=top_news_count,
            is_holding=item.ticker.position.status == "holding",
            earnings_days=_earnings_days(item, report.report_date),
            valuation_risk=_valuation_risk(item),
            thesis_state=state.thesis_state,
            last_reviewed_at=state.last_reviewed_at,
            news_burst_score=news_burst_score,
        )
        rsi = _metric_float(item.valuation.metrics.get("rsi_14")) if item.valuation else None
        conn.execute(
            """
            INSERT INTO news_daily_summary
            (report_run_id, report_date, generated_at, ticker, thesis_state, review_status,
             last_reviewed_at, news_count, top_news_count, valuation_risk, rsi, daily_change_pct,
             premarket_change_pct, earnings_days, warning_count, attention_score, news_burst_score,
             last_close, right_side_status, right_side_tone, right_side_ready_count,
             right_side_check_count, score_data_date, health_score, health_trend_score,
             health_momentum_score, health_volume_score, health_fundamental_score,
             health_risk_score, health_status, health_coverage, health_rule_version,
             right_side_score, right_side_rule_version, signal_entry, signal_stop, signal_risk_pct)
            VALUES
            (:report_run_id, :report_date, :generated_at, :ticker, :thesis_state, :review_status,
             :last_reviewed_at, :news_count, :top_news_count, :valuation_risk, :rsi, :daily_change_pct,
             :premarket_change_pct, :earnings_days, :warning_count, :attention_score, :news_burst_score,
             :last_close, :right_side_status, :right_side_tone, :right_side_ready_count,
             :right_side_check_count, :score_data_date, :health_score, :health_trend_score,
             :health_momentum_score, :health_volume_score, :health_fundamental_score,
             :health_risk_score, :health_status, :health_coverage, :health_rule_version,
             :right_side_score, :right_side_rule_version, :signal_entry, :signal_stop, :signal_risk_pct)
            ON CONFLICT(report_date, ticker) DO UPDATE SET
              report_run_id = excluded.report_run_id,
              generated_at = excluded.generated_at,
              thesis_state = excluded.thesis_state,
              review_status = excluded.review_status,
              last_reviewed_at = excluded.last_reviewed_at,
              news_count = excluded.news_count,
              top_news_count = excluded.top_news_count,
              valuation_risk = excluded.valuation_risk,
              rsi = excluded.rsi,
              daily_change_pct = excluded.daily_change_pct,
              premarket_change_pct = excluded.premarket_change_pct,
              earnings_days = excluded.earnings_days,
              warning_count = excluded.warning_count,
              attention_score = excluded.attention_score,
              news_burst_score = excluded.news_burst_score,
              last_close = excluded.last_close,
              right_side_status = excluded.right_side_status,
              right_side_tone = excluded.right_side_tone,
              right_side_ready_count = excluded.right_side_ready_count,
              right_side_check_count = excluded.right_side_check_count,
              score_data_date = COALESCE(excluded.score_data_date, news_daily_summary.score_data_date),
              health_score = CASE WHEN excluded.score_data_date IS NOT NULL THEN excluded.health_score ELSE news_daily_summary.health_score END,
              health_trend_score = CASE WHEN excluded.score_data_date IS NOT NULL THEN excluded.health_trend_score ELSE news_daily_summary.health_trend_score END,
              health_momentum_score = CASE WHEN excluded.score_data_date IS NOT NULL THEN excluded.health_momentum_score ELSE news_daily_summary.health_momentum_score END,
              health_volume_score = CASE WHEN excluded.score_data_date IS NOT NULL THEN excluded.health_volume_score ELSE news_daily_summary.health_volume_score END,
              health_fundamental_score = CASE WHEN excluded.score_data_date IS NOT NULL THEN excluded.health_fundamental_score ELSE news_daily_summary.health_fundamental_score END,
              health_risk_score = CASE WHEN excluded.score_data_date IS NOT NULL THEN excluded.health_risk_score ELSE news_daily_summary.health_risk_score END,
              health_status = CASE WHEN excluded.score_data_date IS NOT NULL THEN excluded.health_status ELSE news_daily_summary.health_status END,
              health_coverage = CASE WHEN excluded.score_data_date IS NOT NULL THEN excluded.health_coverage ELSE news_daily_summary.health_coverage END,
              health_rule_version = CASE WHEN excluded.score_data_date IS NOT NULL THEN excluded.health_rule_version ELSE news_daily_summary.health_rule_version END,
              right_side_score = CASE WHEN excluded.score_data_date IS NOT NULL THEN excluded.right_side_score ELSE news_daily_summary.right_side_score END,
              right_side_rule_version = CASE WHEN excluded.score_data_date IS NOT NULL THEN excluded.right_side_rule_version ELSE news_daily_summary.right_side_rule_version END,
              signal_entry = excluded.signal_entry,
              signal_stop = excluded.signal_stop,
              signal_risk_pct = excluded.signal_risk_pct
            """,
            {
                "report_run_id": run_id,
                "report_date": report.report_date.isoformat(),
                "generated_at": report.generated_at.isoformat(),
                "ticker": item.ticker.symbol,
                "thesis_state": state.thesis_state,
                "review_status": state.review_status,
                "last_reviewed_at": state.last_reviewed_at.isoformat() if state.last_reviewed_at else None,
                "news_count": len(item.articles),
                "top_news_count": top_news_count,
                "valuation_risk": _valuation_risk(item),
                "rsi": rsi,
                "daily_change_pct": _daily_change_pct(item),
                "premarket_change_pct": premarket_changes.get(item.ticker.symbol),
                "earnings_days": _earnings_days(item, report.report_date),
                "warning_count": len(item.warnings),
                "attention_score": round(attention_score, 2),
                "news_burst_score": round(news_burst_score, 2),
                "last_close": _metric_float(item.valuation.metrics.get("last_close")) if item.valuation else None,
                "right_side_status": str(signal.get("status", "")),
                "right_side_tone": str(signal.get("tone", "")),
                "right_side_ready_count": int(signal.get("ready_count", 0) or 0),
                "right_side_check_count": int(signal.get("check_count", 0) or 0),
                "score_data_date": score_data_date_text,
                "health_score": score.get("health_score"),
                "health_trend_score": score.get("health_trend_score"),
                "health_momentum_score": score.get("health_momentum_score"),
                "health_volume_score": score.get("health_volume_score"),
                "health_fundamental_score": score.get("health_fundamental_score"),
                "health_risk_score": score.get("health_risk_score"),
                "health_status": str(score.get("health_status", "")),
                "health_coverage": int(score.get("health_coverage", 0) or 0),
                "health_rule_version": str(score.get("health_rule_version", "")),
                "right_side_score": score.get("right_side_score"),
                "right_side_rule_version": str(score.get("right_side_rule_version", "")),
                "signal_entry": signal.get("entry_reference"),
                "signal_stop": signal.get("invalidation"),
                "signal_risk_pct": signal.get("risk_pct"),
            },
        )
    conn.commit()
    return run_id


def load_ticker_history(
    conn: sqlite3.Connection,
    tickers: list[str],
    *,
    report_date: date,
    history_days: int,
) -> dict[str, list[TickerHistoryPoint]]:
    if not tickers:
        return {}
    placeholders = ", ".join("?" for _ in tickers)
    since_date = (report_date - timedelta(days=max(1, history_days))).isoformat()
    rows = conn.execute(
        f"""
        SELECT report_date, generated_at, ticker, thesis_state, review_status, last_reviewed_at,
               news_count, top_news_count, valuation_risk, rsi, daily_change_pct, premarket_change_pct,
               earnings_days, warning_count, attention_score, news_burst_score, last_close,
               right_side_status, right_side_tone, right_side_ready_count, right_side_check_count,
               score_data_date, health_score, health_trend_score, health_momentum_score,
               health_volume_score, health_fundamental_score, health_risk_score, health_status,
               health_coverage, health_rule_version, right_side_score, right_side_rule_version,
               signal_entry, signal_stop, signal_risk_pct
        FROM news_daily_summary
        WHERE ticker IN ({placeholders})
          AND report_date >= ?
        ORDER BY ticker, report_date DESC, generated_at DESC
        """,
        [*tickers, since_date],
    ).fetchall()
    result: dict[str, list[TickerHistoryPoint]] = {ticker: [] for ticker in tickers}
    for row in rows:
        point = TickerHistoryPoint(
            report_date=date.fromisoformat(row[0]),
            generated_at=datetime.fromisoformat(row[1]),
            ticker=row[2],
            thesis_state=row[3] or "",
            review_status=row[4] or "not-reviewed",
            last_reviewed_at=datetime.fromisoformat(row[5]) if row[5] else None,
            news_count=int(row[6] or 0),
            top_news_count=int(row[7] or 0),
            valuation_risk=row[8] or "None",
            rsi=row[9],
            daily_change_pct=row[10],
            premarket_change_pct=row[11],
            earnings_days=row[12],
            warning_count=int(row[13] or 0),
            attention_score=float(row[14] or 0.0),
            news_burst_score=float(row[15] or 0.0),
            last_close=row[16],
            right_side_status=row[17] or "",
            right_side_tone=row[18] or "",
            right_side_ready_count=int(row[19] or 0),
            right_side_check_count=int(row[20] or 0),
            score_data_date=date.fromisoformat(row[21]) if row[21] else None,
            health_score=row[22],
            health_trend_score=row[23],
            health_momentum_score=row[24],
            health_volume_score=row[25],
            health_fundamental_score=row[26],
            health_risk_score=row[27],
            health_status=row[28] or "",
            health_coverage=int(row[29] or 0),
            health_rule_version=row[30] or "",
            right_side_score=row[31],
            right_side_rule_version=row[32] or "",
            signal_entry=row[33],
            signal_stop=row[34],
            signal_risk_pct=row[35],
        )
        result.setdefault(point.ticker, []).append(point)
    return result


def load_report_dates(conn: sqlite3.Connection, *, limit: int = 30) -> list[str]:
    rows = conn.execute(
        """
        SELECT report_date
        FROM report_runs
        GROUP BY report_date
        ORDER BY MAX(generated_at) DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return [str(row[0]) for row in rows]


def _load_prior_top_news_baseline(
    conn: sqlite3.Connection,
    ticker: str,
    report_date: date,
    *,
    days: int,
) -> float:
    start = (report_date - timedelta(days=days)).isoformat()
    row = conn.execute(
        """
        SELECT AVG(top_news_count)
        FROM news_daily_summary
        WHERE ticker = ?
          AND report_date >= ?
          AND report_date < ?
        """,
        (ticker, start, report_date.isoformat()),
    ).fetchone()
    value = row[0] if row else None
    return float(value) if value is not None else 0.0


def _attention_score(
    *,
    news_count: int,
    top_news_count: int,
    is_holding: bool,
    earnings_days: int | None,
    valuation_risk: str,
    thesis_state: str,
    last_reviewed_at: datetime | None,
    news_burst_score: float,
) -> float:
    score = float(news_count) * 1.5 + float(top_news_count) * 6.0
    if is_holding:
        score += 4.0
    if earnings_days is not None:
        if earnings_days == 0:
            score += 8.0
        elif earnings_days == 1:
            score += 5.0
        elif 0 < earnings_days <= 7:
            score += 2.0
        elif -7 <= earnings_days < 0:
            score += 4.0
    score += {
        "Elevated": 2.0,
        "High": 4.0,
        "Extreme": 6.0,
    }.get(valuation_risk, 0.0)
    if thesis_state in {"weakening", "broken"}:
        score += 5.0
    if news_burst_score > 0:
        score += min(news_burst_score * 4.0, 12.0)
    if thesis_state in {"building", "active"} and _is_stale_review(last_reviewed_at, days=14):
        score += 3.0
    return score


def _valuation_risk(item: Any) -> str:
    if not getattr(item, "valuation", None):
        return "None"
    values: list[float] = []
    for key in ("trailing_pe", "forward_pe"):
        value = _metric_float(item.valuation.metrics.get(key))
        if value is not None:
            values.append(value)
    if not values:
        return "None"
    highest = max(values)
    if highest >= 200:
        return "Extreme"
    if highest >= 100:
        return "High"
    if highest >= 50:
        return "Elevated"
    return "None"


def _earnings_days(item: Any, anchor: date) -> int | None:
    earnings = getattr(item, "earnings", None)
    earnings_date = getattr(earnings, "earnings_date", None)
    if not isinstance(earnings_date, date):
        return None
    return (earnings_date - anchor).days


def _daily_change_pct(item: Any) -> float | None:
    valuation = getattr(item, "valuation", None)
    if valuation is None:
        return None
    last = _metric_float(valuation.metrics.get("last_close"))
    prev = _metric_float(valuation.metrics.get("previous_close"))
    if last is None or prev in (None, 0):
        return None
    return (last - prev) / prev * 100.0


def _metric_float(value: Any) -> float | None:
    if not isinstance(value, (int, float)):
        return None
    number = float(value)
    if math.isnan(number):
        return None
    return number


def _is_stale_review(last_reviewed_at: datetime | None, *, days: int) -> bool:
    if last_reviewed_at is None:
        return True
    return (datetime.now(timezone.utc) - last_reviewed_at.astimezone(timezone.utc)).days >= days


def _review_status_from_checklist(checklist: list[str]) -> str:
    count = len(set(checklist))
    if count >= 4:
        return "reviewed"
    if count >= 1:
        return "in-progress"
    return "not-reviewed"


def _parse_date(value: Any) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        return None


def _parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _parse_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _loads_json_list(value: Any) -> list[str]:
    if not value:
        return []
    try:
        loaded = json.loads(str(value))
    except json.JSONDecodeError:
        return []
    if not isinstance(loaded, list):
        return []
    return [str(item) for item in loaded if str(item)]


def _import_questions(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    return []


def _position_payload(position: PositionConfig | None) -> dict[str, Any]:
    if position is None:
        return {}
    return {
        "status": position.status,
        "shares": position.shares,
        "avg_cost": position.avg_cost,
        "portfolio_weight": position.portfolio_weight,
        "position_size": position.position_size,
        "stop_loss": position.stop_loss,
        "sector": position.sector,
    }


def _load_position_json(value: Any) -> PositionConfig | None:
    if not value:
        return None
    try:
        payload = json.loads(str(value))
    except json.JSONDecodeError:
        return None
    return _position_from_payload(payload)


def _position_from_payload(value: Any) -> PositionConfig | None:
    if not isinstance(value, dict):
        return None
    status = str(value.get("status") or "").strip()
    shares = _parse_float(value.get("shares"))
    avg_cost = _parse_float(value.get("avg_cost"))
    portfolio_weight = _parse_float(value.get("portfolio_weight"))
    position_size = _parse_float(value.get("position_size"))
    stop_loss = _parse_float(value.get("stop_loss"))
    sector = str(value.get("sector") or "").strip()
    if not any((status, sector, shares is not None, avg_cost is not None, portfolio_weight is not None, position_size is not None, stop_loss is not None)):
        return None
    return PositionConfig(
        status=status or "watchlist",
        shares=shares,
        avg_cost=avg_cost,
        portfolio_weight=portfolio_weight,
        position_size=position_size,
        stop_loss=stop_loss,
        sector=sector,
    )


def _serialize_metric_value(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, (list, dict, tuple)):
        return json.dumps(value, ensure_ascii=True, separators=(",", ":"))
    return str(value)


def _coerce_metric_value(value: str | None) -> object:
    if value is None:
        return None
    stripped = value.strip()
    if stripped.startswith(("[", "{")):
        try:
            decoded = json.loads(stripped)
        except json.JSONDecodeError:
            pass
        else:
            if isinstance(decoded, (list, dict)):
                return decoded
    try:
        number = float(value)
    except ValueError:
        return value
    if number.is_integer():
        return int(number)
    return number
