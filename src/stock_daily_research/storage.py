from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import date, datetime
from pathlib import Path

from .models import DailyReport, EarningsDate, NewsArticle, ValuationSnapshot, XSignal


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

CREATE INDEX IF NOT EXISTS idx_news_articles_ticker ON news_articles(ticker);
CREATE INDEX IF NOT EXISTS idx_news_articles_published_at ON news_articles(published_at);
CREATE INDEX IF NOT EXISTS idx_x_signals_ticker ON x_signals(ticker);
CREATE INDEX IF NOT EXISTS idx_valuation_ticker_date ON valuation_snapshots(ticker, as_of_date);
CREATE INDEX IF NOT EXISTS idx_earnings_ticker ON earnings_dates(ticker);
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
    """Migrate legacy schemas that lack the current UNIQUE constraints.

    Earlier versions used UNIQUE(url) on news_articles (drops cross-ticker rows)
    and no unique on earnings_dates (rows accumulated daily).
    """
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

    conn.commit()


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
    conn.commit()


def save_article(conn: sqlite3.Connection, article: NewsArticle) -> None:
    conn.execute(
        """
        INSERT OR REPLACE INTO news_articles
        (ticker, title, source, domain, published_at, url, summary, event_type, importance_score)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                None if metric_value is None else str(metric_value),
                valuation.retrieved_at.isoformat(),
            ),
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


def _coerce_metric_value(value: str | None) -> object:
    if value is None:
        return None
    try:
        number = float(value)
    except ValueError:
        return value
    if number.is_integer():
        return int(number)
    return number


def save_earnings(conn: sqlite3.Connection, earnings: EarningsDate) -> None:
    conn.execute(
        """
        INSERT OR REPLACE INTO earnings_dates
        (ticker, company_name, earnings_date, time_of_day, fiscal_quarter, fiscal_year, eps_estimate, revenue_estimate, source, source_retrieved_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            earnings.ticker,
            earnings.company_name,
            earnings.earnings_date.isoformat() if earnings.earnings_date else None,
            earnings.time_of_day,
            earnings.fiscal_quarter,
            earnings.fiscal_year,
            earnings.eps_estimate,
            earnings.revenue_estimate,
            earnings.source,
            earnings.source_retrieved_at.isoformat(),
        ),
    )
