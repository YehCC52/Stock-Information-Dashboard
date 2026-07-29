from __future__ import annotations

import logging
import sys
import time
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
from .models import DailyReport, TickerConfig, TickerReport, TickerResearchState, XSignal
from .news import GoogleNewsRssProvider
from .notify import build_daily_summary, build_telegram_notifier
from .premarket import fetch_overnight_premarket
from .taiwan_market import TaiwanMarketDataProvider
from .report import (
    derive_portfolio_weights,
    holding_currencies,
    report_output_dir,
    right_side_check,
    right_side_execution_plan,
    score_history_snapshot,
    write_report,
)
from .storage import (
    export_research_state_file,
    import_research_state_file,
    init_db,
    load_fresh_valuation_snapshot,
    load_latest_valuation_snapshot,
    load_next_earnings_date,
    load_post_earnings_reviews,
    load_report_dates,
    load_fresh_taiwan_market_overview,
    load_latest_taiwan_market_overview,
    load_ticker_history,
    load_ticker_research_states,
    load_trade_journal_entries,
    save_report,
    save_report_run,
)
from .valuation import (
    TECHNICAL_HISTORY_VERSION,
    fetch_yfinance_earnings_date,
    fetch_yfinance_valuation,
)
from .x_signals import load_manual_x_signals


logger = logging.getLogger(__name__)

DEFAULT_FETCH_WORKERS = 6
VALUATION_CACHE_TTL_HOURS = 4
_VALUATION_MAX_RETRIES = 3


def _right_side_history_status(
    check: dict[str, object],
    execution: dict[str, object] | None,
) -> str:
    """Persist only fully executable setups as ready validation signals."""
    check_status = str(check.get("status", ""))
    if not execution:
        return check_status
    execution_status = str(execution.get("status", ""))
    if execution_status == "ready":
        return "Right-side ready"
    if check_status == "Right-side ready":
        return "Execution blocked" if execution_status == "blocked" else "Execution watch"
    return check_status


def run_daily(
    config_path: str | Path,
    report_date: date | None = None,
    output_dir: str | Path = "reports",
    db_path: str | Path = "data/stock_daily.sqlite3",
    fetch_news: bool = True,
    fetch_valuation: bool = True,
    fetch_macro: bool = True,
    fetch_taiwan_data: bool = True,
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
    if not fetch_taiwan_data:
        global_warnings.append("Taiwan revenue, institutional-flow, and market-margin data fetching skipped by --no-taiwan-data.")

    market_sentiment = None
    market_context = None
    premarket = None
    taiwan_market_overview = None
    if fetch_valuation:
        try:
            market_sentiment = fetch_market_sentiment()
            global_warnings.extend(market_sentiment.warnings)
        except Exception as exc:
            logger.warning("Market sentiment fetch failed", exc_info=True)
            global_warnings.append(f"Market sentiment fetch failed: {exc}")
        try:
            market_context = fetch_market_context()
            global_warnings.extend(market_context.warnings)
        except Exception as exc:
            logger.warning("Market context fetch failed", exc_info=True)
            global_warnings.append(f"Market context fetch failed: {exc}")
        try:
            premarket = fetch_overnight_premarket(config.tickers, max_workers=max(1, max_workers))
            global_warnings.extend(premarket.warnings)
        except Exception as exc:
            logger.warning("Premarket snapshot fetch failed", exc_info=True)
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
        research_states = _apply_plan_defaults(research_states, config.tickers)
        tickers = _apply_position_overrides(config.tickers, research_states)
        post_earnings_reviews = load_post_earnings_reviews(conn, ticker_symbols)
        trade_journal = load_trade_journal_entries(conn, ticker_symbols)
        if len(holding_currencies(tickers)) > 1:
            global_warnings.append("Mixed-currency holdings detected; combined unrealized P/L is intentionally hidden.")

        news_provider = GoogleNewsRssProvider()
        manual_x_signals = load_manual_x_signals(config.settings.x_signals.manual_file, tickers)
        signals_by_ticker: dict[str, list[XSignal]] = defaultdict(list)
        for signal in manual_x_signals:
            signals_by_ticker[signal.ticker].append(signal)

        prefetched_valuations: dict[str, object] = {}
        if fetch_valuation:
            for tc in tickers:
                cached = load_fresh_valuation_snapshot(
                    conn, tc.symbol, max_age_hours=VALUATION_CACHE_TTL_HOURS
                )
                if (
                    cached is not None
                    and cached.metrics.get("technical_history_version") == TECHNICAL_HISTORY_VERSION
                    and "analyst_target_median" in cached.metrics
                    and isinstance(cached.metrics.get("chart_close_60"), list)
                    and len(cached.metrics["chart_close_60"]) >= 2
                ):
                    prefetched_valuations[tc.symbol] = cached

        ticker_reports = _fetch_all_tickers(
            tickers,
            news_provider=news_provider,
            signals_by_ticker=signals_by_ticker,
            fetch_news=fetch_news,
            fetch_valuation=fetch_valuation,
            lookback_days=config.settings.news.lookback_days,
            max_articles=config.settings.news.max_articles_per_ticker,
            max_workers=max(1, max_workers),
            progress=progress,
            prefetched_valuations=prefetched_valuations,
        )
        if fetch_taiwan_data:
            has_taiwan_tickers = any(ticker.market in {"twse", "tpex"} for ticker in tickers)
            fresh_taiwan_overview = (
                load_fresh_taiwan_market_overview(
                    conn,
                    before_or_on=actual_report_date,
                    max_age_hours=VALUATION_CACHE_TTL_HOURS,
                )
                if has_taiwan_tickers
                else None
            )
            taiwan_market_overview = fresh_taiwan_overview
            try:
                taiwan_result = TaiwanMarketDataProvider(
                    include_market_overview=fresh_taiwan_overview is None
                ).fetch(tickers, actual_report_date)
                global_warnings.extend(taiwan_result.warnings)
                taiwan_market_overview = taiwan_result.overview or fresh_taiwan_overview
                ticker_reports = [
                    replace(item, taiwan_market=taiwan_result.snapshots.get(item.ticker.symbol))
                    for item in ticker_reports
                ]
            except Exception as exc:
                logger.warning("Taiwan market data fetch failed", exc_info=True)
                global_warnings.append(f"Taiwan market data fetch failed: {exc}")
            if has_taiwan_tickers and taiwan_market_overview is None:
                fallback_overview = load_latest_taiwan_market_overview(
                    conn,
                    before_or_on=actual_report_date,
                )
                if fallback_overview is not None:
                    taiwan_market_overview = fallback_overview
                    global_warnings.append(
                        "Taiwan margin maintenance fallback used from "
                        f"{fallback_overview.as_of_date.isoformat()}."
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
            ticker_reports = _apply_earnings_fallbacks(conn, ticker_reports, actual_report_date)

        report_path = report_output_dir(output_dir, actual_report_date) / f"{actual_report_date.isoformat()}.html"
        preliminary_report = DailyReport(
            report_date=actual_report_date,
            generated_at=generated_at,
            ticker_reports=ticker_reports,
            warnings=list(global_warnings),
            economic_events=economic_events,
            market_sentiment=market_sentiment,
            market_context=market_context,
            premarket=premarket,
            taiwan_market_overview=taiwan_market_overview,
            research_states=research_states,
            post_earnings_reviews=post_earnings_reviews,
            trade_journal=trade_journal,
            settings=config.settings,
        )
        benchmarks = market_context.benchmark_returns if market_context else {}
        right_side_signals: dict[str, dict[str, object]] = {}
        score_snapshots: dict[str, dict[str, object]] = {}
        for item in ticker_reports:
            score_snapshots[item.ticker.symbol] = score_history_snapshot(
                item,
                actual_report_date,
                benchmarks,
            )
            check = right_side_check(
                item,
                benchmarks=benchmarks,
                portfolio=config.settings.portfolio,
            )
            if check is None:
                continue
            signal = dict(check)
            execution = right_side_execution_plan(preliminary_report, item)
            if execution:
                signal.update({
                    "status": _right_side_history_status(check, execution),
                    "entry_reference": execution.get("entry_reference"),
                    "invalidation": execution.get("invalidation"),
                    "risk_pct": execution.get("risk_pct"),
                })
            right_side_signals[item.ticker.symbol] = signal
        save_report(conn, preliminary_report)
        save_report_run(
            conn,
            preliminary_report,
            html_path=report_path,
            right_side_signals=right_side_signals,
            score_snapshots=score_snapshots,
        )
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
            logger.warning("Telegram notification failed", exc_info=True)
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
        taiwan_market_overview=taiwan_market_overview,
        research_states=research_states,
        post_earnings_reviews=post_earnings_reviews,
        trade_journal=trade_journal,
        ticker_history=ticker_history,
        history_overview=history_overview,
        settings=config.settings,
    )
    report = derive_portfolio_weights(report)
    write_report(report, output_dir)
    return report


def _apply_plan_defaults(
    research_states: dict[str, TickerResearchState],
    tickers: list[TickerConfig],
) -> dict[str, TickerResearchState]:
    """Fill research fields from YAML defaults; a non-empty DB value always wins.

    YAML `research:` and `plan:` are the baseline review state/playbook; the DB
    row (edited in the UI and round-tripped via export/import) overrides it
    field-by-field. An empty DB field falls back to YAML so a freshly-seeded
    ticker shows its thesis and plan.
    """
    merged = dict(research_states)
    for ticker in tickers:
        plan = ticker.plan
        research = ticker.research
        if plan.is_empty and research.is_empty:
            continue
        symbol = ticker.symbol
        state = merged.get(symbol) or TickerResearchState(ticker=symbol)
        merged[symbol] = replace(
            state,
            tag=state.tag or research.tag,
            thesis_state=state.thesis_state or research.thesis_state,
            thesis_trigger=state.thesis_trigger or research.thesis_trigger,
            thesis_text=state.thesis_text or research.thesis_text,
            note=state.note or research.note,
            revisit_date=state.revisit_date or research.revisit_date,
            review_status=state.review_status if state.review_status != "not-reviewed" else (research.review_status or state.review_status),
            bull_case=state.bull_case or plan.bull_case,
            bear_case=state.bear_case or plan.bear_case,
            entry_plan=state.entry_plan or plan.entry_plan,
            add_zone=state.add_zone or plan.add_zone,
            reduce_zone=state.reduce_zone or plan.reduce_zone,
            stop_loss=state.stop_loss or plan.stop_loss,
        )
    return merged


def _apply_position_overrides(
    tickers: list[TickerConfig],
    research_states: dict[str, TickerResearchState],
) -> list[TickerConfig]:
    result: list[TickerConfig] = []
    for ticker in tickers:
        state = research_states.get(ticker.symbol)
        override = state.position if state else None
        if override is None:
            result.append(ticker)
            continue
        base = ticker.position
        result.append(
            replace(
                ticker,
                position=replace(
                    base,
                    status=override.status or base.status,
                    shares=override.shares if override.shares is not None else base.shares,
                    avg_cost=override.avg_cost if override.avg_cost is not None else base.avg_cost,
                    portfolio_weight=(
                        override.portfolio_weight
                        if override.portfolio_weight is not None
                        else base.portfolio_weight
                    ),
                    position_size=(
                        override.position_size
                        if override.position_size is not None
                        else base.position_size
                    ),
                    stop_loss=override.stop_loss if override.stop_loss is not None else base.stop_loss,
                    sector=override.sector or base.sector,
                ),
            )
        )
    return result


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
    prefetched_valuations: dict[str, object] | None = None,
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
            cached_valuation=(prefetched_valuations or {}).get(ticker.symbol),
        )

    results: dict[str, TickerReport] = {}
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(worker, ticker): ticker for ticker in tickers}
        for future in as_completed(futures):
            ticker = futures[future]
            try:
                results[ticker.symbol] = future.result()
            except Exception as exc:
                logger.warning("Worker crashed for %s", ticker.symbol, exc_info=True)
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


def _apply_earnings_fallbacks(
    conn: sqlite3.Connection,
    ticker_reports: list[TickerReport],
    report_date: date,
) -> list[TickerReport]:
    """Backfill a known earnings date from prior runs when the live fetch is empty."""
    result: list[TickerReport] = []
    for item in ticker_reports:
        if item.earnings is not None and item.earnings.earnings_date is not None:
            result.append(item)
            continue
        fallback = load_next_earnings_date(conn, item.ticker.symbol, on_or_after=report_date)
        if fallback is None:
            result.append(item)
            continue
        result.append(replace(item, earnings=fallback))
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
    return metrics.get("last_close") is not None


def _fetch_one_ticker(
    ticker: TickerConfig,
    *,
    news_provider: GoogleNewsRssProvider,
    signals: list[XSignal],
    fetch_news: bool,
    fetch_valuation: bool,
    lookback_days: int,
    max_articles: int,
    cached_valuation: object = None,
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
        if cached_valuation is not None:
            valuation = cached_valuation
        else:
            last_exc: Exception | None = None
            for attempt in range(_VALUATION_MAX_RETRIES + 1):
                try:
                    valuation = fetch_yfinance_valuation(ticker)
                    last_exc = None
                    break
                except Exception as exc:
                    last_exc = exc
                    if attempt < _VALUATION_MAX_RETRIES:
                        time.sleep(2 ** attempt)
            if last_exc is not None:
                logger.warning(
                    "Valuation fetch failed for %s after %d attempts",
                    ticker.symbol,
                    _VALUATION_MAX_RETRIES + 1,
                    exc_info=True,
                )
                warnings.append(
                    f"Valuation fetch failed after {_VALUATION_MAX_RETRIES + 1} attempts: {last_exc}"
                )

        if ticker.has_earnings:
            try:
                earnings = fetch_yfinance_earnings_date(ticker)
            except Exception as exc:
                logger.warning("Earnings date fetch failed for %s", ticker.symbol, exc_info=True)
                warnings.append(f"Earnings date fetch failed: {exc}")

    return TickerReport(
        ticker=ticker,
        articles=articles,
        x_signals=signals,
        valuation=valuation,
        earnings=earnings,
        warnings=warnings,
    )
