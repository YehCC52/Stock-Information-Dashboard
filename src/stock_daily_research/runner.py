from __future__ import annotations

import sys
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import closing
from dataclasses import replace
from datetime import date, datetime, timedelta
from pathlib import Path
import sqlite3
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

from .config import load_config
from .macro import OfficialMacroCalendarProvider
from .market_context import fetch_market_context
from .market_sentiment import fetch_market_sentiment
from .models import DailyReport, TickerConfig, TickerReport, XSignal
from .news import GoogleNewsRssProvider
from .notify import build_daily_summary, build_telegram_notifier
from .premarket import fetch_overnight_premarket
from .report import write_report
from .storage import (
    export_research_state_file,
    import_research_state_file,
    init_db,
    load_latest_valuation_snapshot,
    load_post_earnings_reviews,
    load_report_dates,
    load_ticker_history,
    load_ticker_research_states,
    save_report,
    save_report_run,
)
from .valuation import fetch_yfinance_earnings_date, fetch_yfinance_valuation
from .x_signals import load_manual_x_signals


DEFAULT_FETCH_WORKERS = 6


def run_daily(
    config_path: str | Path,
    report_date: date | None = None,
    output_dir: str | Path = "reports",
    db_path: str | Path = "data/stock_daily.sqlite3",
    fetch_news: bool = True,
    fetch_valuation: bool = True,
    fetch_macro: bool = True,
    notify_telegram: bool = False,
    max_workers: int = DEFAULT_FETCH_WORKERS,
    progress: bool = True,
    import_research_state_path: str | Path | None = None,
    export_research_state_path: str | Path | None = None,
    history_days: int = 30,
) -> DailyReport:
    load_dotenv()
    config = load_config(config_path)
    zone = ZoneInfo(config.settings.report_timezone)
    generated_at = datetime.now(zone)
    actual_report_date = report_date or generated_at.date()
    ticker_symbols = [ticker.symbol for ticker in config.tickers]

    global_warnings: list[str] = []
    if config.settings.x_signals.mode != "manual":
        global_warnings.append("X API automation is disabled in this MVP to avoid paid/usage-billed API calls.")
    if not fetch_news:
        global_warnings.append("News fetching skipped by --no-news.")
    if not fetch_valuation:
        global_warnings.append("Valuation and earnings fetching skipped by --no-valuation.")
    if not fetch_macro:
        global_warnings.append("Macro calendar fetching skipped by --no-macro.")

    market_sentiment = None
    market_context = None
    premarket = None
    if fetch_valuation:
        try:
            market_sentiment = fetch_market_sentiment()
            global_warnings.extend(market_sentiment.warnings)
        except Exception as exc:
            global_warnings.append(f"Market sentiment fetch failed: {exc}")
        try:
            market_context = fetch_market_context()
            global_warnings.extend(market_context.warnings)
        except Exception as exc:
            global_warnings.append(f"Market context fetch failed: {exc}")
        try:
            premarket = fetch_overnight_premarket(config.tickers, max_workers=max(1, max_workers))
            global_warnings.extend(premarket.warnings)
        except Exception as exc:
            global_warnings.append(f"Premarket snapshot fetch failed: {exc}")
    else:
        global_warnings.append("Market sentiment skipped because valuation fetching is disabled.")

    telegram_notifier = None
    should_notify_telegram = notify_telegram or config.settings.notifications.telegram.enabled
    if should_notify_telegram:
        telegram_notifier = build_telegram_notifier(
            disable_web_page_preview=config.settings.notifications.telegram.disable_web_page_preview
        )
        if telegram_notifier is None:
            global_warnings.append("Telegram notification skipped: TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID is missing.")

    with closing(init_db(db_path)) as conn:
        if import_research_state_path:
            import_research_state_file(conn, import_research_state_path)
        research_states = load_ticker_research_states(conn, ticker_symbols)
        post_earnings_reviews = load_post_earnings_reviews(conn, ticker_symbols)

        news_provider = GoogleNewsRssProvider()
        manual_x_signals = load_manual_x_signals(config.settings.x_signals.manual_file, config.tickers)
        signals_by_ticker: dict[str, list[XSignal]] = defaultdict(list)
        for signal in manual_x_signals:
            signals_by_ticker[signal.ticker].append(signal)

        ticker_reports = _fetch_all_tickers(
            config.tickers,
            news_provider=news_provider,
            signals_by_ticker=signals_by_ticker,
            fetch_news=fetch_news,
            fetch_valuation=fetch_valuation,
            lookback_days=config.settings.news.lookback_days,
            max_articles=config.settings.news.max_articles_per_ticker,
            max_workers=max(1, max_workers),
            progress=progress,
        )
        economic_events = []
        if fetch_macro and config.settings.macro.enabled:
            macro_result = OfficialMacroCalendarProvider().fetch(
                report_date=actual_report_date,
                timezone_name=config.settings.report_timezone,
                days_back=config.settings.macro.days_back,
                days_ahead=config.settings.macro.days_ahead,
                manual_events=config.settings.macro.manual_events,
                cache_path=Path(db_path).parent / "macro_events_cache.json",
            )
            economic_events = macro_result.events
            global_warnings.extend(macro_result.warnings)

        if fetch_valuation:
            ticker_reports = _apply_valuation_fallbacks(conn, ticker_reports, actual_report_date)
            ticker_reports = _apply_estimate_revision_history(conn, ticker_reports, actual_report_date)

        report_path = Path(output_dir) / f"{actual_report_date.isoformat()}.html"
        preliminary_report = DailyReport(
            report_date=actual_report_date,
            generated_at=generated_at,
            ticker_reports=ticker_reports,
            warnings=list(global_warnings),
            economic_events=economic_events,
            market_sentiment=market_sentiment,
            market_context=market_context,
            premarket=premarket,
            research_states=research_states,
            post_earnings_reviews=post_earnings_reviews,
        )
        save_report(conn, preliminary_report)
        save_report_run(conn, preliminary_report, html_path=report_path)
        ticker_history = load_ticker_history(
            conn,
            ticker_symbols,
            report_date=actual_report_date,
            history_days=max(7, history_days),
        )
        history_overview = {
            "history_days": max(7, history_days),
            "archive_dates": load_report_dates(conn, limit=max(history_days, 30)),
        }
        if export_research_state_path:
            export_research_state_file(conn, export_research_state_path)

    if telegram_notifier:
        try:
            telegram_notifier.send_message(build_daily_summary(preliminary_report, str(report_path)))
        except Exception as exc:
            global_warnings.append(f"Telegram notification failed: {exc}")

    report = DailyReport(
        report_date=actual_report_date,
        generated_at=generated_at,
        ticker_reports=ticker_reports,
        warnings=global_warnings,
        economic_events=economic_events,
        market_sentiment=market_sentiment,
        market_context=market_context,
        premarket=premarket,
        research_states=research_states,
        post_earnings_reviews=post_earnings_reviews,
        ticker_history=ticker_history,
        history_overview=history_overview,
    )
    write_report(report, output_dir)
    return report


def _fetch_all_tickers(
    tickers: list[TickerConfig],
    *,
    news_provider: GoogleNewsRssProvider,
    signals_by_ticker: dict[str, list[XSignal]],
    fetch_news: bool,
    fetch_valuation: bool,
    lookback_days: int,
    max_articles: int,
    max_workers: int,
    progress: bool,
) -> list[TickerReport]:
    total = len(tickers)
    if progress:
        print(f"Fetching {total} tickers with {max_workers} workers...", file=sys.stderr, flush=True)

    def worker(ticker: TickerConfig) -> TickerReport:
        return _fetch_one_ticker(
            ticker,
            news_provider=news_provider,
            signals=signals_by_ticker.get(ticker.symbol, []),
            fetch_news=fetch_news,
            fetch_valuation=fetch_valuation,
            lookback_days=lookback_days,
            max_articles=max_articles,
        )

    results: dict[str, TickerReport] = {}
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(worker, ticker): ticker for ticker in tickers}
        for future in as_completed(futures):
            ticker = futures[future]
            try:
                results[ticker.symbol] = future.result()
            except Exception as exc:
                results[ticker.symbol] = TickerReport(
                    ticker=ticker,
                    articles=[],
                    x_signals=signals_by_ticker.get(ticker.symbol, []),
                    valuation=None,
                    earnings=None,
                    warnings=[f"Worker crashed: {exc}"],
                )
            if progress:
                done = len(results)
                print(f"  [{done}/{total}] {ticker.symbol}", file=sys.stderr, flush=True)

    return [results[ticker.symbol] for ticker in tickers]


def _apply_valuation_fallbacks(
    conn: sqlite3.Connection,
    ticker_reports: list[TickerReport],
    report_date: date,
) -> list[TickerReport]:
    result: list[TickerReport] = []
    for item in ticker_reports:
        if item.valuation and _has_usable_valuation(item.valuation.metrics):
            result.append(item)
            continue

        fallback = load_latest_valuation_snapshot(
            conn,
            item.ticker.symbol,
            before_or_on=report_date,
        )
        if not fallback:
            result.append(item)
            continue

        warnings = [
            *item.warnings,
            f"Valuation fallback used: latest available {fallback.as_of_date.isoformat()} from {fallback.source}.",
        ]
        result.append(replace(item, valuation=fallback, warnings=warnings))
    return result


def _apply_estimate_revision_history(
    conn: sqlite3.Connection,
    ticker_reports: list[TickerReport],
    report_date: date,
) -> list[TickerReport]:
    result: list[TickerReport] = []
    anchor = report_date - timedelta(days=30)
    for item in ticker_reports:
        if not item.valuation:
            result.append(item)
            continue
        prior = load_latest_valuation_snapshot(conn, item.ticker.symbol, before_or_on=anchor)
        if not prior:
            result.append(item)
            continue
        metrics = dict(item.valuation.metrics)
        _fill_revision_metric(metrics, prior.metrics, "next_fy_revenue", "fy1_revenue_revision_30d")
        _fill_revision_metric(metrics, prior.metrics, "next_q_revenue", "next_q_revenue_revision_30d")
        result.append(replace(item, valuation=replace(item.valuation, metrics=metrics)))
    return result


def _fill_revision_metric(
    metrics: dict[str, object],
    prior_metrics: dict[str, object],
    source_key: str,
    revision_key: str,
) -> None:
    if metrics.get(revision_key) is not None:
        return
    current = metrics.get(source_key)
    prior = prior_metrics.get(source_key)
    if not isinstance(current, (int, float)) or not isinstance(prior, (int, float)):
        return
    if current != current or prior != prior or prior == 0:
        return
    metrics[revision_key] = round((float(current) - float(prior)) / abs(float(prior)) * 100.0, 2)


def _has_usable_valuation(metrics: dict[str, object]) -> bool:
    return any(value is not None for value in metrics.values())


def _fetch_one_ticker(
    ticker: TickerConfig,
    *,
    news_provider: GoogleNewsRssProvider,
    signals: list[XSignal],
    fetch_news: bool,
    fetch_valuation: bool,
    lookback_days: int,
    max_articles: int,
) -> TickerReport:
    warnings: list[str] = []
    articles = []
    valuation = None
    earnings = None

    if fetch_news:
        articles, news_warnings = news_provider.fetch_for_ticker(
            ticker,
            lookback_days=lookback_days,
            max_articles=max_articles,
        )
        warnings.extend(news_warnings)

    if fetch_valuation:
        try:
            valuation = fetch_yfinance_valuation(ticker)
        except Exception as exc:
            warnings.append(f"Valuation fetch failed: {exc}")

        try:
            earnings = fetch_yfinance_earnings_date(ticker)
        except Exception as exc:
            warnings.append(f"Earnings date fetch failed: {exc}")

    return TickerReport(
        ticker=ticker,
        articles=articles,
        x_signals=signals,
        valuation=valuation,
        earnings=earnings,
        warnings=warnings,
    )
