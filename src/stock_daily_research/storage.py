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
    TickerHistoryPoint,
    TickerResearchState,
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
    _ensure_column(conn, "news_daily_summary", "generated_at", "TEXT NOT NULL DEFAULT ''")
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
    for state in report.research_states.values():
        upsert_ticker_research_state(conn, state)
    for review in report.post_earnings_reviews.values():
        upsert_post_earnings_review(conn, review)
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
                None if metric_value is None else str(metric_value),
                valuation.retrieved_at.isoformat(),
            ),
        )


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


def export_research_state_payload(conn: sqlite3.Connection) -> dict[str, Any]:
    states = load_ticker_research_states(conn)
    reviews = load_post_earnings_reviews(conn)
    payload: dict[str, Any] = {
        "version": 1,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "tickers": {},
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
    for item in report.ticker_reports:
        state = report.research_states.get(item.ticker.symbol, TickerResearchState(ticker=item.ticker.symbol))
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
             premarket_change_pct, earnings_days, warning_count, attention_score, news_burst_score)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
              news_burst_score = excluded.news_burst_score
            """,
            (
                run_id,
                report.report_date.isoformat(),
                report.generated_at.isoformat(),
                item.ticker.symbol,
                state.thesis_state,
                state.review_status,
                state.last_reviewed_at.isoformat() if state.last_reviewed_at else None,
                len(item.articles),
                top_news_count,
                _valuation_risk(item),
                rsi,
                _daily_change_pct(item),
                premarket_changes.get(item.ticker.symbol),
                _earnings_days(item, report.report_date),
                len(item.warnings),
                round(attention_score, 2),
                round(news_burst_score, 2),
            ),
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
               earnings_days, warning_count, attention_score, news_burst_score
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
