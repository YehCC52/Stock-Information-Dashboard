from __future__ import annotations

import re
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from math import isfinite
from pathlib import Path
from statistics import median
from zoneinfo import ZoneInfo

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .data_quality import confidence as data_quality_confidence
from .models import TradeFill, TradeJournalEntry
from .models import DailyReport, MARKET_LABELS, MarketContext, NewsArticle, PositionConfig, PortfolioSettings, PostEarningsReview, TickerHistoryPoint, TickerReport, TickerResearchState
from .news import EVENT_LABELS, normalize_title
from .valuation import format_metric_value


DEFAULT_MAX_SINGLE_WEIGHT = 15.0  # single-name weight % above which My Book flags concentration

METRIC_LABELS = {
    "last_close": "Last Close",
    "previous_close": "Prev Close",
    "daily_change": "Daily %",
    "rsi_14": "RSI 14",
    "fifty_two_week_high": "52W High",
    "fifty_two_week_low": "52W Low",
    "from_52w_high": "From High",
    "sma_5": "SMA 5D",
    "sma_20": "SMA 20D",
    "sma_60": "SMA 60D",
    "sma_120": "SMA 120D",
    "volume_vs_20d": "Volume / 20D",
    "atr_20": "ATR 20D",
    "atr_20_percent": "ATR %",
    "move_vs_atr": "Move / ATR",
    "gap_percent": "Gap %",
    "market_cap": "Market Cap",
    "enterprise_value": "Enterprise Value",
    "trailing_pe": "Trailing P/E",
    "forward_pe": "Forward P/E",
    "ttm_eps": "TTM EPS",
    "forward_eps": "Forward EPS",
    "next_fy_eps": "Next FY EPS",
    "eps_growth_pct": "EPS Growth",
    "fy1_eps_revision_30d": "FY1 EPS Rev 30D",
    "next_q_revenue": "Next Q Revenue",
    "next_q_revenue_growth_pct": "Next Q Rev Growth",
    "next_fy_revenue": "Next FY Revenue",
    "revenue_growth_pct": "Revenue Growth",
    "fy1_revenue_revision_30d": "FY1 Revenue Rev 30D",
    "next_q_revenue_revision_30d": "Next Q Revenue Rev 30D",
    "latest_eps_surprise_pct": "Latest EPS Surprise",
    "latest_revenue_surprise_pct": "Latest Revenue Surprise",
    "peg_ratio": "PEG Ratio",
    "price_to_sales": "Price/Sales",
    "price_to_book": "Price/Book",
    "ev_to_revenue": "Enterprise Value/Revenue",
    "ev_to_ebitda": "Enterprise Value/EBITDA",
    "sector": "Sector",
    "industry": "Industry",
}

HTML_METRIC_LABELS = {
    "last_close": "收盤價",
    "previous_close": "前收",
    "daily_change": "日漲跌",
    "rsi_14": "RSI 14",
    "fifty_two_week_high": "52週高",
    "fifty_two_week_low": "52週低",
    "from_52w_high": "距高點",
    "sma_5": "SMA 5D",
    "sma_20": "SMA 20D",
    "sma_60": "SMA 60D",
    "sma_120": "SMA 120D",
    "volume_vs_20d": "成交量 / 20D",
    "atr_20": "ATR 20D",
    "atr_20_percent": "ATR %",
    "move_vs_atr": "波動 / ATR",
    "gap_percent": "缺口 %",
    "market_cap": "市值",
    "enterprise_value": "企業價值",
    "trailing_pe": "過去12月 P/E",
    "forward_pe": "預估 P/E",
    "ttm_eps": "TTM EPS",
    "forward_eps": "預估 EPS",
    "next_fy_eps": "下一財年 EPS",
    "eps_growth_pct": "EPS 成長",
    "fy1_eps_revision_30d": "FY1 EPS 修正 30D",
    "next_q_revenue": "下季營收",
    "next_q_revenue_growth_pct": "下季營收成長",
    "next_fy_revenue": "下一財年營收",
    "revenue_growth_pct": "營收成長",
    "fy1_revenue_revision_30d": "FY1 營收修正 30D",
    "next_q_revenue_revision_30d": "下季營收修正 30D",
    "latest_eps_surprise_pct": "最近 EPS 驚喜",
    "latest_revenue_surprise_pct": "最近營收驚喜",
    "peg_ratio": "PEG",
    "price_to_sales": "P/S",
    "price_to_book": "P/B",
    "ev_to_revenue": "EV/營收",
    "ev_to_ebitda": "EV/EBITDA",
    "sector": "產業",
    "industry": "細分產業",
}

EVENT_LABELS_ZH = {
    "earnings": "財報",
    "guidance": "展望",
    "ai": "AI",
    "deal": "交易",
    "regulation": "監管",
    "lawsuit": "訴訟",
    "antitrust": "反壟斷",
    "supply": "供應鏈",
    "product": "產品",
    "analyst": "分析師",
    "analyst_call": "分析師",
    "management": "管理層",
    "macro": "總經",
    "market": "市場",
    "other": "其他",
}

SOURCE_RELIABILITY_LABELS_ZH = {
    "official/company": "官方/公司",
    "tier 1 media": "一線媒體",
    "commentary": "評論",
    "trusted media": "可信媒體",
}

LEVEL_LABELS_ZH = {
    "high": "高",
    "medium": "中",
    "low": "低",
    "info": "資訊",
}


@dataclass(frozen=True)
class ReportPaths:
    markdown: Path
    html: Path
    brief: Path


def report_output_dir(output_dir: str | Path, report_date: date) -> Path:
    """Return the year/month archive directory for a daily report."""
    return Path(output_dir) / f"{report_date.year:04d}" / f"{report_date.month:02d}"


def _build_environment(template_dir: str | Path | None = None, *, autoescape_html: bool = False) -> Environment:
    template_path = Path(template_dir) if template_dir else Path(__file__).parent / "templates"
    env = Environment(
        loader=FileSystemLoader(template_path),
        autoescape=select_autoescape(["html", "xml"]) if autoescape_html else select_autoescape(enabled_extensions=()),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.filters["metric_label"] = lambda value: METRIC_LABELS.get(value, value)
    env.filters["metric_value"] = format_metric_value
    env.filters["date_or_na"] = date_or_na
    env.filters["twn_timestamp"] = format_twn_timestamp
    env.filters["twn_datetime"] = format_twn_datetime
    env.filters["utc_timestamp"] = format_utc_timestamp
    env.filters["et_timestamp"] = format_et_timestamp
    return env


def render_markdown_report(report: DailyReport, template_dir: str | Path | None = None) -> str:
    env = _build_environment(template_dir)
    template = env.get_template("daily_report.md.j2")
    return template.render(report=report, metric_labels=METRIC_LABELS)


def render_html_report(report: DailyReport, template_dir: str | Path | None = None) -> str:
    env = _build_environment(template_dir, autoescape_html=True)
    env.filters["pe_class"] = pe_class
    env.filters["earnings_urgency"] = lambda value: earnings_urgency(value, report.report_date)
    env.filters["earnings_urgency_label"] = lambda value: earnings_urgency_label(value, report.report_date)
    env.filters["days_until"] = lambda value: days_until(value, report.report_date)
    env.filters["earnings_delta"] = lambda item: earnings_delta(item, report.report_date)
    env.filters["zh_text"] = zh_text
    env.filters["position_status_label"] = position_status_label
    env.filters["review_status_label"] = review_status_label
    env.filters["card_state_label"] = card_state_label
    env.filters["ticker_anchor"] = lambda symbol: f"ticker-{symbol.lower()}"
    env.filters["event_label"] = event_label
    env.filters["event_label_zh"] = event_label_zh
    env.filters["html_metric_label"] = html_metric_label
    env.filters["source_reliability_label"] = source_reliability_label
    env.filters["level_label"] = level_label
    env.filters["market_label"] = market_label
    env.filters["news_rationale"] = news_rationale
    env.filters["book_label_zh"] = _daily_summary_book_label
    env.filters["decision_text_zh"] = _daily_summary_reasons
    env.globals["news_triage_label"] = lambda item, article: news_triage_label(item, article, report.report_date)
    from .market_context import market_regime, rates_interpretation
    env.filters["rates_interpretation"] = rates_interpretation
    env.filters["market_regime"] = lambda rpt: market_regime(
        rpt.market_context,
        rpt.market_sentiment.score if rpt.market_sentiment else None,
    )
    env.filters["post_earnings"] = lambda item: post_earnings_status(item, report.report_date)
    benchmarks = {}
    if report.market_context and report.market_context.benchmark_returns:
        benchmarks = report.market_context.benchmark_returns
    portfolio_settings = report.settings.portfolio if report.settings else None
    env.filters["ticker_insights"] = lambda item: ticker_insights(item, report.report_date, benchmarks=benchmarks, portfolio=portfolio_settings)
    env.filters["stock_health"] = lambda item: stock_health_diagnostic(item, report.report_date, benchmarks)
    env.filters["right_side_score"] = lambda item: right_side_score(item, benchmarks)
    env.filters["execution_plan"] = lambda item: right_side_execution_plan(report, item)
    env.filters["price_structure_chart"] = price_structure_chart
    env.filters["card_state"] = lambda item: card_state(item, report.report_date)
    env.filters["topic_tags"] = topic_tags
    env.filters["metric_raw"] = metric_raw
    env.filters["has_risk_signal"] = lambda item: has_risk_signal(item, report.report_date)
    env.filters["valuation_risk"] = valuation_risk_label
    env.filters["top_news_count"] = top_news_count
    env.filters["top_news_signatures"] = top_news_signatures
    env.filters["daily_change"] = daily_change_pct
    env.filters["from_52w_high"] = from_52w_high_pct
    env.filters["from_52w_low"] = from_52w_low_pct
    env.filters["ticker_cluster"] = ticker_cluster
    env.filters["premarket_change"] = lambda item: premarket_change_pct(report, item.ticker.symbol)
    env.filters["position_view"] = position_view
    env.filters["eps_revision_class"] = eps_revision_class
    env.filters["source_reliability"] = source_reliability
    env.filters["post_earnings_defaults"] = lambda item: post_earnings_defaults(report, item)
    env.filters["pre_earnings_card"] = lambda item: pre_earnings_card(report, item)
    env.filters["data_quality"] = lambda item: data_quality_confidence(
        item,
        report.report_date,
        premarket_move=premarket_move_for(report, item.ticker.symbol),
    )
    env.filters["format_pct"] = format_pct
    env.filters["format_tw_shares"] = format_tw_shares
    env.filters["format_tw_revenue"] = format_tw_revenue
    env.filters["change_class"] = change_class
    env.filters["format_ratio"] = format_ratio
    env.filters["rsi_class"] = rsi_class
    env.filters["rsi_label"] = rsi_label
    env.filters["research_state"] = lambda item: research_state_for(report, item.ticker.symbol)
    env.filters["history_points"] = lambda item: report.ticker_history.get(item.ticker.symbol, [])
    env.globals["ticker_delta"] = lambda symbol: ticker_delta(report, symbol)
    env.globals["ticker_sparkline"] = lambda symbol: ticker_sparkline(report, symbol)
    plan_triggers_by_symbol: dict[str, list[dict[str, object]]] = {}
    for trigger in plan_triggers(report):
        plan_triggers_by_symbol.setdefault(str(trigger["ticker"]), []).append(trigger)
    env.globals["plan_triggers_for"] = lambda symbol: plan_triggers_by_symbol.get(symbol, [])
    template = env.get_template("daily_report.html.j2")
    map_markets = sector_map_markets(report)
    return template.render(
        report=report,
        metric_labels=METRIC_LABELS,
        summary=build_summary(report),
        history=history_sections(report),
        research_payload=research_payload(report),
        earnings_soon=earnings_soon(report),
        important_news=important_news(report),
        news_clusters=event_clusters(report),
        hero=morning_briefing_cards(report),
        daily_summary=daily_summary(report),
        strategy_screener=strategy_screener(report),
        right_side_validation=right_side_signal_validation(report),
        trade_journal=trade_journal_summary(report),
        morning_actions=morning_actions(report),
        todays_catalysts=todays_catalysts(report),
        post_earnings_items=post_earnings_items(report),
        macro_risk=macro_risk_meter(report.market_context),
        todays_focus=todays_focus(report),
        capital_allocation=capital_allocation_queue(report),
        book_today=book_today_summary(report),
        book_impact=book_impact_ranking(report),
        sector_map_markets=map_markets,
        premarket_triage=premarket_triage(report),
        priority_items=priority_items(report),
        rule_alerts=rule_alerts(report),
        valuation_rows=sorted(report.ticker_reports, key=lambda item: item.ticker.symbol),
        ticker_cards=sort_by_market_cap(report.ticker_reports),
        sectors=sectors_in_use(report),
        overextended=overextended_tickers(report),
        data_quality=data_quality_overview(report),
        portfolio=portfolio_impact_summary(report),
        portfolio_risk=portfolio_risk_overview(report),
        related_tickers=related_ticker_links(report),
        clusters=clusters_in_use(report),
        valuation_keys=[
            "last_close",
            "rsi_14",
            "volume_vs_20d",
            "gap_percent",
            "atr_20_percent",
            "market_cap",
            "trailing_pe",
            "forward_pe",
            "ttm_eps",
            "next_fy_eps",
            "eps_growth_pct",
            "fy1_eps_revision_30d",
            "fy1_revenue_revision_30d",
            "next_q_revenue_revision_30d",
            "revenue_growth_pct",
            "peg_ratio",
            "price_to_sales",
            "price_to_book",
            "ev_to_ebitda",
        ],
    )


def write_report(report: DailyReport, output_dir: str | Path) -> ReportPaths:
    output_path = report_output_dir(output_dir, report.report_date)
    output_path.mkdir(parents=True, exist_ok=True)
    markdown_path = output_path / f"{report.report_date.isoformat()}.md"
    html_path = output_path / f"{report.report_date.isoformat()}.html"
    brief_path = output_path / f"{report.report_date.isoformat()}-brief.txt"
    markdown_path.write_text(_strip_bom(render_markdown_report(report)), encoding="utf-8")
    html_path.write_text(_strip_bom(render_html_report(report)), encoding="utf-8")
    brief_path.write_text(portfolio_brief(report), encoding="utf-8")
    return ReportPaths(markdown=markdown_path, html=html_path, brief=brief_path)


def _strip_bom(text: str) -> str:
    """Drop a leading UTF-8 BOM (U+FEFF) if a Windows editor saved a template
    with one. The BOM otherwise leaks into every rendered report and shows up
    as an invisible character / parsing glitch in browsers."""
    return text[1:] if text.startswith("\ufeff") else text


def build_summary(report: DailyReport) -> dict[str, int]:
    ticker_count = len(report.ticker_reports)
    tickers_with_news = sum(1 for item in report.ticker_reports if item.articles)
    tickers_with_warnings = sum(1 for item in report.ticker_reports if item.warnings)
    earnings_soon_count = len(earnings_soon(report))
    hot_count = sum(
        1 for item in report.ticker_reports if card_state(item, report.report_date) == "hot"
    )
    rsi_overbought_count = sum(
        1 for item in report.ticker_reports
        if (rsi := rsi_value(item)) is not None and rsi >= 70
    )
    rsi_oversold_count = sum(
        1 for item in report.ticker_reports
        if (rsi := rsi_value(item)) is not None and rsi <= 30
    )
    premarket_gap_count = len(report.premarket.gap_movers) if report.premarket else 0
    reviewed_count = sum(
        1
        for state in report.research_states.values()
        if state.review_status == "reviewed"
    )
    market_counts: dict[str, int] = {}
    for item in report.ticker_reports:
        market_counts[item.ticker.market] = market_counts.get(item.ticker.market, 0) + 1
    return {
        "ticker_count": ticker_count,
        "tickers_with_news": tickers_with_news,
        "tickers_with_warnings": tickers_with_warnings,
        "earnings_soon_count": earnings_soon_count,
        "premarket_gap_count": premarket_gap_count,
        "hot_count": hot_count,
        "global_warning_count": len(report.warnings),
        "economic_event_count": len(report.economic_events),
        "rsi_overbought_count": rsi_overbought_count,
        "rsi_oversold_count": rsi_oversold_count,
        "reviewed_count": reviewed_count,
        "market_counts": market_counts,
    }


def market_label(value: str) -> str:
    return MARKET_LABELS.get(value, value.upper())


def format_tw_shares(value: object) -> str:
    """Format Taiwan market flow in shares, with a compact Chinese unit."""
    if not isinstance(value, (int, float)) or not isfinite(float(value)):
        return "N/A"
    number = float(value)
    sign = "+" if number > 0 else ""
    magnitude = abs(number)
    if magnitude >= 100_000_000:
        return f"{sign}{number / 100_000_000:.2f}\u5104\u80a1"
    if magnitude >= 10_000:
        return f"{sign}{number / 10_000:.1f}\u842c\u80a1"
    return f"{sign}{number:,.0f}\u80a1"


def format_tw_revenue(value: object) -> str:
    """Format TWSE monthly revenue, which is disclosed in thousands of TWD."""
    if not isinstance(value, (int, float)) or not isfinite(float(value)):
        return "N/A"
    amount_twd = float(value) * 1_000
    yi = chr(0x5104)
    yuan = chr(0x5143)
    if abs(amount_twd) >= 100_000_000:
        return f"{amount_twd / 100_000_000:,.1f}{yi}{yuan}"
    if abs(amount_twd) >= 10_000:
        return f"{amount_twd / 10_000:,.1f}{chr(0x842c)}{yuan}"
    return f"{amount_twd:,.0f}{yuan}"

def related_ticker_links(report: DailyReport) -> dict[str, list[dict[str, str]]]:
    """Return explicit cross-market ticker links that exist in this report."""
    by_symbol = {item.ticker.symbol: item for item in report.ticker_reports}
    result: dict[str, list[dict[str, str]]] = {}
    for item in report.ticker_reports:
        links: list[dict[str, str]] = []
        for symbol in item.ticker.related_symbols:
            related = by_symbol.get(symbol.upper())
            if related is None or related.ticker.symbol == item.ticker.symbol:
                continue
            links.append({
                "symbol": related.ticker.symbol,
                "display_symbol": related.ticker.display_symbol,
                "market": market_label(related.ticker.market),
            })
        if links:
            result[item.ticker.symbol] = links
    return result


def research_state_for(report: DailyReport, symbol: str) -> TickerResearchState:
    return report.research_states.get(symbol, TickerResearchState(ticker=symbol))


def post_earnings_review_for(report: DailyReport, symbol: str) -> PostEarningsReview | None:
    return report.post_earnings_reviews.get(symbol)


def research_payload(report: DailyReport) -> dict[str, object]:
    states: dict[str, object] = {}
    for item in report.ticker_reports:
        state = research_state_for(report, item.ticker.symbol)
        review = post_earnings_review_for(report, item.ticker.symbol)
        states[item.ticker.symbol] = {
            "tag": state.tag,
            "thesis_state": state.thesis_state,
            "thesis_trigger": state.thesis_trigger,
            "thesis_text": state.thesis_text,
            "note": state.note,
            "checklist": list(state.checklist),
            "revisit_date": state.revisit_date.isoformat() if state.revisit_date else "",
            "pinned": state.pinned,
            "review_status": state.review_status,
            "last_reviewed_at": state.last_reviewed_at.isoformat() if state.last_reviewed_at else "",
            "bull_case": state.bull_case,
            "bear_case": state.bear_case,
            "entry_plan": state.entry_plan,
            "add_zone": state.add_zone,
            "reduce_zone": state.reduce_zone,
            "stop_loss": state.stop_loss,
            "earnings_questions": list(state.earnings_questions),
            "position": position_payload(item.ticker.position),
            "post_earnings_review": {
                "earnings_date": review.earnings_date.isoformat() if review and review.earnings_date else "",
                "eps": review.eps if review else "",
                "revenue": review.revenue if review else "",
                "guide": review.guide if review else "",
                "eps_surprise_pct": review.eps_surprise_pct if review else None,
                "revenue_surprise_pct": review.revenue_surprise_pct if review else None,
                "fy1_eps_revision_after": review.fy1_eps_revision_after if review else None,
                "fy1_revenue_revision_after": review.fy1_revenue_revision_after if review else None,
                "conclusion": review.conclusion if review else "",
                "next_step": review.next_step if review else "",
                "gross_margin_change": review.gross_margin_change if review else "",
                "management_keywords": review.management_keywords if review else "",
                "thesis_changed": review.thesis_changed if review else "",
            },
        }
    trades = [
        {
            "trade_id": trade.trade_id,
            "ticker": trade.ticker,
            "market": trade.market,
            "currency": trade.currency,
            "status": trade.status,
            "entry_date": trade.entry_date.isoformat() if trade.entry_date else "",
            "entry_price": trade.entry_price,
            "shares": trade.shares,
            "current_stop": trade.current_stop,
            "initial_risk": trade.initial_risk,
            "initial_stop": trade.initial_stop,
            "exit_date": trade.exit_date.isoformat() if trade.exit_date else "",
            "exit_price": trade.exit_price,
            "fees": trade.fees,
            "fx_rate_to_base": trade.fx_rate_to_base,
            "fills": [
                {
                    "fill_id": fill.fill_id,
                    "side": fill.side,
                    "fill_date": fill.fill_date.isoformat() if fill.fill_date else "",
                    "price": fill.price,
                    "shares": fill.shares,
                    "fees": fill.fees,
                    "note": fill.note,
                }
                for fill in trade.fills
            ],
            "setup": trade.setup,
            "note": trade.note,
            "updated_at": trade.updated_at.isoformat() if trade.updated_at else "",
        }
        for trade in report.trade_journal
    ]
    return {
        "tickers": states,
        "trades": trades,
        "history_days": int(report.history_overview.get("history_days", 30)) if report.history_overview else 30,
        "archive_dates": list(report.history_overview.get("archive_dates", [])) if report.history_overview else [],
    }


def position_payload(position: PositionConfig) -> dict[str, object]:
    return {
        "status": position.status,
        "shares": position.shares,
        "avg_cost": position.avg_cost,
        "portfolio_weight": position.portfolio_weight,
        "position_size": position.position_size,
        "stop_loss": position.stop_loss,
        "sector": position.sector,
    }


def history_sections(report: DailyReport) -> dict[str, object]:
    sections = dict(report.history_overview)
    sections.setdefault("history_days", 30)
    sections["changes_since_last_run"] = changes_since_last_run(report)
    sections["changes_30d"] = changes_in_window(report, days=30)
    sections["review_queue"] = research_review_queue(report)
    sections["recent_thesis_changes"] = recent_thesis_changes(report)
    sections["post_earnings_due"] = post_earnings_due(report)
    sections["research_drift"] = research_drift(report)
    return sections


def earnings_soon(report: DailyReport, days: int = 7) -> list[TickerReport]:
    result: list[TickerReport] = []
    for item in report.ticker_reports:
        if not item.earnings or not item.earnings.earnings_date:
            continue
        days_until = (item.earnings.earnings_date - report.report_date).days
        if 0 <= days_until <= days:
            result.append(item)
    return sorted(result, key=lambda item: item.earnings.earnings_date if item.earnings else date.max)


def important_news(report: DailyReport, limit: int = 12) -> list[tuple[TickerReport, object, str]]:
    """Return curated (ticker_report, article, tier) triples ranked by importance.

    Globally dedupes by canonical URL and normalized title so the same story
    attributed to multiple tickers (because each ticker's name appears in
    its title) shows up only once, under the strongest attribution.

    The first five are an editorial-style pick list: ranked by importance,
    event type, earnings proximity, and source quality, then lightly diversified
    so one ticker does not consume the entire visible news block.
    """
    candidates = sorted(
        (
            (item, article)
            for item in report.ticker_reports
            for article in item.articles
            if article.importance_score >= 0.8
        ),
        key=lambda pair: _news_editorial_score(pair, report.report_date),
        reverse=True,
    )

    seen_urls: set[str] = set()
    seen_titles: set[str] = set()
    deduped: list[tuple[TickerReport, object]] = []
    for item, article in candidates:
        url_key = article.url.split("?")[0].lower()
        title_key = normalize_title(article.title)
        if url_key in seen_urls or title_key in seen_titles:
            continue
        seen_urls.add(url_key)
        seen_titles.add(title_key)
        deduped.append((item, article))
        if len(deduped) >= limit:
            break

    visible_limit = min(5, limit, len(deduped))
    curated: list[tuple[TickerReport, object]] = []
    deferred: list[tuple[TickerReport, object]] = []
    ticker_counts: dict[str, int] = {}
    for pair in deduped:
        symbol = pair[0].ticker.symbol
        if len(curated) < visible_limit and ticker_counts.get(symbol, 0) < 2:
            curated.append(pair)
            ticker_counts[symbol] = ticker_counts.get(symbol, 0) + 1
        else:
            deferred.append(pair)
    if len(curated) < visible_limit:
        needed = visible_limit - len(curated)
        curated.extend(deferred[:needed])
        deferred = deferred[needed:]

    curated_keys = {(item.ticker.symbol, article.url) for item, article in curated}
    ordered = curated + [
        pair for pair in deduped
        if (pair[0].ticker.symbol, pair[1].url) not in curated_keys
    ]

    triples: list[tuple[TickerReport, object, str]] = []
    for idx, (item, article) in enumerate(ordered[:limit]):
        if idx < 3 and article.importance_score >= 1.0:
            tier = "top"
        elif idx < 8:
            tier = "primary"
        else:
            tier = "minor"
        triples.append((item, article, tier))
    return triples


def _news_editorial_score(pair: tuple[TickerReport, object], anchor: date) -> float:
    item, article = pair
    score = float(getattr(article, "importance_score", 0.0)) * 100
    event_type = str(getattr(article, "event_type", "other"))
    event_boost = {
        "earnings": 18,
        "guidance": 16,
        "regulation": 13,
        "lawsuit": 12,
        "ma": 12,
        "product": 9,
        "analyst_rating": 7,
        "management": 7,
        "macro": 6,
        "market_reaction": 6,
    }.get(event_type, 0)
    score += event_boost

    delta = earnings_delta(item, anchor)
    if delta is not None:
        if delta == 0:
            score += 26
        elif delta == 1:
            score += 20
        elif 0 <= delta <= 7:
            score += 8
        elif -2 <= delta < 0:
            score += 14

    if event_type in ("macro", "market_reaction"):
        score += 8

    source_key = f"{getattr(article, 'domain', '')} {getattr(article, 'source', '')}".lower()
    if any(source in source_key for source in ("reuters", "bloomberg", "wsj", "wall street journal", "financial times", "ft.com", "cnbc")):
        score += 4

    published_at = getattr(article, "published_at", None)
    if published_at and hasattr(published_at, "date"):
        age_days = (anchor - published_at.date()).days
        if age_days >= 0:
            score += max(0, 3 - age_days)
    return score


def news_triage_label(item: TickerReport, article: object, anchor: date) -> str:
    """Explain why a news item is near the top of the morning queue."""
    delta = earnings_delta(item, anchor)
    event_type = str(getattr(article, "event_type", "other"))
    if delta == 0:
        return "today catalyst"
    if delta == 1:
        return "tomorrow catalyst"
    if delta is not None and -2 <= delta < 0:
        return "post-earnings"
    if event_type in ("macro", "market_reaction"):
        return "macro-linked"
    return "watchlist"


# Words that carry no clustering signal — generic finance / filler vocabulary.
# Title tokens in this set are ignored when deciding whether two stories cover
# the same event, so "stock", "shares", "says" don't accidentally bind unrelated
# articles together.
_CLUSTER_STOPWORDS: frozenset[str] = frozenset({
    "the", "a", "an", "and", "or", "but", "for", "to", "of", "in", "on", "at",
    "by", "with", "from", "as", "is", "are", "be", "was", "were", "will", "would",
    "could", "should", "may", "might", "has", "have", "had", "its", "it", "this",
    "that", "these", "those", "new", "more", "up", "down", "over", "after", "before",
    "amid", "into", "out", "than", "then", "now", "say", "says", "said", "report",
    "reports", "reported", "stock", "stocks", "share", "shares", "market", "markets",
    "inc", "corp", "co", "ltd", "plc", "group", "company", "update", "news", "today",
    "week", "year", "day", "us", "u", "s", "vs", "amp", "how", "why", "what", "who",
    "you", "your", "we", "our", "his", "her", "their", "they", "he", "she",
    # Publisher / wire-service names — Google News appends "- Publisher" to every
    # title, so without these two same-source articles would falsely cluster.
    "bloomberg", "reuters", "cnbc", "wsj", "ft", "com", "wall", "street",
    "journal", "financial", "times", "barron", "barrons", "yahoo", "fortune",
})

# Google News titles end with " - Publisher Name"; strip it so the source
# attribution never contributes clustering tokens.
_SOURCE_SUFFIX_RE = re.compile(r"\s+-\s+[^-]+$")


def _cluster_tokens(title: str) -> set[str]:
    """Significant tokens used to decide if two stories cover the same event."""
    stripped = _SOURCE_SUFFIX_RE.sub("", title)
    return {
        token
        for token in normalize_title(stripped).split()
        if len(token) >= 3 and token not in _CLUSTER_STOPWORDS
    }


_IMPACT_LABELS: dict[str, str] = {
    "earnings": "fundamental",
    "guidance": "fundamental",
    "regulation": "regulatory overhang",
    "lawsuit": "regulatory overhang",
    "deal": "strategic optionality",
    "ma": "strategic optionality",
    "ai": "secular / AI",
    "analyst": "sentiment",
    "analyst_rating": "sentiment",
    "product": "product cycle",
    "market": "macro / beta",
    "macro": "macro / beta",
    "market_reaction": "macro / beta",
}

# Event types that, when corroborated by multiple sources, are worth a closer
# look rather than passive monitoring.
_THESIS_RELEVANT_EVENTS: frozenset[str] = frozenset({
    "earnings", "guidance", "regulation", "lawsuit", "deal", "ma",
})


@dataclass
class _Cluster:
    """An in-progress news cluster while grouping cross-source stories."""

    seed: frozenset[str]
    headline: str
    members: list[tuple[TickerReport, NewsArticle]]


def event_clusters(report: DailyReport, min_sources: int = 2) -> list[dict[str, object]]:
    """Group cross-source news covering the same event into clusters.

    Two articles join the same cluster when they share at least two significant
    title tokens (generic finance words excluded). This collapses the common
    pattern where one story (e.g. "SpaceX–Tesla merger speculation") is reported
    by Bloomberg, CNBC ×4, etc. into a single card that shows source count,
    impact tag, and a confidence read instead of N near-duplicate rows.

    Only clusters drawing on at least ``min_sources`` distinct outlets are
    returned — a single-source story is not an "event cluster".
    """
    candidates = sorted(
        (
            (item, article)
            for item in report.ticker_reports
            for article in item.articles
        ),
        key=lambda pair: float(getattr(pair[1], "importance_score", 0.0)),
        reverse=True,
    )

    clusters: list[_Cluster] = []
    for item, article in candidates:
        tokens = _cluster_tokens(article.title)
        if len(tokens) < 2:
            continue
        match = None
        # Compare against each cluster's *seed* tokens (frozen at creation), not a
        # growing union — otherwise clusters snowball and absorb unrelated stories.
        for cluster in clusters:
            if len(tokens & cluster.seed) >= 2:
                match = cluster
                break
        if match is None:
            clusters.append(_Cluster(
                seed=frozenset(tokens),
                headline=article.title,
                members=[(item, article)],
            ))
        else:
            match.members.append((item, article))

    out: list[dict[str, object]] = []
    for cluster in clusters:
        members = cluster.members
        source_counts: dict[str, int] = {}
        tickers: list[str] = []
        event_counts: dict[str, int] = {}
        for item, article in members:
            source = str(getattr(article, "source", "") or article.domain)
            source_counts[source] = source_counts.get(source, 0) + 1
            symbol = item.ticker.symbol
            if symbol not in tickers:
                tickers.append(symbol)
            event_type = str(getattr(article, "event_type", "other"))
            event_counts[event_type] = event_counts.get(event_type, 0) + 1

        distinct_sources = len(source_counts)
        if distinct_sources < min_sources:
            continue

        # Prefer the most common *classified* event; fall back to "other" only
        # when nothing was classified.
        classified = {k: v for k, v in event_counts.items() if k != "other"}
        if classified:
            dominant_event = max(classified.items(), key=lambda kv: kv[1])[0]
        else:
            dominant_event = "other"
        impact = _IMPACT_LABELS.get(dominant_event, "sentiment")

        article_count = len(members)
        if distinct_sources >= 3:
            confidence = "high"
        elif distinct_sources == 2:
            confidence = "medium"
        else:
            confidence = "low"

        if confidence in ("high", "medium") and dominant_event in _THESIS_RELEVANT_EVENTS:
            action = "review — corroborated, may be thesis-relevant"
        else:
            action = "monitor only, not thesis-changing yet"

        sources_label = ", ".join(
            f"{name} ×{count}" if count > 1 else name
            for name, count in sorted(source_counts.items(), key=lambda kv: (-kv[1], kv[0]))
        )

        out.append({
            "headline": cluster.headline,
            "tickers": tickers,
            "sources": sources_label,
            "source_count": distinct_sources,
            "article_count": article_count,
            "event_type": dominant_event,
            "impact": impact,
            "confidence": confidence,
            "action": action,
        })

    out.sort(key=lambda c: (int(c["source_count"]), int(c["article_count"])), reverse=True)
    return out


TIER1_NEWS_DOMAINS = {
    "reuters.com",
    "bloomberg.com",
    "wsj.com",
    "ft.com",
    "cnbc.com",
    "apnews.com",
}
OFFICIAL_SOURCE_HINTS = ("sec.gov", "investor.", "ir.", "businesswire.com", "prnewswire.com", "globenewswire.com")


def source_reliability(article: object) -> dict[str, object]:
    domain = str(getattr(article, "domain", "")).lower()
    source = str(getattr(article, "source", "")).lower()
    combined = f"{domain} {source}"
    if any(hint in combined for hint in OFFICIAL_SOURCE_HINTS):
        return {"tier": "official", "label": "official/company", "score": 3}
    if domain in TIER1_NEWS_DOMAINS or any(domain.endswith("." + d) for d in TIER1_NEWS_DOMAINS):
        return {"tier": "tier1", "label": "tier 1 media", "score": 2}
    if "seekingalpha" in combined or "fool.com" in combined:
        return {"tier": "commentary", "label": "commentary", "score": 0}
    return {"tier": "trusted", "label": "trusted media", "score": 1}


def date_or_na(value: object) -> str:
    if value is None:
        return "N/A"
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def days_until(value: object, anchor: date) -> str:
    if not isinstance(value, date):
        return ""
    delta = (value - anchor).days
    if delta < 0:
        return f"{-delta}天前"
    if delta == 0:
        return "今日"
    if delta == 1:
        return "明日"
    return f"{delta}天後"


def earnings_delta(item: TickerReport, anchor: date) -> int | None:
    if not item.earnings or not isinstance(item.earnings.earnings_date, date):
        return None
    return (item.earnings.earnings_date - anchor).days


def earnings_urgency(value: object, anchor: date) -> str:
    if not isinstance(value, date):
        return "none"
    delta = (value - anchor).days
    if delta < 0:
        return "past"
    if delta <= 1:
        return "imminent"
    if delta <= 3:
        return "soon"
    if delta <= 7:
        return "week"
    return "later"


def earnings_urgency_label(value: object, anchor: date) -> str:
    labels = {
        "none": "",
        "past": "已過期",
        "imminent": "即將公布",
        "soon": "近期",
        "week": "本週",
        "later": "稍後",
    }
    return labels.get(earnings_urgency(value, anchor), "")


def position_status_label(value: object) -> str:
    labels = {
        "watchlist": "觀察中",
        "holding": "已持有",
        "tracking": "追蹤中",
        "avoid": "暫不考慮",
    }
    text = str(value or "")
    return labels.get(text, text)


def review_status_label(value: object) -> str:
    labels = {
        "reviewed": "已檢視",
        "in-progress": "檢視中",
        "not-reviewed": "未檢視",
    }
    text = str(value or "")
    return labels.get(text, text.replace("-", " ").title())


def card_state_label(value: object) -> str:
    labels = {
        "hot": "熱點",
        "warm": "留意",
        "warn": "警示",
        "quiet": "平穩",
    }
    text = str(value or "")
    return labels.get(text, text.title())


def html_metric_label(value: object) -> str:
    key = str(value or "")
    return HTML_METRIC_LABELS.get(key, METRIC_LABELS.get(key, key))


def event_label_zh(event_type: object) -> str:
    key = str(event_type or "")
    return EVENT_LABELS_ZH.get(key, zh_text(event_label(key)))


def source_reliability_label(reliability: object) -> str:
    if isinstance(reliability, dict):
        label = str(reliability.get("label") or "")
    else:
        label = str(reliability or "")
    return SOURCE_RELIABILITY_LABELS_ZH.get(label, zh_text(label))


def level_label(value: object) -> str:
    text = str(value or "")
    return LEVEL_LABELS_ZH.get(text.lower(), zh_text(text))


# zh_text replacement table, hoisted to module level: the filter runs thousands
# of times per render and rebuilding the ~150-entry literal per call is pure
# waste. Insertion order matters where entries overlap ("tickers" before
# "ticker", "not-reviewed" before "reviewed").
_ZH_REPLACEMENTS: dict[str, str] = {
        "FOMC Rate Decision": "FOMC 利率決策",
        "Rate decision / statement expected at 2:00 PM ET; press conference normally 2:30 PM ET.": "預計美東時間下午 2:00 公布利率決策與聲明，記者會通常於 2:30 舉行。",
        "Review guidance, valuation, and recent news before the print.": "公布前先檢查財測、估值與近期新聞。",
        "Earnings date is inside the 7-day review window.": "財報日期已進入 7 天檢視窗口。",
        "revisit thesis before chasing": "追價前先重新檢查投資論點",
        "avoid chasing without a fresh catalyst": "沒有新催化時避免追價",
        "high multiple but EPS revisions up": "高本益比但 EPS 預估上修",
        "EPS revisions down": "EPS 預估下修",
        "heavy news flow": "重大新聞密集",
        "top-tier news": "一級新聞",
        "crowded setup": "交易條件擁擠",
        "stretched valuation": "估值偏高",
        "extreme valuation": "估值風險極高",
        "hot but overbought": "強勢但過熱",
        "overbought technicals": "技術面過熱",
        "from 52W high": "距 52 週高點",
        "SPY 20D momentum": "SPY 20 日動能",
        "QQQ 20D momentum": "QQQ 20 日動能",
        "VIX level": "VIX 水位",
        "Credit appetite": "信用風險偏好",
        "yfinance proxy": "yfinance 估算",
        "risk-on": "偏多",
        "risk-off": "避險",
        "neutral": "中性",
        "Rates mixed": "利率訊號分歧",
        "Rates pressure": "利率壓力",
        "Dollar pressure": "美元壓力",
        "Oil inflation pressure": "油價通膨壓力",
        "avg yield move": "平均殖利率變動",
        "Valuation fallback used": "已使用估值備援資料",
        "Earnings date from yfinance only — verify with company IR or Nasdaq": "財報日期僅來自 yfinance，請再向公司投資人關係網站或 Nasdaq 確認",
        "Google News RSS redirect unresolved — verify original source": "Google News RSS 重新導向未解析，請確認原始來源",
        "Missing:": "缺少欄位：",
        "strategic optionality": "策略選擇權",
        "macro / beta": "總經 / Beta",
        "No material changes versus the previous saved run.": "相較上次儲存的報告，沒有重大變化。",
        "Overextended": "漲幅過度延伸",
        "Rule Alerts": "規則警示",
        "review — corroborated, may be thesis-relevant": "多來源佐證，應檢視是否影響投資論點",
        "S&P 500 futures": "S&P 500 期貨",
        "Nasdaq 100 futures": "Nasdaq 100 期貨",
        "SPY premarket": "SPY 盤前",
        "QQQ premarket": "QQQ 盤前",
        "Mega-cap software": "大型軟體",
        "Internet / ads": "網路 / 廣告",
        "Consumer hardware": "消費電子",
        "ETF / Index": "ETF / 指數",
        "AI infra": "AI 基礎設施",
        "Memory": "記憶體",
        "Semis": "半導體",
        "Crypto": "加密貨幣",
        "Space": "太空",
        "regular": "一般盤",
        "cloud": "雲端",
        "monitor only, not thesis-changing yet": "持續監看，暫未改變投資論點",
        "Biggest positive impact": "最大正面貢獻",
        "Biggest negative impact": "最大負面貢獻",
        "Highest risk holding": "風險最高持股",
        "Holding with event soon": "近期有事件的持股",
        "Watchlist top movers": "觀察清單主要異動",
        "Catalyst-backed": "有催化支持",
        "Unclear / noisy": "原因不明 / 雜訊偏多",
        "No watchlist gaps above threshold.": "觀察清單沒有超過門檻的盤前缺口。",
        "No mover with clear catalyst support.": "目前沒有具明確催化支持的異動。",
        "No unexplained high-priority movers.": "目前沒有原因不明的高優先異動。",
        "Review now": "立即檢視",
        "event risk": "\u4e8b\u4ef6\u98a8\u96aa",
        "no action before earnings review": "\u8ca1\u5831\u6aa2\u8996\u524d\u66ab\u505c\u64cd\u4f5c",
        "no action before event review": "\u4e8b\u4ef6\u6aa2\u8996\u524d\u66ab\u505c\u64cd\u4f5c",
        "Review only before event": "\u4e8b\u4ef6\u524d\u50c5\u6aa2\u8996\uff0c\u4e0d\u64cd\u4f5c",
        "Do not add / consider trim": "\u505c\u6b62\u52a0\u78bc\uff0c\u8a55\u4f30\u6e1b\u78bc",
        "Priority add candidate": "\u512a\u5148\u52a0\u78bc\u5019\u9078",
        "event window": "\u4e8b\u4ef6\u7a97\u53e3",
        "less stretched": "\u56de\u6a94\u5e45\u5ea6\u8f03\u6eab\u548c",
        "no trusted news": "\u7f3a\u5c11\u53ef\u4fe1\u65b0\u805e\u4f86\u6e90",
        "verify company and source updates": "\u8acb\u78ba\u8a8d\u516c\u53f8\u516c\u544a\u8207\u4f86\u6e90\u66f4\u65b0",
        "unavailable": "\u7121\u8cc7\u6599",
        "No chase": "不追價",
        "Monitor": "持續監看",
        "Extreme valuation": "估值風險極高",
        "event soon": "事件將近",
        "latest daily": "最新日漲跌",
        "premarket": "盤前",
        "tier 1 media": "一級媒體",
        "trusted media": "可信媒體",
        "no linked headline": "無關聯新聞",
        "regulatory overhang": "監管壓力",
        "secular / AI": "長期趨勢 / AI",
        "Market sentiment": "市場情緒",
        "sentiment": "市場情緒",
        "fundamental": "基本面",
        "Other watchlist": "其他觀察",
        "Communication Services": "通訊服務",
        "Consumer Cyclical": "非必需消費",
        "Consumer Defensive": "必需消費",
        "Financial Services": "金融服務",
        "Basic Materials": "原物料",
        "Real Estate": "不動產",
        "Technology": "科技",
        "Industrials": "工業",
        "Regulation": "監管",
        "Other": "其他",
        "Breakout confirmed": "突破確認",
        "Pullback buy zone": "回檔買點區",
        "Extended, do not chase": "已延伸，避免追高",
        "Mixed / neutral": "中性",
        "Thesis weakening": "投資論點轉弱",
        "Avoid": "暫避",
        "Trend healthy": "趨勢良好",
        "Volatility contraction": "\u6ce2\u52d5\u6536\u6582",
        "Breakout validation": "\u7a81\u7834\u9a57\u8b49",
        "Risk box": "\u98a8\u96aa\u76d2",
        "Base tightening": "\u578b\u614b\u6536\u6582",
        "Base still loose": "\u6ce2\u52d5\u5c1a\u672a\u6536\u6582",
        "Base data incomplete": "\u6536\u6582\u8cc7\u6599\u4e0d\u8db3",
        "Breakout holding": "\u7a81\u7834\u5f8c\u5b88\u7a69",
        "Breakout failed": "\u7a81\u7834\u5931\u6557",
        "Breakout needs volume": "\u7a81\u7834\u91cf\u80fd\u4e0d\u8db3",
        "No recent breakout": "\u5c1a\u672a\u89f8\u767c\u7a81\u7834",
        "Risk controlled": "\u98a8\u96aa\u53ef\u63a7",
        "Risk needs smaller size": "\u98a8\u96aa\u504f\u5bec\uff0c\u7e2e\u5c0f\u90e8\u4f4d",
        "Risk too wide": "\u98a8\u96aa\u904e\u5bec",
        "Risk box unavailable": "\u98a8\u96aa\u76d2\u8cc7\u6599\u4e0d\u8db3",
        "Right-side ready": "\u53f3\u5074\u689d\u4ef6\u5230\u4f4d",
        "Base building": "\u6536\u6582\u7b49\u5f85\u7a81\u7834",
        "Wait for confirmation": "\u7b49\u5f85\u53f3\u5074\u78ba\u8a8d",
        "Protect capital first": "\u5148\u63a7\u5236\u98a8\u96aa",
        "Pivot": "\u6a1e\u7d10",
        "Entry": "\u53c3\u8003\u9032\u5834",
        "Invalidation": "\u5931\u6548\u50f9",
        "2R checkpoint": "2R \u6aa2\u67e5\u9ede",
        "BB width percentile": "\u5e03\u6797\u5bec\u5ea6\u767e\u5206\u4f4d",
        "5D volume": "5 \u65e5\u91cf\u80fd",        "Market alignment": "\u5e02\u5834\u540c\u6b65",
        "Market and RS aligned": "\u5e02\u5834\u8207\u76f8\u5c0d\u5f37\u5ea6\u540c\u6b65",
        "Market trend weak": "\u5e02\u5834\u8da8\u52e2\u504f\u5f31",
        "Relative strength lagging": "\u76f8\u5c0d\u5f37\u5ea6\u843d\u5f8c",
        "Max size": "\u6700\u5927\u55ae\u4f4d\u6578",        "Pullback watch": "回檔可觀察",
        "Trend weakening": "趨勢轉弱",
        "Bullish MA stack": "均線多頭排列",
        "Bearish MA stack": "均線空頭排列",
        "Mixed MA stack": "均線排列分歧",
        "20D distance": "距 20D",
        "20D slope (5d)": "20D 近 5 日斜率",
        "Volume": "量能",
        "20D average": "20D 均量",
        "Breakout above prior 20D high": "收盤突破前 20 日高點",
        "Breakdown below prior 20D low": "收盤跌破前 20 日低點",
        "Close below 60D support": "收盤跌破 60D 支撐",
        "20D below 60D": "20D 低於 60D",        "Reviewed": "已檢視",
        "In progress": "檢視中",
        "Not reviewed": "未檢視",
        "watching": "觀察中",
        "building": "建立中",
        "active": "有效",
        "weakening": "轉弱",
        "broken": "失效",
        "unmarked": "未標記",
        "Above 20D / 60D / 120D": "站上 20D / 60D / 120D",
        "Above 20D / 60D, below 120D": "站上 20D / 60D，低於 120D",
        "Below 20D / 60D / 120D": "低於 20D / 60D / 120D",
        "Near 20D support": "接近 20D 支撐",
        "5D below 20D": "5D 低於 20D",
        "near 52w high": "接近 52 週高",
        "below 52w high": "低於 52 週高",
        "right at 52w high": "貼近 52 週高",
        "revisions up": "預估上修",
        "flat revisions": "預估持平",
        "EPS negative / unstable": "EPS 轉弱/不穩",
        "overbought": "過熱",
        "oversold": "超賣",
        "data warnings": "資料警示",
        "data warning": "資料警示",
        "pre-market": "盤前",
        "Earnings": "財報",
        "Above 20D / 120D, below 60D": "\u7ad9\u4e0a 20D / 120D\uff0c\u4f4e\u65bc 60D",
        "Above 60D / 120D, below 20D": "\u7ad9\u4e0a 60D / 120D\uff0c\u4f4e\u65bc 20D",
        "Above 20D, below 60D / 120D": "\u7ad9\u4e0a 20D\uff0c\u4f4e\u65bc 60D / 120D",
        "Above 60D, below 20D / 120D": "\u7ad9\u4e0a 60D\uff0c\u4f4e\u65bc 20D / 120D",
        "Above 120D, below 20D / 60D": "\u7ad9\u4e0a 120D\uff0c\u4f4e\u65bc 20D / 60D",
        "above 20D/60D/120D": "\u7ad9\u4e0a 20D / 60D / 120D",
        "below 20D/60D/120D": "\u4f4e\u65bc 20D / 60D / 120D",
        "RS leadership": "\u76f8\u5c0d\u5f37\u5ea6\u9818\u5148",
        "RS positive": "\u76f8\u5c0d\u5f37\u5ea6\u6b63\u5411",
        "RS lagging": "\u76f8\u5c0d\u5f37\u5ea6\u843d\u5f8c",
        "chase risk": "\u8ffd\u9ad8\u98a8\u96aa",
        "valuation context": "\u4f30\u503c\u80cc\u666f",
        "top stories": "重點新聞",
        "top story": "重點新聞",
        "Earnings today": "今日財報",
        "Earnings tomorrow": "明日財報",
        "Trailing P/E": "過去12月 P/E",
        "Forward P/E": "預估 P/E",
        "None": "無",
        "Extreme": "極高",
        "High": "高",
        "Elevated": "偏高",
        "Low": "低",
        "Medium": "中",
        "Extreme Greed": "極度貪婪",
        "Greed": "貪婪",
        "Neutral": "中性",
        "Fear": "恐懼",
        "Extreme Fear": "極度恐懼",
        "Rates": "利率",
        "DXY": "美元",
        "Oil": "油價",
        "volume": "成交量",
        "today": "今日",
        "tomorrow": "明日",
        "tickers": "檔",
        "ticker": "檔",
        "holdings": "持股",
        "holding": "持股",
        "events": "事件",
        "event": "事件",
        "Top-news count increased": "重點新聞增加",
        "Thesis state changed": "投資論點狀態改變",
        "Review status changed": "檢視狀態改變",
        "Valuation risk changed": "估值風險改變",
        "More data warnings": "資料警示增加",
        "More top-news": "重點新聞增加",
        "Attention score rose": "關注分數上升",
        "Thesis moved": "投資論點改變",
        "post-earnings review due": "待做財報後檢視",
        "post-earnings review": "財報後檢視",
        "thesis": "投資論點",
        "news burst": "新聞放量",
        "valuation with active thesis": "估值偏高且論點仍有效",
        "last reviewed": "上次檢視",
        "never reviewed": "尚未檢視",
        "warning(s)": "個警示",
        "reported": "已公布",
        "unmarked": "未標記",
        "not-reviewed": "未檢視",
        "in-progress": "檢視中",
        "reviewed": "已檢視",
        "official/company": "官方/公司",
        "tier 1 media": "一線媒體",
        "trusted media": "可信媒體",
        "commentary": "評論",
        "P/E >=100": "P/E >=100",
        "Beat": "優於",
        "Miss": "低於",
        "In line": "符合",
        "Up": "上修",
        "Flat": "持平",
        "Down": "下修",
        "Unscored": "尚未評分",
        "Watch / no fresh capital": "觀察，暫不投入新資金",
        "Wait for pullback": "等待回檔",
        "Hold / add only on confirmation": "續抱，確認後再加碼",
        "Reduce / avoid": "減碼或暫避",
        "No fresh capital": "暫不投入新資金",        "News fetching skipped by --no-news.": "已使用 --no-news 跳過新聞抓取。",
        "Valuation and earnings fetching skipped by --no-valuation.": "已使用 --no-valuation 跳過估值與財報抓取。",
        "Macro calendar fetching skipped by --no-macro.": "已使用 --no-macro 跳過總經日曆抓取。",
        "Market sentiment skipped because valuation fetching is disabled.": "因估值抓取停用，已跳過市場情緒。",
}


def zh_text(value: object) -> str:
    """Display-only Traditional Chinese wording for common dashboard phrases."""
    text = str(value or "")
    text = re.sub(r"([+-]?\d+(?:\.\d+)?)% from 52W high", lambda match: f"距 52 週高點 {match.group(1)}%", text)
    text = re.sub(
        r"(\d+) trusted headline\(s\), (\d+) top-tier\.",
        lambda match: f"{match.group(1)} 則可信新聞，{match.group(2)} 則一級新聞。",
        text,
    )
    text = re.sub(
        r"(\d+) headline\(s\); revisit thesis before chasing\.",
        lambda match: f"{match.group(1)} 則新聞；追價前先重新檢查投資論點。",
        text,
    )
    text = re.sub(r"FY1 EPS revision ([+-]?\d+(?:\.\d+)?)% over 30D\.", lambda match: f"FY1 EPS 預估 30 日修正 {match.group(1)}%。", text)
    for src, dest in _ZH_REPLACEMENTS.items():
        text = text.replace(src, dest)
    text = re.sub(r"\bin (\d+)d\b", lambda match: f"{match.group(1)} \u5929\u5f8c", text)
    text = re.sub(r"\b(\d+)d ago\b", lambda match: f"{match.group(1)} \u5929\u524d", text)
    text = re.sub(r"above (\d+) of 3 MAs", lambda match: f"\u7ad9\u4e0a 3 \u689d\u5747\u7dda\u4e2d\u7684 {match.group(1)} \u689d", text)
    text = re.sub(r"\bscore (\d+)\b", lambda match: f"右側分數 {match.group(1)}", text)
    text = re.sub(r"\b(\d+) articles?\b", lambda match: f"{match.group(1)} 篇報導", text)
    text = re.sub(r"\b(\d+(?:\.\d+)?)x volume\b", lambda match: f"成交量 {match.group(1)} 倍", text)
    text = re.sub(r"\b(\d+)\s+headlines?\b", lambda match: f"{match.group(1)} 則新聞", text)
    text = re.sub(r"\b(\d+)\s+top-tier\b", lambda match: f"{match.group(1)} 則一級新聞", text)
    text = re.sub(r"\bearnings\b", "財報", text)
    text = re.sub(r"([+-]?\d+(?:\.\d+)?)% over (\d+) sessions", lambda match: f"過去 {match.group(2)} 個交易日 {match.group(1)}%", text)
    text = re.sub(r"\bEPS rev\b", "EPS 預估修正", text)
    text = re.sub(r"\brevenue rev\b", "營收預估修正", text)
    text = re.sub(r"\b(\d+)/(\d+) horizons\b", lambda match: f"{match.group(1)}/{match.group(2)} 個期間領先", text)
    text = re.sub(r"([+-]?\d+(?:\.\d+)?)pp average", lambda match: f"平均 {match.group(1)} 個百分點", text)
    text = text.replace("pp avg", " \u500b\u767e\u5206\u9ede\u5e73\u5747")
    if re.search(r"[\u3400-\u9fff]", text):
        text = text.replace("; ", "；").replace(". ", "。")
        if text.endswith("."):
            text = text[:-1] + "。"
    return text


def event_label(event_type: object) -> str:
    return EVENT_LABELS.get(str(event_type), str(event_type).replace("_", " ").title())


# One-line interpretation for top news, by event_type.
# Goal: turn "headline" into "judgment" — what should the reader take from it.
NEWS_RATIONALE: dict[str, str] = {
    "earnings": "財報解讀",
    "guidance": "前景影響評估",
    "ai": "AI/資本支出啟示",
    "deal": "戰略佈局",
    "regulation": "監管風險",
    "lawsuit": "訴訟風險",
    "antitrust": "反壟斷隱憂",
    "supply": "供應鏈訊號",
    "product": "產品週期訊號",
    "analyst": "賣方觀點轉變",
    "analyst_call": "賣方觀點轉變",
    "management": "領導層變動",
    "macro": "宏觀風險",
    "market": "宏觀風險",
}


def news_rationale(article: object) -> str:
    """Short interpretation phrase for top news items. Empty when no clear angle."""
    return NEWS_RATIONALE.get(str(getattr(article, "event_type", "")), "")


def earnings_action(item: TickerReport, anchor: date) -> str | None:
    """Rule-based action recommendation tied to earnings timing + RSI.

    Returns None when the ticker isn't in any earnings window.

    The rules are intentionally short verbs so the user can act without thinking:
      - Earnings TODAY + overbought (RSI ≥ 70)   → "Wait reaction"
      - Earnings TODAY + oversold (RSI ≤ 30)     → "Watch capitulation"
      - Earnings TODAY (other)                   → "Watch reaction"
      - Earnings TOMORROW                        → "Prepare plan"
      - Earnings 2-7d                            → "Build thesis"
      - Reported 1-7d ago                        → "Review outcome"
    """
    if not item.earnings or not isinstance(item.earnings.earnings_date, date):
        return None
    delta = (item.earnings.earnings_date - anchor).days
    rsi = None
    if item.valuation:
        rsi = _as_float(item.valuation.metrics.get("rsi_14"))

    if delta == 0:
        if rsi is not None and rsi >= 70:
            return "等待反應（過度延伸）"
        if rsi is not None and rsi <= 30:
            return "觀察恐慌賣壓"
        return "觀察反應"
    if delta == 1:
        return "準備計畫"
    if 2 <= delta <= 7:
        return "建立論點"
    if -7 <= delta <= -1:
        return "檢視結果"
    return None


def _market_benchmark_pairs(item: TickerReport) -> tuple[tuple[str, str, str], ...]:
    """Return the comparable benchmarks for the ticker's declared market."""
    market = item.ticker.market
    if market in {"twse", "tpex", "taiwan"}:
        return (("vs_twii", "twii", "TWII"),)
    if market == "crypto":
        if item.ticker.symbol.upper() == "BTC-USD":
            return ()
        return (("vs_btc", "btc", "BTC"),)
    return (
        ("vs_spy", "spy", "SPY"),
        ("vs_qqq", "qqq", "QQQ"),
    )


def relative_strength(item: TickerReport, benchmarks: dict[str, float]) -> dict[str, float]:
    """Return 20-session relative-strength spreads against market peers."""
    if not item.valuation:
        return {}
    ticker_return = _as_float(item.valuation.metrics.get("return_20d"))
    if ticker_return is None:
        return {}
    out: dict[str, float] = {}
    for result_key, benchmark_key, _label in _market_benchmark_pairs(item):
        bench_return = benchmarks.get(f"{benchmark_key}_20d")
        if isinstance(bench_return, (int, float)):
            out[result_key] = round(ticker_return - bench_return, 2)
    return out


def relative_strength_profile(item: TickerReport, benchmarks: dict[str, float]) -> dict[str, object]:
    """Summarize market-relative strength across 20/60/120 sessions."""
    if not item.valuation:
        return {}
    pairs = _market_benchmark_pairs(item)
    if not pairs:
        return {}

    horizon_spreads: dict[int, float] = {}
    for horizon in (20, 60, 120):
        ticker_return = _as_float(item.valuation.metrics.get(f"return_{horizon}d"))
        if ticker_return is None:
            continue
        peers = [
            value
            for _result_key, benchmark_key, _label in pairs
            if isinstance((value := benchmarks.get(f"{benchmark_key}_{horizon}d")), (int, float))
        ]
        if peers:
            horizon_spreads[horizon] = round(ticker_return - sum(peers) / len(peers), 2)
    if not horizon_spreads:
        return {}

    spreads = list(horizon_spreads.values())
    positive = sum(1 for value in spreads if value > 0)
    return {
        "market": item.ticker.market,
        "benchmark_label": " / ".join(label for _key, _bench, label in pairs),
        "horizon_spreads": horizon_spreads,
        "available_horizons": len(spreads),
        "positive_horizons": positive,
        "average_spread": round(sum(spreads) / len(spreads), 2),
    }


def format_relative_strength(rs: dict[str, float]) -> list[str]:
    """Compact phrases like '+2.3% vs SPY 20D'."""
    parts: list[str] = []
    labels = (
        ("vs_spy", "vs SPY 20D"),
        ("vs_qqq", "vs QQQ 20D"),
        ("vs_twii", "vs TWII 20D"),
        ("vs_btc", "vs BTC 20D"),
    )
    for key, label in labels:
        if key in rs:
            value = rs[key]
            sign = "+" if value >= 0 else ""
            parts.append(f"{sign}{value:.1f}% {label}")
    return parts
# Right-side trading status labels — used by both the badge and the insights row.
RIGHT_SIDE_STATUSES = (
    "Breakout confirmed",
    "Pullback buy zone",
    "Extended, do not chase",
    "Mixed / neutral",
    "Thesis weakening",
    "Avoid",
)


MIN_PRICE_REGIME_SESSIONS = 21


def price_regime_status(item: TickerReport) -> dict[str, object] | None:
    """Describe a technical-history reset without inventing adjusted prices."""
    if not item.valuation:
        return None
    metrics = item.valuation.metrics
    change_date = metrics.get("price_regime_change_date")
    if not change_date:
        return None
    sessions = int(_as_float(metrics.get("price_history_sessions")) or 0)
    change_pct = _as_float(metrics.get("price_regime_change_pct"))
    return {
        "date": str(change_date),
        "change_pct": change_pct,
        "sessions": sessions,
        "minimum_sessions": MIN_PRICE_REGIME_SESSIONS,
        "remaining_sessions": max(0, MIN_PRICE_REGIME_SESSIONS - sessions),
        "ready": sessions >= MIN_PRICE_REGIME_SESSIONS,
    }


def _technical_regime_ready(item: TickerReport) -> bool:
    status = price_regime_status(item)
    return status is None or bool(status["ready"])


def right_side_score(item: TickerReport, benchmarks: dict[str, float] | None = None) -> dict[str, object] | None:
    """Composite 0–100 right-side trading score with a status label.

    Combines trend (SMA stack) + relative strength + volume confirmation +
    earnings momentum + RSI cool-down + valuation overhang + distance from
    52-week high into a single score, then maps to one of:
      Avoid (<25) / Thesis weakening / Extended, do not chase /
      Breakout confirmed (>=75) / Pullback buy zone / Mixed / neutral.

    Returns None when there's no valuation snapshot (nothing to score).
    """
    if not item.valuation:
        return None
    metrics = item.valuation.metrics
    if not _technical_regime_ready(item):
        return None
    last = _as_float(metrics.get("last_close"))
    if last is None:
        return None

    benchmarks = benchmarks or {}

    score = 50
    reasons: list[tuple[int, str]] = []

    # Trend contribution from SMA stack
    sma20 = _as_float(metrics.get("sma_20"))
    sma60 = _as_float(metrics.get("sma_60"))
    sma120 = _as_float(metrics.get("sma_120"))
    sma_count = sum(1 for s in (sma20, sma60, sma120) if s is not None)
    above_count = sum(
        1
        for s in (sma20, sma60, sma120)
        if s is not None and last > s
    )
    if sma_count >= 3:
        if above_count == 3:
            score += 10
            reasons.append((10, "above 20D/60D/120D"))
        elif above_count == 2:
            score += 5
            reasons.append((5, f"above {above_count} of 3 MAs"))
        elif above_count == 0:
            score -= 10
            reasons.append((-10, "below 20D/60D/120D"))

    # Relative strength vs SPY/QQQ
    rs = relative_strength(item, benchmarks)
    if rs:
        avg_spread = sum(rs.values()) / len(rs)
        if avg_spread > 5:
            score += 10
            reasons.append((10, f"RS leadership ({avg_spread:+.1f}pp avg)"))
        elif avg_spread > 0:
            score += 5
            reasons.append((5, f"RS positive ({avg_spread:+.1f}pp avg)"))
        elif avg_spread < -5:
            score -= 5
            reasons.append((-5, f"RS lagging ({avg_spread:+.1f}pp avg)"))

    # Volume confirmation
    vol = _as_float(metrics.get("volume_vs_20d"))
    vpa = volume_price_analysis(item)
    if vpa:
        adjustment = int(vpa["score_adjustment"])
        if adjustment:
            score += adjustment
            reasons.append((adjustment, f"VPA {vpa['event']}"))
        # VPA already interpreted direction, spread and close location.
        vol = None
    if vol is not None:
        if vol > 1.5:
            score += 5
            reasons.append((5, f"volume {vol:.1f}× 20D"))
        elif vol < 0.5:
            score -= 5
            reasons.append((-5, f"volume {vol:.1f}× 20D"))

    # Earnings momentum (FY1 EPS revision over last 30 days)
    eps_rev = _as_float(metrics.get("fy1_eps_revision_30d"))
    earnings_negative = False
    if eps_rev is not None:
        if eps_rev > 2:
            score += 10
            reasons.append((10, f"EPS rev {eps_rev:+.1f}% 30D"))
        elif eps_rev > 0:
            score += 5
            reasons.append((5, f"EPS rev {eps_rev:+.1f}% 30D"))
        elif eps_rev < -2:
            score -= 5
            earnings_negative = True
            reasons.append((-5, f"EPS rev {eps_rev:+.1f}% 30D"))

    # RSI and valuation remain context; they do not invalidate a confirmed trend.
    rsi = _as_float(metrics.get("rsi_14"))
    if rsi is not None and rsi >= 70:
        reasons.append((0, f"RSI {rsi:.0f}: chase risk"))

    risk_tier = valuation_risk_label(item)
    if risk_tier in {"High", "Extreme"}:
        reasons.append((0, f"{risk_tier} valuation context"))

    # Stretched into 52-week high
    from_high = from_52w_high_pct(item)
    if from_high is not None and from_high >= -2:
        score -= 5
        reasons.append((-5, "right at 52w high"))

    score = max(0, min(100, score))

    # Status label — priority order so the loudest signal wins
    near_52w_high = from_high is not None and from_high >= -2
    trend_up = sma_count >= 3 and above_count == 3
    rsi_overbought = rsi is not None and rsi >= 70

    if score < 25:
        status = "Avoid"
        tone = "down"
    elif score < 40 and earnings_negative:
        status = "Thesis weakening"
        tone = "down"
    elif trend_up and near_52w_high and rsi_overbought:
        status = "Extended, do not chase"
        tone = "extended"
    elif score >= 75:
        status = "Breakout confirmed"
        tone = "up"
    elif 55 <= score < 75:
        status = "Pullback buy zone"
        tone = "up"
    else:
        status = "Mixed / neutral"
        tone = "mixed"

    reasons.sort(key=lambda pair: abs(pair[0]), reverse=True)
    formatted_reasons = [
        f"{'+' if pts > 0 else ''}{pts} {label}" for pts, label in reasons
    ]
    slug = (
        status.lower()
        .replace(" / ", "-")
        .replace(", ", " ")
        .replace(" ", "-")
    )

    return {
        "score": int(score),
        "status": status,
        "tone": tone,
        "slug": slug,
        "reasons": formatted_reasons,
    }


def technical_playbook(item: TickerReport) -> dict[str, object] | None:
    """Classify a ticker's technical state from explicit, inspectable rules.

    This is deliberately separate from ``right_side_score``: it only evaluates
    price structure, MA slope, distance, volume, and a prior 20-session level.
    It is a repeatable review aid, not a trade instruction.
    """
    if not item.valuation:
        return None
    metrics = item.valuation.metrics
    last = _as_float(metrics.get("last_close"))
    sma20 = _as_float(metrics.get("sma_20"))
    sma60 = _as_float(metrics.get("sma_60"))
    sma120 = _as_float(metrics.get("sma_120"))
    if last is None or sma20 in (None, 0) or sma60 is None or sma120 is None:
        return None

    distance20 = round((last - sma20) / sma20 * 100.0, 2)
    slope20 = _as_float(metrics.get("sma_20_slope_5d"))
    volume = _as_float(metrics.get("volume_vs_20d"))
    prior_high = _as_float(metrics.get("prior_20d_high"))
    prior_low = _as_float(metrics.get("prior_20d_low"))
    rsi = _as_float(metrics.get("rsi_14"))

    bullish_stack = last > sma20 > sma60 > sma120
    bearish_stack = last < sma20 < sma60 < sma120
    base_up = sma20 > sma60 > sma120
    breaking_down = prior_low is not None and last < prior_low
    weakening = (
        last < sma60
        or sma20 < sma60
        or breaking_down
        or (last < sma20 and slope20 is not None and slope20 <= -1.0)
    )
    breakout = bool(
        bullish_stack
        and prior_high is not None
        and last > prior_high
        and volume is not None
        and volume >= 1.5
    )
    extended = base_up and (distance20 >= 8.0 or (rsi is not None and rsi >= 70.0))
    pullback = bool(
        base_up
        and -3.0 <= distance20 <= 3.0
        and (rsi is None or 40.0 <= rsi <= 65.0)
        and (volume is None or volume <= 1.2)
    )

    criteria: list[str] = []
    if bullish_stack:
        criteria.append("Bullish MA stack")
    elif bearish_stack:
        criteria.append("Bearish MA stack")
    else:
        criteria.append("Mixed MA stack")
    criteria.append(f"20D distance {distance20:+.1f}%")
    if slope20 is not None:
        criteria.append(f"20D slope (5d) {slope20:+.1f}%")
    if volume is not None:
        criteria.append(f"Volume {volume:.1f}x 20D average")
    if breakout:
        criteria.append("Breakout above prior 20D high")
    elif breaking_down:
        criteria.append("Breakdown below prior 20D low")
    elif last < sma60:
        criteria.append("Close below 60D support")
    elif sma20 < sma60:
        criteria.append("20D below 60D")
    if rsi is not None:
        criteria.append(f"RSI {rsi:.0f}")

    if breakout:
        status, tone, priority = "Breakout confirmed", "up", 5
    elif weakening:
        status, tone, priority = "Trend weakening", "down", 5
    elif extended:
        status, tone, priority = "Extended, do not chase", "extended", 4
    elif pullback:
        status, tone, priority = "Pullback watch", "up", 4
    elif bullish_stack:
        status, tone, priority = "Trend healthy", "up", 3
    else:
        status, tone, priority = "Mixed / neutral", "mixed", 1

    return {
        "status": status,
        "tone": tone,
        "priority": priority,
        "criteria": criteria[:6],
    }


def _health_tone(score: int | None) -> str:
    """Map an explainable health score to the dashboard tone vocabulary."""
    if score is None:
        return "na"
    if score >= 70:
        return "good"
    if score >= 50:
        return "mixed"
    return "danger"


def _health_dimension(
    key: str,
    label: str,
    score: float | None,
    evidence: list[str],
) -> dict[str, object]:
    normalized = None if score is None else int(round(max(0.0, min(100.0, score))))
    return {
        "key": key,
        "label": label,
        "short_label": {"trend": "趨", "momentum": "動", "volume": "量", "fundamental": "基", "risk": "險"}.get(key, label[:1]),
        "score": normalized,
        "tone": _health_tone(normalized),
        "evidence": evidence[:3],
        "available": normalized is not None,
    }


def _health_average(dimensions: list[dict[str, object]], weights: dict[str, float]) -> int | None:
    available = [dimension for dimension in dimensions if dimension["available"]]
    denominator = sum(weights[str(dimension["key"])] for dimension in available)
    if not available or denominator <= 0:
        return None
    weighted = sum(
        float(dimension["score"]) * weights[str(dimension["key"])]
        for dimension in available
    )
    return int(round(weighted / denominator))


def stock_health_diagnostic(
    item: TickerReport,
    anchor: date,
    benchmarks: dict[str, float] | None = None,
) -> dict[str, object]:
    """Build a transparent five-dimension stock health diagnostic.

    The diagnostic only uses values already collected for the daily report. A
    missing fundamental dimension (for example an ETF or crypto asset) is
    excluded from the weighted average instead of being treated as a failure.
    """
    benchmarks = benchmarks or {}
    metrics = item.valuation.metrics if item.valuation else {}
    last = _as_float(metrics.get("last_close"))
    regime = price_regime_status(item)
    rebuilding = bool(regime and not regime["ready"])

    trend_evidence: list[str] = []
    trend_score: float | None = None
    if last is not None and not rebuilding:
        sma20 = _as_float(metrics.get("sma_20"))
        sma60 = _as_float(metrics.get("sma_60"))
        sma120 = _as_float(metrics.get("sma_120"))
        available_mas = [value for value in (sma20, sma60, sma120) if value is not None]
        if available_mas:
            trend_score = 50.0
            above = sum(1 for value in available_mas if last > value)
            if len(available_mas) == 3 and last > sma20 > sma60 > sma120:
                trend_score += 25
                trend_evidence.append("價格與均線呈多頭排列")
            elif len(available_mas) == 3 and last < sma20 < sma60 < sma120:
                trend_score -= 30
                trend_evidence.append("價格與均線呈空頭排列")
            else:
                trend_score += (above / len(available_mas) - 0.5) * 30
                trend_evidence.append(f"站上 {above}/{len(available_mas)} 條主要均線")

            slope20 = _as_float(metrics.get("sma_20_slope_5d"))
            if slope20 is not None:
                trend_score += 10 if slope20 >= 1 else 5 if slope20 > 0 else -10 if slope20 <= -1 else -5
                trend_evidence.append(f"20 日線五日斜率 {slope20:+.1f}%")
            return20 = _as_float(metrics.get("return_20d"))
            if return20 is not None:
                trend_score += 8 if return20 >= 8 else 4 if return20 > 0 else -8 if return20 <= -8 else -4
                trend_evidence.append(f"近 20 日報酬 {return20:+.1f}%")

            technical = technical_playbook(item)
            if technical:
                technical_labels = {
                    "Breakout confirmed": "突破確認",
                    "Trend weakening": "趨勢轉弱",
                    "Extended, do not chase": "延伸過大，不追價",
                    "Pullback watch": "回檔觀察",
                    "Trend healthy": "趨勢健康",
                    "Mixed / neutral": "中性整理",
                }
                status = str(technical["status"])
                trend_score += 10 if status == "Breakout confirmed" else -15 if status == "Trend weakening" else 0
                trend_evidence.append(technical_labels.get(status, status))

    momentum_evidence: list[str] = []
    momentum_score: float | None = None
    if last is not None and not rebuilding:
        rs = relative_strength(item, benchmarks)
        rsi = _as_float(metrics.get("rsi_14"))
        return5 = _as_float(metrics.get("return_5d"))
        if rs or rsi is not None or return5 is not None:
            momentum_score = 50.0
            if rs:
                average_spread = sum(rs.values()) / len(rs)
                momentum_score += 22 if average_spread >= 8 else 12 if average_spread > 0 else -22 if average_spread <= -8 else -12
                momentum_evidence.append(f"相對大盤 20 日強弱 {average_spread:+.1f} 個百分點")
            if rsi is not None:
                if 50 <= rsi <= 65:
                    momentum_score += 12
                    momentum_evidence.append(f"RSI {rsi:.0f} 位於強勢區")
                elif rsi >= 75:
                    momentum_score -= 12
                    momentum_evidence.append(f"RSI {rsi:.0f} 過熱")
                elif rsi < 40:
                    momentum_score -= 10
                    momentum_evidence.append(f"RSI {rsi:.0f} 動能偏弱")
                else:
                    momentum_evidence.append(f"RSI {rsi:.0f}")
            if return5 is not None:
                momentum_score += 10 if return5 >= 5 else 5 if return5 > 0 else -10 if return5 <= -5 else -5
                momentum_evidence.append(f"近 5 日報酬 {return5:+.1f}%")

    volume_evidence: list[str] = []
    volume_score: float | None = None
    squeeze_flags = 0
    if last is not None and not rebuilding:
        volume_ratio = _as_float(metrics.get("volume_vs_20d"))
        atr_contraction = _as_float(metrics.get("atr_contraction_ratio"))
        bb_percentile = _as_float(metrics.get("bb_width_20_percentile"))
        volume5 = _as_float(metrics.get("volume_5d_vs_20d"))
        breakout_volume = _as_float(metrics.get("breakout_volume_vs_20d"))
        vpa = volume_price_analysis(item)
        if any(value is not None for value in (volume_ratio, atr_contraction, bb_percentile, volume5, breakout_volume)) or vpa:
            volume_score = 50.0
            if vpa:
                adjustment = int(vpa["score_adjustment"])
                volume_score += adjustment * 4
                volume_evidence.append(f"量價判讀：{vpa['event']}")
            if volume_ratio is not None:
                change = daily_change_pct(item)
                if volume_ratio >= 1.5:
                    volume_score += 12 if change is not None and change > 0 else -8 if change is not None and change < 0 else 4
                elif volume_ratio < 0.6:
                    volume_score -= 5
                volume_evidence.append(f"成交量為 20 日均量 {volume_ratio:.2f} 倍")
            if atr_contraction is not None and atr_contraction <= 0.8:
                squeeze_flags += 1
                volume_score += 6
            if bb_percentile is not None and bb_percentile <= 25:
                squeeze_flags += 1
                volume_score += 6
            if volume5 is not None and volume5 <= 0.8:
                squeeze_flags += 1
                volume_score += 4
            if squeeze_flags:
                volume_evidence.append(f"波動收縮條件符合 {squeeze_flags}/3")
            if breakout_volume is not None and breakout_volume >= 1.5:
                volume_score += 10
                volume_evidence.append(f"突破量達均量 {breakout_volume:.2f} 倍")

    fundamental_evidence: list[str] = []
    fundamental_score: float | None = None
    fundamental_values = {
        "revision": _as_float(metrics.get("fy1_eps_revision_30d")),
        "eps_growth": _as_float(metrics.get("eps_growth_pct")),
        "revenue_growth": _as_float(metrics.get("revenue_growth_pct")),
        "surprise": _as_float(metrics.get("latest_eps_surprise_pct")),
    }
    if item.ticker.has_fundamentals and any(value is not None for value in fundamental_values.values()):
        fundamental_score = 50.0
        ttm_eps = _as_float(metrics.get("ttm_eps"))
        unstable_eps = ttm_eps is not None and ttm_eps <= 0
        if unstable_eps:
            fundamental_score -= 12
            fundamental_evidence.append("近 12 月 EPS 為負，成長率可信度較低")
        revision = fundamental_values["revision"]
        if revision is not None:
            fundamental_score += 22 if revision >= 3 else 12 if revision > 0 else -22 if revision <= -3 else -12
            fundamental_evidence.append(f"FY1 EPS 預估近 30 日調整 {revision:+.1f}%")
        eps_growth = fundamental_values["eps_growth"]
        if eps_growth is not None:
            growth_adjustment = 15 if eps_growth >= 20 else 8 if eps_growth > 0 else -15
            fundamental_score += min(5, growth_adjustment) if unstable_eps and growth_adjustment > 0 else growth_adjustment
            fundamental_evidence.append(f"預估 EPS 成長 {eps_growth:+.1f}%")
        revenue_growth = fundamental_values["revenue_growth"]
        if revenue_growth is not None:
            fundamental_score += 10 if revenue_growth >= 10 else 5 if revenue_growth > 0 else -10
            fundamental_evidence.append(f"預估營收成長 {revenue_growth:+.1f}%")
        surprise = fundamental_values["surprise"]
        if surprise is not None:
            fundamental_score += 8 if surprise >= 5 else 4 if surprise > 0 else -8
            fundamental_evidence.append(f"最近 EPS 驚喜 {surprise:+.1f}%")

    risk_evidence: list[str] = []
    risk_score: float | None = None
    if last is not None or item.warnings or item.ticker.position.status == "holding":
        risk_score = 75.0
        atr_pct = _as_float(metrics.get("atr_20_percent"))
        if atr_pct is not None:
            risk_score += 8 if atr_pct <= 2.5 else -18 if atr_pct >= 8 else -8 if atr_pct >= 5 else 0
            if atr_pct >= 5:
                risk_evidence.append(f"ATR {atr_pct:.1f}% 顯示波動偏高")
        from_high = from_52w_high_pct(item)
        rsi = _as_float(metrics.get("rsi_14"))
        if from_high is not None and from_high >= -2 and rsi is not None and rsi >= 70:
            risk_score -= 12
            risk_evidence.append("接近 52 週高點且 RSI 過熱")
        elif from_high is not None and from_high <= -30:
            risk_score -= 10
            risk_evidence.append(f"距 52 週高點 {from_high:.1f}%")
        daily_change = daily_change_pct(item)
        if daily_change is not None and daily_change <= -5:
            risk_score -= 15
            risk_evidence.append(f"單日下跌 {daily_change:.1f}%")
        valuation_risk = valuation_risk_label(item)
        if valuation_risk in {"High", "Extreme"}:
            risk_score -= 10
            risk_evidence.append("估值容錯空間偏低")
        if item.earnings and item.earnings.earnings_date:
            earnings_days = (item.earnings.earnings_date - anchor).days
            if 0 <= earnings_days <= 3:
                risk_score -= 12
                risk_evidence.append(f"財報事件剩 {earnings_days} 天")
        position = item.ticker.position
        if position.status == "holding" and position.stop_loss is None:
            risk_score -= 12
            risk_evidence.append("持有部位尚未設定停損")
        if item.warnings:
            risk_score -= min(20, len(item.warnings) * 5)
            risk_evidence.append(f"有 {len(item.warnings)} 項資料品質警示")
        if rebuilding:
            risk_score = min(risk_score, 35)
            risk_evidence.insert(0, "價格制度切換，技術指標重建中")
        if not risk_evidence:
            risk_evidence.append("目前未偵測到重大事件或波動風險")

    dimensions = [
        _health_dimension("trend", "趨勢結構", trend_score, trend_evidence),
        _health_dimension("momentum", "相對動能", momentum_score, momentum_evidence),
        _health_dimension("volume", "量價能量", volume_score, volume_evidence),
        _health_dimension("fundamental", "基本面動能", fundamental_score, fundamental_evidence),
        _health_dimension("risk", "風險控制", risk_score, risk_evidence),
    ]
    dimension_map = {str(dimension["key"]): dimension for dimension in dimensions}
    score = _health_average(
        dimensions,
        {"trend": 30, "momentum": 20, "volume": 20, "fundamental": 15, "risk": 15},
    )
    coverage = sum(1 for dimension in dimensions if dimension["available"])

    if rebuilding:
        status, tone = "指標重建中", "warn"
    elif score is None or coverage < 2:
        status, tone = "資料不足", "quiet"
    elif score >= 75:
        status, tone = "強勢", "good"
    elif score >= 62:
        status, tone = "偏多", "good"
    elif score >= 48:
        status, tone = "中性", "mixed"
    elif score >= 35:
        status, tone = "偏弱", "warn"
    else:
        status, tone = "高風險", "danger"

    technical = technical_playbook(item) if not rebuilding else None
    technical_status = str(technical["status"]) if technical else ""
    recent_breakout = _as_float(metrics.get("breakout_days_ago"))
    breakout_hold = _as_float(metrics.get("breakout_hold_pct"))
    breakout_match = bool(
        technical_status == "Breakout confirmed"
        or (
            recent_breakout is not None
            and 0 <= recent_breakout <= 5
            and (breakout_hold is None or breakout_hold >= -1)
        )
    )
    pullback_match = technical_status == "Pullback watch"
    squeeze_match = squeeze_flags >= 2 and bool(dimension_map["trend"]["score"] is not None and int(dimension_map["trend"]["score"]) >= 45)
    fundamental_match = bool(
        dimension_map["fundamental"]["score"] is not None
        and int(dimension_map["fundamental"]["score"]) >= 65
    )
    change = daily_change_pct(item)
    volume_ratio = _as_float(metrics.get("volume_vs_20d"))
    gap = _as_float(metrics.get("gap_percent"))
    move_atr = _as_float(metrics.get("move_vs_atr"))
    unusual_match = bool(
        (change is not None and abs(change) >= 3)
        or (volume_ratio is not None and volume_ratio >= 1.5)
        or (gap is not None and abs(gap) >= 2)
        or (move_atr is not None and abs(move_atr) >= 1.5)
    )
    risk_match = bool(
        rebuilding
        or (dimension_map["risk"]["score"] is not None and int(dimension_map["risk"]["score"]) < 45)
        or technical_status == "Trend weakening"
        or (item.ticker.position.status == "holding" and item.ticker.position.stop_loss is None)
    )
    matches = [
        key
        for key, matched in (
            ("breakout", breakout_match),
            ("pullback", pullback_match),
            ("squeeze", squeeze_match),
            ("fundamental", fundamental_match),
            ("unusual", unusual_match),
            ("risk", risk_match),
        )
        if matched
    ]

    match_reasons: dict[str, str] = {}
    if breakout_match:
        match_reasons["breakout"] = "價格突破且結構仍守在關鍵價位之上"
    if pullback_match:
        match_reasons["pullback"] = "多頭均線未破，價格回到可控的觀察區"
    if squeeze_match:
        match_reasons["squeeze"] = f"波動與量能收縮條件符合 {squeeze_flags}/3"
    if fundamental_match:
        match_reasons["fundamental"] = fundamental_evidence[0] if fundamental_evidence else "基本面動能優於觀察名單"
    if unusual_match:
        unusual_parts: list[str] = []
        if change is not None and abs(change) >= 3:
            unusual_parts.append(f"單日 {change:+.1f}%")
        if volume_ratio is not None and volume_ratio >= 1.5:
            unusual_parts.append(f"量比 {volume_ratio:.2f} 倍")
        if gap is not None and abs(gap) >= 2:
            unusual_parts.append(f"跳空 {gap:+.1f}%")
        if move_atr is not None and abs(move_atr) >= 1.5:
            unusual_parts.append(f"波動 {move_atr:+.1f} ATR")
        match_reasons["unusual"] = "、".join(unusual_parts[:3])
    if risk_match:
        match_reasons["risk"] = risk_evidence[0] if risk_evidence else "風險控制分數偏低"

    if rebuilding:
        action = "等待累積足夠交易日，再使用技術訊號。"
    elif risk_match:
        action = "先處理風險與停損，不新增部位。"
    elif breakout_match:
        action = "確認突破守穩與量能延續，再依計畫分批。"
    elif pullback_match:
        action = "等待回檔止穩，不在下跌途中搶進。"
    elif squeeze_match:
        action = "設好觸發價，等待帶量脫離整理區。"
    elif score is not None and score >= 62:
        action = "列入優先觀察，等價格觸發既定計畫。"
    else:
        action = "維持觀察，暫無需要追價的訊號。"

    return {
        "score": score,
        "status": status,
        "tone": tone,
        "coverage": coverage,
        "dimensions": dimensions,
        "dimension_map": dimension_map,
        "matches": matches,
        "match_reasons": match_reasons,
        "action": action,
        "updated_basis": "產檔時的日線與基本面資料",
    }


def strategy_screener(report: DailyReport, limit_per_market: int = 8) -> dict[str, object]:
    """Rank the watchlist with transparent rules and existing free data."""
    definitions = [
        ("overall", "綜合排行", "依五維健診總分排序，缺少的維度會自動排除後重新加權。"),
        ("breakout", "突破動能", "尋找突破近期關鍵價位，且量價與風險條件仍可控的標的。"),
        ("pullback", "回檔續強", "尋找多頭結構中的健康回檔，不把急跌誤判為便宜。"),
        ("squeeze", "波動收縮", "尋找 ATR、布林帶寬度與量能同步收斂的蓄勢標的。"),
        ("fundamental", "基本面動能", "依 EPS 預估修正、成長與財報驚喜篩選；ETF 與加密貨幣不套用。"),
        ("unusual", "今日異動", "依本次產檔的單日漲跌、量比、跳空與 ATR 異常篩選，並非盤中即時訊號。"),
        ("risk", "風險優先", "先找出趨勢轉弱、波動升高、事件逼近或缺少停損的標的。"),
    ]
    benchmarks = report.market_context.benchmark_returns if report.market_context and report.market_context.benchmark_returns else {}
    candidates: dict[str, dict[str, list[dict[str, object]]]] = {
        key: {} for key, _label, _description in definitions
    }

    for item in report.ticker_reports:
        health = stock_health_diagnostic(item, report.report_date, benchmarks)
        market = _market_bucket(item.ticker.market)
        dimension_map = health["dimension_map"]
        overall_score = health["score"]
        metrics = item.valuation.metrics if item.valuation else {}
        change = daily_change_pct(item)
        volume_ratio = _as_float(metrics.get("volume_vs_20d"))
        gap = _as_float(metrics.get("gap_percent"))
        move_atr = _as_float(metrics.get("move_vs_atr"))

        strategy_scores: dict[str, int] = {}
        if overall_score is not None and int(health["coverage"]) >= 2:
            strategy_scores["overall"] = int(overall_score)
        if "breakout" in health["matches"]:
            strategy_scores["breakout"] = int(round(
                int(dimension_map["trend"]["score"] or 0) * 0.45
                + int(dimension_map["momentum"]["score"] or 0) * 0.25
                + int(dimension_map["volume"]["score"] or 0) * 0.30
            ))
        if "pullback" in health["matches"]:
            strategy_scores["pullback"] = int(round(
                int(dimension_map["trend"]["score"] or 0) * 0.55
                + int(dimension_map["risk"]["score"] or 0) * 0.30
                + int(dimension_map["momentum"]["score"] or 0) * 0.15
            ))
        if "squeeze" in health["matches"]:
            strategy_scores["squeeze"] = min(100, int(dimension_map["trend"]["score"] or 50) + 15)
        if "fundamental" in health["matches"]:
            strategy_scores["fundamental"] = int(dimension_map["fundamental"]["score"] or 0)
        if "unusual" in health["matches"]:
            strategy_scores["unusual"] = min(100, int(round(
                40
                + (abs(change) * 5 if change is not None else 0)
                + (max(0, volume_ratio - 1) * 15 if volume_ratio is not None else 0)
                + (abs(gap) * 3 if gap is not None else 0)
                + (max(0, abs(move_atr) - 1) * 10 if move_atr is not None else 0)
            )))
        if "risk" in health["matches"]:
            risk_score = dimension_map["risk"]["score"]
            strategy_scores["risk"] = 100 - int(risk_score) if risk_score is not None else 80

        for key, strategy_score in strategy_scores.items():
            reason = (
                health["match_reasons"].get(key)
                if key != "overall"
                else "、".join(
                    str(dimension["evidence"][0])
                    for dimension in health["dimensions"]
                    if dimension["available"] and dimension["evidence"]
                )[:120]
            )
            row = {
                "ticker": item.ticker.symbol,
                "display_symbol": item.ticker.display_symbol,
                "company": item.ticker.company_name,
                "market": market,
                "market_label": {"us": "美股", "taiwan": "台股", "crypto": "加密貨幣", "other": "其他"}.get(market, market),
                "score": strategy_score,
                "health": health,
                "reason": reason or "依目前可用資料列入觀察",
                "action": health["action"],
                "anchor": f"ticker-{item.ticker.symbol.lower()}",
            }
            candidates[key].setdefault(market, []).append(row)

    strategies: list[dict[str, object]] = []
    market_order = ("us", "taiwan", "crypto", "other")
    for key, label, description in definitions:
        rows: list[dict[str, object]] = []
        for market in market_order:
            market_rows = sorted(
                candidates[key].get(market, []),
                key=lambda row: (-int(row["score"]), str(row["ticker"])),
            )[:max(1, limit_per_market)]
            for rank, row in enumerate(market_rows, start=1):
                row["rank"] = rank
                rows.append(row)
        strategies.append({"key": key, "label": label, "description": description, "rows": rows})

    return {
        "strategies": strategies,
        "default_strategy": "overall",
        "updated_basis": "使用現有免費資料，於每日報表產生時更新",
    }

def _aligned_ohlcv(item: TickerReport) -> dict[str, list[object]] | None:
    """Return aligned daily OHLCV rows from the cached chart payload."""
    if not item.valuation:
        return None
    metrics = item.valuation.metrics
    raw = {
        "dates": metrics.get("chart_dates_60"),
        "closes": metrics.get("chart_close_60"),
        "highs": metrics.get("chart_high_60"),
        "lows": metrics.get("chart_low_60"),
        "volumes": metrics.get("chart_volume_60"),
    }
    if not all(isinstance(values, list) for values in raw.values()):
        return None
    count = min(len(values) for values in raw.values())
    if count < 2:
        return None

    result: dict[str, list[object]] = {key: [] for key in raw}
    for index in range(count):
        close = _as_float(raw["closes"][index])
        high = _as_float(raw["highs"][index])
        low = _as_float(raw["lows"][index])
        volume = _as_float(raw["volumes"][index])
        if close is None or high is None or low is None or high < low:
            continue
        result["dates"].append(str(raw["dates"][index]))
        result["closes"].append(close)
        result["highs"].append(high)
        result["lows"].append(low)
        result["volumes"].append(volume if volume is not None and volume > 0 else None)
    return result if len(result["closes"]) >= 2 else None


def _true_range_at(highs: list[float], lows: list[float], closes: list[float], index: int) -> float:
    if index <= 0:
        return max(0.0, highs[index] - lows[index])
    return max(
        highs[index] - lows[index],
        abs(highs[index] - closes[index - 1]),
        abs(lows[index] - closes[index - 1]),
    )


def _close_location(high: float, low: float, close: float) -> float:
    spread = high - low
    return (close - low) / spread if spread > 0 else 0.5


def _trend_structure(item: TickerReport, series: dict[str, list[object]]) -> dict[str, object]:
    metrics = item.valuation.metrics if item.valuation else {}
    closes = [float(value) for value in series["closes"]]
    highs = [float(value) for value in series["highs"]]
    lows = [float(value) for value in series["lows"]]
    last = closes[-1]
    sma20 = _as_float(metrics.get("sma_20"))
    sma60 = _as_float(metrics.get("sma_60"))
    sma120 = _as_float(metrics.get("sma_120"))
    slope20 = _as_float(metrics.get("sma_20_slope_5d"))

    evidence: list[str] = []
    bullish_stack = bool(
        sma20 is not None
        and sma60 is not None
        and last > sma20 > sma60
        and (sma120 is None or sma60 > sma120)
    )
    bearish_stack = bool(
        sma20 is not None
        and sma60 is not None
        and last < sma20 < sma60
        and (sma120 is None or sma60 < sma120)
    )

    swing = "mixed"
    if len(closes) >= 20:
        prior_high = max(highs[-20:-10])
        prior_low = min(lows[-20:-10])
        recent_high = max(highs[-10:])
        recent_low = min(lows[-10:])
        if recent_high > prior_high and recent_low > prior_low:
            swing = "up"
            evidence.append("\u8fd1 10 \u65e5\u9ad8\u4f4e\u9ede\u540c\u6b65\u588a\u9ad8")
        elif recent_high < prior_high and recent_low < prior_low:
            swing = "down"
            evidence.append("\u8fd1 10 \u65e5\u9ad8\u4f4e\u9ede\u540c\u6b65\u4e0b\u79fb")
        else:
            evidence.append("\u9ad8\u4f4e\u9ede\u7d50\u69cb\u5c1a\u672a\u540c\u5411")

    if bullish_stack and (slope20 is None or slope20 > 0) and swing != "down":
        label, tone, slug = "\u4e0a\u5347\u8da8\u52e2", "up", "uptrend"
        evidence.insert(0, "\u6536\u76e4\u7ad9\u4e0a 20\uff0f60\uff0f120 \u65e5\u5747\u7dda\u591a\u982d\u6392\u5217")
    elif bearish_stack and (slope20 is None or slope20 < 0) and swing != "up":
        label, tone, slug = "\u4e0b\u964d\u8da8\u52e2", "down", "downtrend"
        evidence.insert(0, "\u6536\u76e4\u8dcc\u7834 20\uff0f60\uff0f120 \u65e5\u5747\u7dda\u7a7a\u982d\u6392\u5217")
    elif slope20 is not None and abs(slope20) <= 0.5 and swing == "mixed":
        label, tone, slug = "\u5340\u9593\u6574\u7406", "mixed", "range"
        evidence.insert(0, "20 \u65e5\u5747\u7dda\u8da8\u5e73\u4e14\u9ad8\u4f4e\u9ede\u672a\u5f62\u6210\u8da8\u52e2")
    else:
        label, tone, slug = "\u8da8\u52e2\u8f49\u63db", "mixed", "transition"
        evidence.insert(0, "\u5747\u7dda\u8207\u9ad8\u4f4e\u9ede\u8a0a\u865f\u5c1a\u672a\u4e00\u81f4")

    if slope20 is not None:
        evidence.append(f"20 \u65e5\u7dda 5 \u65e5\u659c\u7387 {slope20:+.1f}%")
    return {
        "label": label,
        "tone": tone,
        "slug": slug,
        "swing": swing,
        "evidence": evidence[:4],
    }

def volume_price_analysis(item: TickerReport) -> dict[str, object] | None:
    """Classify the latest bar by Wyckoff's effort-versus-result principle."""
    series = _aligned_ohlcv(item)
    if not series or len(series["closes"]) < 21:
        return None
    closes = [float(value) for value in series["closes"]]
    highs = [float(value) for value in series["highs"]]
    lows = [float(value) for value in series["lows"]]
    volumes = [_as_float(value) for value in series["volumes"]]
    current_volume = volumes[-1]
    baseline_volumes = [value for value in volumes[-21:-1] if value is not None and value > 0]
    if current_volume is None or len(baseline_volumes) < 10:
        return None

    prior_ranges = [
        _true_range_at(highs, lows, closes, index)
        for index in range(max(1, len(closes) - 21), len(closes) - 1)
    ]
    prior_ranges = [value for value in prior_ranges if value > 0]
    if not prior_ranges:
        return None

    volume_ratio = current_volume / (sum(baseline_volumes) / len(baseline_volumes))
    true_range = _true_range_at(highs, lows, closes, len(closes) - 1)
    range_ratio = true_range / median(prior_ranges)
    close_location = _close_location(highs[-1], lows[-1], closes[-1])
    prior_high = max(highs[-21:-1])
    prior_low = min(lows[-21:-1])
    range_span = prior_high - prior_low
    range_position = (closes[-1] - prior_low) / range_span if range_span > 0 else 0.5
    change_pct = (closes[-1] - closes[-2]) / closes[-2] * 100.0 if closes[-2] else 0.0
    breakout = closes[-1] > prior_high
    breakdown = closes[-1] < prior_low
    high_volume = volume_ratio >= 1.5
    low_volume = volume_ratio <= 0.7
    wide_spread = range_ratio >= 1.2
    narrow_spread = range_ratio <= 0.7
    trend = _trend_structure(item, series)

    status = "\u91cf\u50f9\u4e2d\u6027"
    event = "\u7b49\u5f85\u5f8c\u7e8c\u50f9\u683c\u78ba\u8a8d"
    tone = "mixed"
    adjustment = 0
    priority = 1

    if breakout:
        if volume_ratio >= 1.2 and range_ratio >= 1.0 and close_location >= 0.65:
            status, event, tone, adjustment, priority = "\u9700\u6c42\u78ba\u8a8d", "\u653e\u91cf\u7a81\u7834", "up", 5, 5
        elif volume_ratio < 1.0 or close_location < 0.55:
            status, event, adjustment, priority = "\u7a81\u7834\u91cf\u80fd\u4e0d\u8db3", "\u4f4e\u54c1\u8cea\u7a81\u7834", -3, 4
        else:
            status, event, priority = "\u7a81\u7834\u5f85\u78ba\u8a8d", "\u7a81\u7834\u4f46\u8b49\u64da\u4e0d\u8db3", 3
    elif breakdown:
        if volume_ratio >= 1.2 and range_ratio >= 1.0 and close_location <= 0.35:
            status, event, tone, adjustment, priority = "\u4f9b\u7d66\u78ba\u8a8d", "\u653e\u91cf\u8dcc\u7834", "down", -5, 5
        elif volume_ratio < 1.0 or close_location > 0.45:
            status, event, adjustment, priority = "\u8dcc\u7834\u672a\u7372\u78ba\u8a8d", "\u4f4e\u91cf\u8dcc\u7834", 0, 4
        else:
            status, event, tone, adjustment, priority = "\u8dcc\u7834\u5f85\u78ba\u8a8d", "\u7d50\u69cb\u8f49\u5f31", "down", -3, 4
    elif high_volume and narrow_spread:
        if range_position <= 0.35 and close_location >= 0.55:
            status, event, priority = "\u4f4e\u6a94\u627f\u63a5\u5019\u9078", "\u9ad8\u91cf\u7a84\u5e45\u5438\u6536", 4
        elif range_position >= 0.65 and close_location <= 0.45:
            status, event, tone, adjustment, priority = "\u9ad8\u6a94\u4f9b\u7d66\u589e\u52a0", "\u9ad8\u91cf\u7a84\u5e45\u6d3e\u767c\u98a8\u96aa", "down", -3, 4
        else:
            status, event, priority = "\u5927\u91cf\u63db\u624b", "\u9ad8\u91cf\u7a84\u5e45\uff0c\u65b9\u5411\u672a\u5b9a", 3
    elif trend["slug"] == "uptrend" and change_pct < 0 and low_volume and range_ratio <= 1.0:
        status, event, tone, adjustment, priority = "\u4f9b\u7d66\u6536\u6582", "\u4e0a\u5347\u8da8\u52e2\u91cf\u7e2e\u56de\u6a94", "up", 3, 3
    elif trend["slug"] == "downtrend" and change_pct > 0 and low_volume:
        status, event, tone, adjustment, priority = "\u9700\u6c42\u4e0d\u8db3", "\u4e0b\u964d\u8da8\u52e2\u4f4e\u91cf\u53cd\u5f48", "down", -3, 3
    elif high_volume and change_pct > 0 and close_location >= 0.65:
        status, event, tone, adjustment, priority = "\u9700\u6c42\u64f4\u5f35", "\u50f9\u6f32\u91cf\u589e", "up", 3, 3
    elif high_volume and change_pct < 0 and close_location <= 0.35:
        status, event, tone, adjustment, priority = "\u4f9b\u7d66\u64f4\u5f35", "\u50f9\u8dcc\u91cf\u589e", "down", -3, 4
    elif wide_spread and low_volume:
        status, event, adjustment, priority = "\u91cf\u50f9\u80cc\u96e2", "\u50f9\u683c\u64f4\u5f35\u4f46\u91cf\u80fd\u672a\u8ddf\u4e0a", -2, 3

    evidence_score = 40
    evidence_score += 15 if high_volume or low_volume else 5
    evidence_score += 15 if wide_spread or narrow_spread else 5
    evidence_score += 10 if close_location >= 0.7 or close_location <= 0.3 else 5
    evidence_score += 10 if breakout or breakdown else 0
    evidence = [
        f"\u6210\u4ea4\u91cf\u70ba\u524d 20 \u65e5\u5747\u91cf {volume_ratio:.2f} \u500d",
        f"\u771f\u5be6\u6ce2\u5e45\u70ba\u8fd1\u671f\u5178\u578b\u6ce2\u5e45 {range_ratio:.2f} \u500d",
        f"\u6536\u76e4\u4f4d\u65bc\u7576\u65e5\u5340\u9593 {close_location * 100:.0f}%",
        f"\u6536\u76e4\u4f4d\u65bc\u524d 20 \u65e5\u5340\u9593 {range_position * 100:.0f}%",
    ]
    return {
        "status": status,
        "event": event,
        "tone": tone,
        "priority": priority,
        "score_adjustment": adjustment,
        "evidence_score": min(90, evidence_score),
        "volume_ratio": round(volume_ratio, 2),
        "range_ratio": round(range_ratio, 2),
        "close_location": round(close_location, 3),
        "range_position": round(range_position, 3),
        "change_pct": round(change_pct, 2),
        "breakout": breakout,
        "breakdown": breakdown,
        "evidence": evidence,
    }

def _wyckoff_event_at(
    closes: list[float],
    highs: list[float],
    lows: list[float],
    volumes: list[float | None],
    index: int,
) -> dict[str, object] | None:
    if index < 20:
        return None
    prior_high = max(highs[index - 20:index])
    prior_low = min(lows[index - 20:index])
    baseline = [value for value in volumes[index - 20:index] if value is not None and value > 0]
    volume_ratio = None
    if volumes[index] is not None and baseline:
        volume_ratio = float(volumes[index]) / (sum(baseline) / len(baseline))
    location = _close_location(highs[index], lows[index], closes[index])

    if lows[index] < prior_low and closes[index] > prior_low and location >= 0.55:
        return {
            "event": "Spring \u5047\u8dcc\u7834",
            "phase": "\u5438\u7c4c\u5019\u9078",
            "tone": "mixed",
            "priority": 5,
            "level": lows[index],
            "evidence": "\u8dcc\u7834\u652f\u6490\u5f8c\u6536\u56de\u5340\u9593\uff0c\u4ecd\u9700\u4f4e\u91cf\u6e2c\u8a66\u78ba\u8a8d",
        }
    if highs[index] > prior_high and closes[index] < prior_high and location <= 0.45:
        return {
            "event": "Upthrust \u5047\u7a81\u7834",
            "phase": "\u6d3e\u767c\u98a8\u96aa",
            "tone": "down",
            "priority": 5,
            "level": highs[index],
            "evidence": "\u7a81\u7834\u58d3\u529b\u5f8c\u6536\u56de\u5340\u9593\uff0c\u986f\u793a\u4e0a\u65b9\u4f9b\u7d66",
        }
    if closes[index] > prior_high and volume_ratio is not None and volume_ratio >= 1.2 and location >= 0.65:
        return {
            "event": "SOS \u5f37\u52e2\u8a0a\u865f",
            "phase": "\u4e0a\u6f32\u6e96\u5099",
            "tone": "up",
            "priority": 5,
            "level": prior_high,
            "evidence": f"\u653e\u91cf {volume_ratio:.2f} \u500d\u7a81\u7834\u5340\u9593\u4e14\u6536\u8fd1\u9ad8\u9ede",
        }
    if closes[index] < prior_low and volume_ratio is not None and volume_ratio >= 1.2 and location <= 0.35:
        return {
            "event": "SOW \u5f31\u52e2\u8a0a\u865f",
            "phase": "\u4e0b\u8dcc\u6e96\u5099",
            "tone": "down",
            "priority": 5,
            "level": prior_low,
            "evidence": f"\u653e\u91cf {volume_ratio:.2f} \u500d\u8dcc\u7834\u5340\u9593\u4e14\u6536\u8fd1\u4f4e\u9ede",
        }
    return None

def wyckoff_structure_analysis(
    item: TickerReport,
    *,
    vpa: dict[str, object] | None = None,
    trend: dict[str, object] | None = None,
) -> dict[str, object] | None:
    """Return conservative Wyckoff phase and event candidates with evidence."""
    series = _aligned_ohlcv(item)
    if not series or len(series["closes"]) < 21:
        return None
    closes = [float(value) for value in series["closes"]]
    highs = [float(value) for value in series["highs"]]
    lows = [float(value) for value in series["lows"]]
    volumes = [_as_float(value) for value in series["volumes"]]
    trend = trend or _trend_structure(item, series)
    vpa = vpa or volume_price_analysis(item)

    detected: dict[str, object] | None = None
    detected_index: int | None = None
    for index in range(len(closes) - 1, max(19, len(closes) - 6), -1):
        event = _wyckoff_event_at(closes, highs, lows, volumes, index)
        if event:
            detected, detected_index = event, index
            break

    evidence: list[str] = []
    if detected:
        event_label = str(detected["event"])
        phase = str(detected["phase"])
        tone = str(detected["tone"])
        priority = int(detected["priority"])
        evidence.append(str(detected["evidence"]))
        if detected_index is not None and detected_index < len(closes) - 1:
            days_ago = len(closes) - 1 - detected_index
            evidence.append(f"\u4e8b\u4ef6\u51fa\u73fe\u5728 {days_ago} \u500b\u4ea4\u6613\u65e5\u524d\uff0c\u7b49\u5f85\u5f8c\u7e8c\u6e2c\u8a66")
    else:
        metrics = item.valuation.metrics if item.valuation else {}
        pivot = _as_float(metrics.get("breakout_pivot"))
        breakout_days = _as_float(metrics.get("breakout_days_ago"))
        current_volume_ratio = _as_float(vpa.get("volume_ratio")) if vpa else None
        if (
            pivot is not None
            and pivot > 0
            and breakout_days is not None
            and 0 <= breakout_days <= 5
            and closes[-1] >= pivot
            and closes[-1] <= pivot * 1.03
            and current_volume_ratio is not None
            and current_volume_ratio <= 1.0
        ):
            event_label, phase, tone, priority = "LPS \u56de\u6e2c\u5019\u9078", "\u4e0a\u6f32\u6e96\u5099", "up", 4
            evidence.append("\u7a81\u7834\u5f8c\u56de\u6e2c\u539f\u58d3\u529b\u5340\uff0c\u6210\u4ea4\u91cf\u4f4e\u65bc 20 \u65e5\u5747\u91cf")
        elif trend["slug"] == "uptrend":
            event_label, phase, tone, priority = "\u5c1a\u7121\u65b0\u7684\u5a01\u79d1\u592b\u4e8b\u4ef6", "\u4e0a\u6f32\u968e\u6bb5", "up", 3
            evidence.append("\u5747\u7dda\u8207\u9ad8\u4f4e\u9ede\u7dad\u6301\u4e0a\u5347\u7d50\u69cb")
        elif trend["slug"] == "downtrend":
            event_label, phase, tone, priority = "\u5c1a\u7121\u6b62\u8dcc\u4e8b\u4ef6", "\u4e0b\u8dcc\u968e\u6bb5", "down", 4
            evidence.append("\u4e0b\u964d\u7d50\u69cb\u5c1a\u672a\u51fa\u73fe Spring \u6216\u9700\u6c42\u78ba\u8a8d")
        elif vpa and vpa["event"] == "\u9ad8\u91cf\u7a84\u5e45\u5438\u6536":
            event_label, phase, tone, priority = "\u5438\u6536\u5019\u9078", "\u5438\u7c4c\u5019\u9078", "mixed", 4
            evidence.append("\u5340\u9593\u4f4e\u6a94\u51fa\u73fe\u9ad8\u91cf\u7a84\u5e45\uff0c\u4ecd\u9700\u7a81\u7834\u78ba\u8a8d")
        elif vpa and vpa["event"] == "\u9ad8\u91cf\u7a84\u5e45\u6d3e\u767c\u98a8\u96aa":
            event_label, phase, tone, priority = "\u4f9b\u7d66\u6e2c\u8a66", "\u6d3e\u767c\u98a8\u96aa", "down", 4
            evidence.append("\u5340\u9593\u9ad8\u6a94\u51fa\u73fe\u9ad8\u91cf\u7a84\u5e45\u8207\u5f31\u6536\u76e4")
        else:
            event_label, phase, tone, priority = "\u5c1a\u7121\u660e\u78ba\u4e8b\u4ef6", "\u5340\u9593\u6574\u7406", "mixed", 1
            evidence.append("\u5c1a\u672a\u51fa\u73fe\u53ef\u9a57\u8b49\u7684 Spring\u3001Upthrust\u3001SOS \u6216 SOW")

    evidence.extend(str(value) for value in trend["evidence"][:2])
    confidence = 45
    confidence += 20 if detected else 0
    confidence += 10 if tone == trend["tone"] and tone != "mixed" else 0
    confidence += 10 if vpa and tone == vpa["tone"] and tone != "mixed" else 0
    return {
        "phase": phase,
        "event": event_label,
        "tone": tone,
        "priority": priority,
        "evidence_score": min(85, confidence),
        "evidence": evidence[:4],
        "candidate": "\u5019\u9078" in phase or "\u5019\u9078" in event_label or "\u98a8\u96aa" in phase,
        "level": detected.get("level") if detected else None,
    }

def adam_reflection_scenario(item: TickerReport, periods: int = 5) -> dict[str, object] | None:
    """Project a short double-reflection path as a scenario, never a score."""
    series = _aligned_ohlcv(item)
    if not series or periods <= 0:
        return None
    closes = [float(value) for value in series["closes"]]
    usable = min(periods, len(closes) - 1)
    if usable < 2 or closes[-1] <= 0:
        return None
    last = closes[-1]
    projection = [round(2 * last - closes[-2 - index], 4) for index in range(usable)]
    if any(value <= 0 for value in projection):
        return None
    change_pct = (projection[-1] - last) / last * 100.0
    if change_pct >= 1.0:
        direction, tone = "\u504f\u591a\u5ef6\u7e8c\u60c5\u5883", "up"
    elif change_pct <= -1.0:
        direction, tone = "\u504f\u7a7a\u5ef6\u7e8c\u60c5\u5883", "down"
    else:
        direction, tone = "\u6a6b\u5411\u5ef6\u7e8c\u60c5\u5883", "mixed"
    return {
        "direction": direction,
        "tone": tone,
        "periods": usable,
        "projection": projection,
        "projected_end": projection[-1],
        "change_pct": round(change_pct, 2),
        "evidence": f"\u6700\u8fd1 {usable} \u500b\u4ea4\u6613\u65e5\u50f9\u683c\u8def\u5f91\u7684\u96d9\u91cd\u53cd\u5c04",
        "note": "\u50c5\u4f5c\u60c5\u5883\u53c3\u8003\uff0c\u6703\u96a8\u6bcf\u65e5\u50f9\u683c\u66f4\u65b0\uff0c\u4e0d\u7d0d\u5165\u53f3\u5074\u5206\u6578",
    }

def trading_framework_analysis(item: TickerReport) -> dict[str, object] | None:
    """Combine trend, Wyckoff, VPA, Adam and operator discipline in one view."""
    series = _aligned_ohlcv(item)
    if not series or len(series["closes"]) < 21:
        return None
    trend = _trend_structure(item, series)
    vpa = volume_price_analysis(item)
    wyckoff = wyckoff_structure_analysis(item, vpa=vpa, trend=trend)
    adam = adam_reflection_scenario(item)
    if not vpa or not wyckoff:
        return None

    metrics = item.valuation.metrics if item.valuation else {}
    technical = technical_playbook(item)
    position_status = item.ticker.position.status
    adverse_event = wyckoff["event"] in {"Upthrust \u5047\u7a81\u7834", "SOW \u5f31\u52e2\u8a0a\u865f"}
    constructive_event = wyckoff["event"] in {"SOS \u5f37\u52e2\u8a0a\u865f", "LPS \u56de\u6e2c\u5019\u9078"}
    spring_candidate = wyckoff["event"] == "Spring \u5047\u8dcc\u7834"
    extended = bool(technical and technical["status"] == "Extended, do not chase")

    if adverse_event or vpa["status"] in {"\u4f9b\u7d66\u78ba\u8a8d", "\u4f9b\u7d66\u64f4\u5f35", "\u9ad8\u6a94\u4f9b\u7d66\u589e\u52a0"}:
        status = "\u4fdd\u8b77\u8cc7\u91d1"
        action = "\u505c\u6b62\u52a0\u78bc\uff1b\u6301\u6709\u90e8\u4f4d\u6aa2\u67e5\u5931\u6548\u50f9\u8207\u6e1b\u78bc\u8a08\u756b"
        tone, priority = "down", 5
    elif trend["slug"] == "downtrend":
        status = "\u66ab\u505c\u9032\u5834"
        action = "\u4e0d\u9810\u6e2c\u5e95\u90e8\uff1b\u7b49\u5f85\u4e0b\u964d\u7d50\u69cb\u626d\u8f49\u8207\u9700\u6c42\u78ba\u8a8d"
        tone, priority = "down", 4
    elif extended:
        status = "\u4e0d\u53ef\u8ffd\u50f9"
        action = "\u4fdd\u7559\u65e2\u6709\u5f37\u52e2\u90e8\u4f4d\uff0c\u7b49\u5f85\u91cf\u7e2e\u56de\u6e2c\u5f8c\u518d\u8a55\u4f30"
        tone, priority = "mixed", 4
    elif spring_candidate:
        status = "\u7b49\u5f85\u6e2c\u8a66"
        action = "Spring \u53ea\u662f\u5019\u9078\uff1b\u7b49\u5f85\u8f03\u4f4e\u91cf\u56de\u6e2c\u4e14\u5b88\u4f4f\u4f4e\u9ede"
        tone, priority = "mixed", 4
    elif constructive_event and vpa["tone"] == "up":
        status = "\u7e8c\u62b1" if position_status == "holding" else "\u7b49\u5f85\u56de\u6e2c"
        action = "\u8da8\u52e2\u8207\u9700\u6c42\u4e00\u81f4\uff1b\u53ea\u5728\u7a81\u7834\u5b88\u7a69\u6216\u4f4e\u91cf\u56de\u6e2c\u5f8c\u9806\u52e2\u52a0\u78bc"
        tone, priority = "up", 5
    elif trend["slug"] == "uptrend":
        status = "\u7e8c\u62b1" if position_status == "holding" else "\u7b49\u5f85\u89f8\u767c"
        action = "\u4e3b\u8da8\u52e2\u4ecd\u5411\u4e0a\uff1b\u672a\u51fa\u73fe\u91cf\u50f9\u89f8\u767c\u524d\u4e0d\u8ffd\u9010\u77ed\u7dda\u6ce2\u52d5"
        tone, priority = "up", 3
    else:
        status = "\u7b49\u5f85\u78ba\u8a8d"
        action = "\u907f\u514d\u5728\u5340\u9593\u4e2d\u6bb5\u4ea4\u6613\uff0c\u7b49\u5f85\u50f9\u683c\u96e2\u958b\u5340\u9593\u4e26\u7531\u6210\u4ea4\u91cf\u78ba\u8a8d"
        tone, priority = "mixed", 2

    pivot = _as_float(metrics.get("breakout_pivot"))
    prior_low = _as_float(metrics.get("prior_20d_low"))
    prior_high = _as_float(metrics.get("prior_20d_high"))
    sma20 = _as_float(metrics.get("sma_20"))
    sma60 = _as_float(metrics.get("sma_60"))
    event_level = _as_float(wyckoff.get("level"))
    if spring_candidate and event_level is not None:
        invalidation, invalidation_label = event_level, "Spring \u4f4e\u9ede"
    elif constructive_event and pivot is not None:
        invalidation, invalidation_label = pivot, "\u7a81\u7834\u652f\u6490"
    elif tone == "up":
        supports = [
            value
            for value in (sma60, prior_low)
            if value is not None and value < float(series["closes"][-1])
        ]
        invalidation = max(supports) if supports else sma20
        invalidation_label = "\u8da8\u52e2\u652f\u6490"
    elif tone == "down":
        invalidation, invalidation_label = sma20 or prior_high, "\u8f49\u5f37\u9580\u6abb"
    else:
        invalidation, invalidation_label = prior_low, "\u5340\u9593\u652f\u6490"

    aligned_tones = [
        value
        for value in (trend["tone"], wyckoff["tone"], vpa["tone"])
        if value != "mixed"
    ]
    agreement = max(
        (aligned_tones.count(value) for value in set(aligned_tones)),
        default=0,
    )
    evidence_count = int(trend["slug"] in {"uptrend", "downtrend"})
    evidence_count += int(
        wyckoff["event"] not in {
            "\u5c1a\u7121\u660e\u78ba\u4e8b\u4ef6",
            "\u5c1a\u7121\u65b0\u7684\u5a01\u79d1\u592b\u4e8b\u4ef6",
            "\u5c1a\u7121\u6b62\u8dcc\u4e8b\u4ef6",
        }
    )
    evidence_count += int(vpa["status"] != "\u91cf\u50f9\u4e2d\u6027")
    evidence_count += int(agreement >= 2)
    evidence_level = "\u9ad8" if evidence_count >= 3 else "\u4e2d" if evidence_count == 2 else "\u4f4e"
    conflict = "up" in aligned_tones and "down" in aligned_tones

    return {
        "trend": trend,
        "wyckoff": wyckoff,
        "vpa": vpa,
        "adam": adam,
        "operator": {
            "status": status,
            "action": action,
            "tone": tone,
            "invalidation": round(invalidation, 4) if invalidation is not None else None,
            "invalidation_label": invalidation_label,
        },
        "tone": tone,
        "priority": priority,
        "evidence_count": evidence_count,
        "evidence_level": evidence_level,
        "conflict": conflict,
        "summary": f"{trend['label']} \u00b7 {wyckoff['phase']} \u00b7 {vpa['status']}",
    }

def _market_alignment_check(item: TickerReport, benchmarks: dict[str, float]) -> dict[str, object] | None:
    profile = relative_strength_profile(item, benchmarks)
    available = int(profile.get("available_horizons", 0))
    if not available:
        return None
    positive = int(profile["positive_horizons"])
    average = float(profile["average_spread"])
    label = str(profile["benchmark_label"])
    detail = f"{label} | {positive}/{available} horizons | {average:+.1f}pp average"
    required = 2 if available >= 2 else 1
    if positive >= required and average > 0:
        return {"label": "Market alignment", "status": "Market and RS aligned", "tone": "up", "passed": True, "detail": detail}
    if average <= -3:
        return {"label": "Market alignment", "status": "Relative strength lagging", "tone": "down", "passed": False, "detail": detail}
    return {"label": "Market alignment", "status": "Market trend weak", "tone": "mixed", "passed": False, "detail": detail}


def right_side_check(
    item: TickerReport,
    *,
    benchmarks: dict[str, float] | None = None,
    portfolio: PortfolioSettings | None = None,
) -> dict[str, object] | None:
    """Return a mechanical right-side checklist with visible entry-risk math."""
    if not item.valuation:
        return None
    metrics = item.valuation.metrics
    if not _technical_regime_ready(item):
        return None
    last = _as_float(metrics.get("last_close"))
    technical_keys = (
        "atr_contraction_ratio", "bb_width_20_percentile", "volume_5d_vs_20d",
        "breakout_days_ago", "prior_20d_low", "atr_20",
    )
    if last is None or last <= 0 or not any(_as_float(metrics.get(key)) is not None for key in technical_keys):
        return None

    atr_ratio = _as_float(metrics.get("atr_contraction_ratio"))
    bb_percentile = _as_float(metrics.get("bb_width_20_percentile"))
    volume_ratio = _as_float(metrics.get("volume_5d_vs_20d"))
    contraction_signals: list[bool] = []
    contraction_detail: list[str] = []
    if atr_ratio is not None:
        contraction_signals.append(atr_ratio <= 0.8)
        contraction_detail.append(f"ATR 10/20 {atr_ratio:.2f}x")
    if bb_percentile is not None:
        contraction_signals.append(bb_percentile <= 25.0)
        contraction_detail.append(f"BB width percentile {bb_percentile:.0f}%")
    if volume_ratio is not None:
        contraction_signals.append(volume_ratio <= 0.8)
        contraction_detail.append(f"5D volume {volume_ratio:.2f}x")
    if len(contraction_signals) >= 2 and sum(contraction_signals) >= 2:
        contraction = {"label": "Volatility contraction", "status": "Base tightening", "tone": "up", "passed": True}
    elif len(contraction_signals) >= 2:
        contraction = {"label": "Volatility contraction", "status": "Base still loose", "tone": "mixed", "passed": False}
    else:
        contraction = {"label": "Volatility contraction", "status": "Base data incomplete", "tone": "mixed", "passed": False}
    contraction["detail"] = " | ".join(contraction_detail) or "N/A"

    breakout_days = _as_float(metrics.get("breakout_days_ago"))
    breakout_pivot = _as_float(metrics.get("breakout_pivot"))
    breakout_hold = _as_float(metrics.get("breakout_hold_pct"))
    breakout_volume = _as_float(metrics.get("breakout_volume_vs_20d"))
    if breakout_days is None or breakout_pivot is None or breakout_hold is None:
        breakout = {
            "label": "Breakout validation", "status": "No recent breakout", "tone": "mixed", "passed": False,
            "detail": "N/A",
        }
    else:
        detail = f"Pivot {_trade_price(breakout_pivot)} | {int(breakout_days)}d | {breakout_hold:+.1f}%"
        if breakout_volume is not None:
            detail += f" | Volume {breakout_volume:.1f}x"
        if breakout_hold < 0:
            breakout = {"label": "Breakout validation", "status": "Breakout failed", "tone": "down", "passed": False, "detail": detail}
        elif breakout_volume is None or breakout_volume < 1.2:
            breakout = {"label": "Breakout validation", "status": "Breakout needs volume", "tone": "mixed", "passed": False, "detail": detail}
        else:
            breakout = {"label": "Breakout validation", "status": "Breakout holding", "tone": "up", "passed": True, "detail": detail}

    planned_stop = _as_float(item.ticker.position.stop_loss) if item.ticker.position else None
    prior_low = _as_float(metrics.get("prior_20d_low"))
    atr_20 = _as_float(metrics.get("atr_20"))
    stop_candidates = [
        candidate
        for candidate in (planned_stop, prior_low, last - 2.0 * atr_20 if atr_20 is not None else None)
        if candidate is not None and 0 < candidate < last
    ]
    if not stop_candidates:
        risk = {
            "label": "Risk box", "status": "Risk box unavailable", "tone": "mixed", "passed": False,
            "detail": "N/A",
        }
    else:
        stop = max(stop_candidates)
        per_unit_risk = last - stop
        risk_pct = per_unit_risk / last * 100.0
        checkpoint = last + 2.0 * per_unit_risk
        detail = (
            f"Entry {_trade_price(last)} | Invalidation {_trade_price(stop)} | "
            f"{risk_pct:.1f}% | 2R checkpoint {_trade_price(checkpoint)}"
        )
        budget = None
        if portfolio:
            budget = portfolio.risk_budget_by_currency.get(item.ticker.currency.upper())
        if budget is not None and per_unit_risk > 0:
            units = int(budget // per_unit_risk)
            detail += f" | Max size {units} units ({item.ticker.currency} {budget:,.0f} risk)"
        if risk_pct <= 5.0:
            risk = {"label": "Risk box", "status": "Risk controlled", "tone": "up", "passed": True, "detail": detail}
        elif risk_pct <= 8.0:
            risk = {"label": "Risk box", "status": "Risk needs smaller size", "tone": "mixed", "passed": False, "detail": detail}
        else:
            risk = {"label": "Risk box", "status": "Risk too wide", "tone": "down", "passed": False, "detail": detail}

    checks = [contraction, breakout, risk]
    market_check = _market_alignment_check(item, benchmarks or {})
    if market_check:
        checks.append(market_check)
    ready_count = sum(1 for check in checks if check["passed"])
    if breakout["tone"] == "down" or risk["tone"] == "down":
        status, tone = "Protect capital first", "down"
    elif ready_count == len(checks):
        status, tone = "Right-side ready", "up"
    elif contraction["passed"] and risk["passed"]:
        status, tone = "Base building", "mixed"
    else:
        status, tone = "Wait for confirmation", "mixed"
    return {
        "status": status,
        "tone": tone,
        "ready_count": ready_count,
        "check_count": len(checks),
        "checks": checks,
    }


def _right_side_signal_validation_report_observations(
    report: DailyReport,
    horizons: tuple[int, ...] = (5, 10, 20),
    minimum_sample: int = 20,
) -> dict[str, object]:
    """Measure completed right-side signals globally and by market."""
    market_by_symbol = {
        item.ticker.symbol: _market_bucket(item.ticker.market)
        for item in report.ticker_reports
    }
    global_outcomes: dict[int, list[float]] = {horizon: [] for horizon in horizons}
    global_pending: dict[int, int] = {horizon: 0 for horizon in horizons}
    known_markets = set(market_by_symbol.values())
    market_outcomes: dict[str, dict[int, list[float]]] = {
        market: {horizon: [] for horizon in horizons}
        for market in known_markets
    }
    market_pending: dict[str, dict[int, int]] = {
        market: {horizon: 0 for horizon in horizons}
        for market in known_markets
    }
    market_recorded: dict[str, int] = {market: 0 for market in known_markets}
    recorded = 0

    for symbol, points in report.ticker_history.items():
        market = market_by_symbol.get(symbol, "other")
        market_outcomes.setdefault(market, {horizon: [] for horizon in horizons})
        market_pending.setdefault(market, {horizon: 0 for horizon in horizons})
        market_recorded.setdefault(market, 0)
        ordered = sorted(points, key=lambda point: (point.report_date, point.generated_at))
        active_signal = False
        for index, point in enumerate(ordered):
            ready = (
                point.right_side_status == "Right-side ready"
                and point.last_close is not None
                and point.last_close > 0
            )
            if not ready:
                active_signal = False
                continue
            if active_signal:
                continue
            active_signal = True
            recorded += 1
            market_recorded[market] += 1
            for horizon in horizons:
                if index + horizon >= len(ordered):
                    global_pending[horizon] += 1
                    market_pending[market][horizon] += 1
                    continue
                exit_price = ordered[index + horizon].last_close
                if exit_price is None or exit_price <= 0:
                    global_pending[horizon] += 1
                    market_pending[market][horizon] += 1
                    continue
                outcome = (exit_price - point.last_close) / point.last_close * 100.0
                global_outcomes[horizon].append(outcome)
                market_outcomes[market][horizon].append(outcome)

    def rows_for(
        outcomes: dict[int, list[float]],
        pending: dict[int, int],
    ) -> list[dict[str, object]]:
        rows: list[dict[str, object]] = []
        for horizon in horizons:
            values = outcomes[horizon]
            sample_size = len(values)
            rows.append({
                "sessions": horizon,
                "sample_size": sample_size,
                "minimum_sample": minimum_sample,
                "reliable": sample_size >= minimum_sample,
                "win_rate": round(sum(value > 0 for value in values) / sample_size * 100.0, 1) if values else None,
                "average_return": round(sum(values) / sample_size, 2) if values else None,
                "pending": pending[horizon],
            })
        return rows

    labels = {
        "us": "US",
        "taiwan": "Taiwan",
        "crypto": "Crypto",
        "other": "Other",
    }
    markets = [
        {
            "key": market,
            "label": labels.get(market, market.upper()),
            "signals_recorded": market_recorded.get(market, 0),
            "horizons": rows_for(outcomes, market_pending[market]),
        }
        for market, outcomes in market_outcomes.items()
    ]
    order = {"us": 0, "taiwan": 1, "crypto": 2, "other": 3}
    markets.sort(key=lambda row: order.get(str(row["key"]), 9))
    return {
        "signals_recorded": recorded,
        "minimum_sample": minimum_sample,
        "horizons": rows_for(global_outcomes, global_pending),
        "markets": markets,
    }


def _ticker_price_sessions(item: TickerReport | None) -> list[tuple[date, float]]:
    if item is None or not item.valuation:
        return []
    dates = item.valuation.metrics.get("chart_dates_60")
    closes = item.valuation.metrics.get("chart_close_60")
    if not isinstance(dates, list) or not isinstance(closes, list):
        return []
    by_date: dict[date, float] = {}
    for raw_date, raw_close in zip(dates, closes):
        try:
            session_date = date.fromisoformat(str(raw_date)[:10])
        except ValueError:
            continue
        close = _as_float(raw_close)
        if close is not None and close > 0:
            by_date[session_date] = close
    return sorted(by_date.items())


def right_side_signal_validation(
    report: DailyReport,
    horizons: tuple[int, ...] = (5, 10, 20),
    minimum_sample: int = 30,
) -> dict[str, object]:
    """Validate entry signals against exchange sessions and risk-normalized outcomes."""
    items = {item.ticker.symbol: item for item in report.ticker_reports}
    market_by_symbol = {
        symbol: _market_bucket(item.ticker.market)
        for symbol, item in items.items()
    }
    known_markets = set(market_by_symbol.values())

    def empty_outcomes() -> dict[int, list[dict[str, float | None]]]:
        return {horizon: [] for horizon in horizons}

    global_outcomes = empty_outcomes()
    global_pending = {horizon: 0 for horizon in horizons}
    global_unavailable = {horizon: 0 for horizon in horizons}
    market_outcomes = {market: empty_outcomes() for market in known_markets}
    market_pending = {
        market: {horizon: 0 for horizon in horizons}
        for market in known_markets
    }
    market_unavailable = {
        market: {horizon: 0 for horizon in horizons}
        for market in known_markets
    }
    market_recorded = {market: 0 for market in known_markets}
    recorded = 0

    for symbol, points in report.ticker_history.items():
        item = items.get(symbol)
        market = market_by_symbol.get(symbol, "other")
        market_outcomes.setdefault(market, empty_outcomes())
        market_pending.setdefault(market, {horizon: 0 for horizon in horizons})
        market_unavailable.setdefault(market, {horizon: 0 for horizon in horizons})
        market_recorded.setdefault(market, 0)
        sessions = _ticker_price_sessions(item)
        ordered = sorted(points, key=lambda point: (point.report_date, point.generated_at))
        active_signal = False
        for point in ordered:
            ready = (
                point.right_side_status == "Right-side ready"
                and point.last_close is not None
                and point.last_close > 0
            )
            if not ready:
                active_signal = False
                continue
            if active_signal:
                continue
            active_signal = True
            recorded += 1
            market_recorded[market] += 1

            entry_price = point.signal_entry or point.last_close
            prior_indices = [
                index
                for index, (session_date, _close) in enumerate(sessions)
                if session_date <= point.report_date
            ]
            if not prior_indices:
                for horizon in horizons:
                    global_unavailable[horizon] += 1
                    market_unavailable[market][horizon] += 1
                continue
            entry_index = prior_indices[-1]
            for horizon in horizons:
                exit_index = entry_index + horizon
                if exit_index >= len(sessions):
                    global_pending[horizon] += 1
                    market_pending[market][horizon] += 1
                    continue
                exit_price = sessions[exit_index][1]
                return_pct = (exit_price - entry_price) / entry_price * 100.0
                risk_pct = point.signal_risk_pct
                r_multiple = (
                    return_pct / risk_pct
                    if risk_pct is not None and risk_pct > 0
                    else None
                )
                outcome = {"return": return_pct, "r": r_multiple}
                global_outcomes[horizon].append(outcome)
                market_outcomes[market][horizon].append(outcome)

    def rows_for(
        outcomes: dict[int, list[dict[str, float | None]]],
        pending: dict[int, int],
        unavailable: dict[int, int],
    ) -> list[dict[str, object]]:
        rows: list[dict[str, object]] = []
        for horizon in horizons:
            values = [float(row["return"]) for row in outcomes[horizon]]
            r_values = [
                float(row["r"])
                for row in outcomes[horizon]
                if row["r"] is not None
            ]
            wins = [value for value in values if value > 0]
            losses = [value for value in values if value <= 0]
            sample_size = len(values)
            average_win = sum(wins) / len(wins) if wins else None
            average_loss = sum(losses) / len(losses) if losses else None
            payoff_ratio = (
                average_win / abs(average_loss)
                if average_win is not None and average_loss not in (None, 0)
                else None
            )
            rows.append({
                "sessions": horizon,
                "sample_size": sample_size,
                "minimum_sample": minimum_sample,
                "reliable": sample_size >= minimum_sample,
                "win_rate": round(len(wins) / sample_size * 100.0, 1) if values else None,
                "average_return": round(sum(values) / sample_size, 2) if values else None,
                "median_return": round(median(values), 2) if values else None,
                "average_win": round(average_win, 2) if average_win is not None else None,
                "average_loss": round(average_loss, 2) if average_loss is not None else None,
                "payoff_ratio": round(payoff_ratio, 2) if payoff_ratio is not None else None,
                "expectancy_r": round(sum(r_values) / len(r_values), 2) if r_values else None,
                "median_r": round(median(r_values), 2) if r_values else None,
                "r_sample_size": len(r_values),
                "worst_return": round(min(values), 2) if values else None,
                "pending": pending[horizon],
                "unavailable": unavailable[horizon],
                "basis": "exchange_sessions",
            })
        return rows

    labels = {"us": "US", "taiwan": "Taiwan", "crypto": "Crypto", "other": "Other"}
    order = {"us": 0, "taiwan": 1, "crypto": 2, "other": 3}
    markets = [
        {
            "key": market,
            "label": labels.get(market, market.upper()),
            "signals_recorded": market_recorded.get(market, 0),
            "horizons": rows_for(
                outcomes,
                market_pending[market],
                market_unavailable[market],
            ),
        }
        for market, outcomes in market_outcomes.items()
    ]
    markets.sort(key=lambda row: order.get(str(row["key"]), 9))
    return {
        "signals_recorded": recorded,
        "minimum_sample": minimum_sample,
        "basis": "exchange_sessions",
        "horizons": rows_for(global_outcomes, global_pending, global_unavailable),
        "markets": markets,
    }


def _market_bucket(market: str) -> str:
    if market in {"twse", "tpex", "taiwan"}:
        return "taiwan"
    if market == "crypto":
        return "crypto"
    return "us" if market == "us" else "other"


def right_side_execution_plan(report: DailyReport, item: TickerReport) -> dict[str, object] | None:
    """Turn the right-side checklist into a price, risk, and gate plan."""
    if not item.valuation:
        return None
    metrics = item.valuation.metrics
    if not _technical_regime_ready(item):
        return None
    last = _metric_float(item, "last_close")
    if last is None or last <= 0:
        return None

    state = research_state_for(report, item.ticker.symbol)
    pivot = _metric_float(item, "breakout_pivot")
    prior_high = _metric_float(item, "prior_20d_high")
    trigger = pivot or prior_high
    entry_reference = max(last, trigger) if trigger is not None else last

    planned_levels = _plausible_levels(
        _parse_price_levels(state.stop_loss),
        last,
    )
    planned_stop = item.ticker.position.stop_loss
    if planned_levels:
        planned_stop = max(planned_levels)
    atr = _metric_float(item, "atr_20")
    prior_low = _metric_float(item, "prior_20d_low")
    stop_candidates = [
        value
        for value in (
            planned_stop,
            prior_low,
            last - 2.0 * atr if atr is not None else None,
        )
        if value is not None and 0 < value < entry_reference
    ]
    stop = max(stop_candidates) if stop_candidates else None
    per_unit_risk = entry_reference - stop if stop is not None else None
    risk_pct = per_unit_risk / entry_reference * 100.0 if per_unit_risk and entry_reference else None
    target_2r = entry_reference + 2.0 * per_unit_risk if per_unit_risk else None

    portfolio = report.settings.portfolio if report.settings else None
    currency = item.ticker.currency.upper()
    risk_budget = portfolio.risk_budget_by_currency.get(currency) if portfolio else None
    account_risk = portfolio_risk_overview(report)
    risk_used = sum(
        float(row["combined_risk"])
        for row in account_risk["currencies"]
        if row["currency"] == currency
    )
    risk_available = max(0.0, risk_budget - risk_used) if risk_budget is not None else None
    max_units = (
        int(risk_available // per_unit_risk)
        if risk_available is not None and per_unit_risk
        else None
    )
    portfolio_passed = risk_available is None or (
        per_unit_risk is not None and risk_available >= per_unit_risk
    )
    portfolio_gate = {
        "key": "portfolio",
        "label": "Portfolio heat",
        "passed": portfolio_passed,
        "required": risk_budget is not None,
        "tone": "up" if portfolio_passed else "down",
        "detail": (
            f"{currency} \u5df2\u4f7f\u7528 {risk_used:,.0f} / \u9810\u7b97 {risk_budget:,.0f}\uff1b\u53ef\u7528 {risk_available:,.0f}"
            if risk_budget is not None and risk_available is not None
            else "\u5c1a\u672a\u8a2d\u5b9a\u5e33\u6236\u98a8\u96aa\u9810\u7b97"
        ),
    }

    dq = data_quality_confidence(
        item,
        report.report_date,
        premarket_move=premarket_move_for(report, item.ticker.symbol),
    )
    quality_passed = int(dq["score"]) >= 80
    quality_gate = {
        "key": "quality",
        "label": "Data quality",
        "passed": quality_passed,
        "required": True,
        "tone": "up" if quality_passed else "down",
        "detail": f"{dq['score']}/100",
    }

    earnings_days = earnings_delta(item, report.report_date)
    event_passed = earnings_days is None or earnings_days > 3 or earnings_days < 0
    event_detail = "\u4e09\u65e5\u5167\u7121\u8ca1\u5831" if event_passed else f"{earnings_days} \u65e5\u5f8c\u8ca1\u5831"
    event_gate = {
        "key": "event",
        "label": "Event risk",
        "passed": event_passed,
        "required": True,
        "tone": "up" if event_passed else "down",
        "detail": event_detail,
    }

    avg_dollar_volume = _metric_float(item, "avg_dollar_volume_20d")
    order_notional = entry_reference * max_units if max_units is not None and max_units > 0 else None
    order_adv_pct = (
        order_notional / avg_dollar_volume * 100.0
        if order_notional is not None and avg_dollar_volume
        else None
    )
    days_to_liquidate = (
        order_notional / (avg_dollar_volume * 0.10)
        if order_notional is not None and avg_dollar_volume
        else None
    )
    estimated_slippage_bps = (
        min(50.0, max(2.0, 2.0 + order_adv_pct * 10.0))
        if order_adv_pct is not None
        else None
    )
    liquidity_required = max_units is not None and max_units > 0
    liquidity_passed = bool(order_adv_pct is not None and order_adv_pct <= 1.0)
    liquidity_gate = {
        "key": "liquidity",
        "label": "Liquidity",
        "passed": liquidity_passed,
        "required": liquidity_required,
        "tone": "up" if liquidity_passed else ("down" if liquidity_required else "mixed"),
        "detail": (
            f"\u9810\u4f30\u8a02\u55ae\u4f54 20D \u5e73\u5747\u6210\u4ea4\u984d {order_adv_pct:.2f}%\uff1b\u4ee5 10% \u53c3\u8207\u7387\u9700 {days_to_liquidate:.2f} \u500b\u4ea4\u6613\u65e5"
            if order_adv_pct is not None and days_to_liquidate is not None
            else "\u8a2d\u5b9a\u5e33\u6236\u98a8\u96aa\u9810\u7b97\u5f8c\uff0c\u624d\u80fd\u4f30\u7b97\u8a02\u55ae\u6d41\u52d5\u6027"
        ),
    }

    risk_passed = per_unit_risk is not None and risk_pct is not None and risk_pct <= 8.0
    risk_gate = {
        "key": "risk",
        "label": "Defined risk",
        "passed": risk_passed,
        "required": True,
        "tone": "up" if risk_passed else "down",
        "detail": f"\u8ddd\u5931\u6548\u50f9 {risk_pct:.1f}%" if risk_pct is not None else "\u7121\u6709\u6548\u5931\u6548\u50f9",
    }

    chase_pct = (last - trigger) / trigger * 100.0 if trigger else None
    chase_passed = chase_pct is None or chase_pct <= 5.0
    chase_gate = {
        "key": "chase",
        "label": "Entry discipline",
        "passed": chase_passed,
        "required": True,
        "tone": "up" if chase_passed else "down",
        "detail": f"\u8ddd\u89f8\u767c\u50f9 {chase_pct:+.1f}%" if chase_pct is not None else "\u89f8\u767c\u50f9\u7121\u8cc7\u6599",
    }

    benchmarks = report.market_context.benchmark_returns if report.market_context else {}
    profile = relative_strength_profile(item, benchmarks)
    market_available = bool(profile)
    market_passed = bool(
        market_available
        and float(profile.get("average_spread", 0.0)) > 0
        and int(profile.get("positive_horizons", 0)) >= min(2, int(profile.get("available_horizons", 0)))
    )
    market_gate = {
        "key": "market",
        "label": "Market and RS",
        "passed": market_passed,
        "required": market_available,
        "tone": "up" if market_passed else "mixed",
        "detail": (
            f"{profile.get('positive_horizons', 0)}/{profile.get('available_horizons', 0)} \u500b\u9031\u671f\u5f37\u65bc\u57fa\u6e96\uff0c"
            f"{float(profile.get('average_spread', 0.0)):+.1f}pp"
            if market_available
            else "\u57fa\u6e96\u6b77\u53f2\u7121\u8cc7\u6599"
        ),
    }

    group_gate = _sector_alignment_gate(report, item)
    checklist = right_side_check(item, benchmarks=benchmarks, portfolio=portfolio)
    structure_passed = bool(checklist and checklist.get("status") == "Right-side ready")
    structure_gate = {
        "key": "structure",
        "label": "Price structure",
        "passed": structure_passed,
        "required": True,
        "tone": str(checklist.get("tone", "mixed")) if checklist else "mixed",
        "detail": str(checklist.get("status", "\u50f9\u683c\u7d50\u69cb\u8cc7\u6599\u4e0d\u8db3")) if checklist else "\u50f9\u683c\u7d50\u69cb\u8cc7\u6599\u4e0d\u8db3",
    }

    gates = [structure_gate, market_gate, group_gate, portfolio_gate, liquidity_gate, risk_gate, event_gate, quality_gate, chase_gate]
    failed_required = [gate for gate in gates if gate["required"] and not gate["passed"]]
    hard_blockers = {"quality", "event", "portfolio", "liquidity", "risk", "chase"}
    if any(gate["key"] in hard_blockers for gate in failed_required):
        status, tone = "blocked", "down"
    elif not failed_required:
        status, tone = "ready", "up"
    else:
        status, tone = "watch", "mixed"

    return {
        "status": status,
        "tone": tone,
        "entry_trigger": trigger,
        "entry_reference": entry_reference,
        "invalidation": stop,
        "risk_per_unit": per_unit_risk,
        "risk_pct": risk_pct,
        "target_2r": target_2r,
        "risk_budget": risk_budget,
        "risk_used": round(risk_used, 2),
        "risk_available": round(risk_available, 2) if risk_available is not None else None,
        "stress_risk_per_unit": (
            per_unit_risk + max(atr or 0.0, entry_reference * 0.03)
            if per_unit_risk is not None
            else None
        ),
        "order_notional": order_notional,
        "order_adv_pct": order_adv_pct,
        "days_to_liquidate": days_to_liquidate,
        "estimated_slippage_bps": estimated_slippage_bps,
        "max_units": max_units,
        "currency": item.ticker.currency,
        "gates": gates,
        "failed_count": len(failed_required),
        "data_source": item.valuation.source,
        "data_as_of": item.valuation.as_of_date,
        "data_retrieved_at": item.valuation.retrieved_at,
    }


def _sector_alignment_gate(report: DailyReport, item: TickerReport) -> dict[str, object]:
    display_symbol = item.ticker.display_symbol
    ticker_return = _metric_float(item, "return_20d")
    benchmarks = report.market_context.benchmark_returns if report.market_context else {}
    profile_text = " ".join(
        str(item.valuation.metrics.get(key, ""))
        for key in ("sector", "industry")
    ).lower() if item.valuation else ""
    market = _market_bucket(item.ticker.market)
    if market == "taiwan":
        benchmark_key, benchmark_label = "twii", "TWII"
    elif market == "crypto":
        benchmark_key, benchmark_label = "btc", "BTC"
    elif "semiconductor" in profile_text:
        benchmark_key, benchmark_label = "soxx", "SOXX"
    elif any(value in profile_text for value in ("technology", "software", "internet")):
        benchmark_key, benchmark_label = "qqq", "QQQ"
    else:
        benchmark_key, benchmark_label = "spy", "SPY"
    benchmark_return = _as_float(benchmarks.get(f"{benchmark_key}_20d"))

    for row in sector_leadership(report):
        tiles = row.get("tiles", [])
        symbols = {str(tile.get("symbol")) for tile in tiles}
        if display_symbol not in symbols:
            continue
        peer_returns = [
            value
            for tile in tiles
            if str(tile.get("symbol")) != display_symbol
            if (value := _as_float(tile.get("ret_20d"))) is not None
        ]
        peer_return = sum(peer_returns) / len(peer_returns) if peer_returns else None
        comparison_returns = [
            value for value in (peer_return, benchmark_return) if value is not None
        ]
        available = ticker_return is not None and bool(comparison_returns)
        passed = bool(available and all(ticker_return >= value for value in comparison_returns))
        comparison_parts = []
        if peer_return is not None:
            comparison_parts.append(f"\u89c0\u5bdf\u6e05\u55ae\u540c\u65cf\u7fa4 {peer_return:+.1f}%")
        if benchmark_return is not None:
            comparison_parts.append(f"{benchmark_label} {benchmark_return:+.1f}%")
        group_detail = (
            f"{row.get('label_zh', row.get('label', 'Group'))}: \u500b\u80a1 {ticker_return:+.1f}% / "
            + " / ".join(comparison_parts)
        ) if available else f"{row.get('label_zh', row.get('label', 'Group'))}: \u6bd4\u8f03\u8cc7\u6599\u4e0d\u8db3"
        return {
            "key": "group",
            "label": "Industry group",
            "passed": passed,
            "required": available,
            "tone": "up" if passed else "mixed",
            "detail": group_detail,
        }
    if ticker_return is not None and benchmark_return is not None:
        passed = ticker_return >= benchmark_return
        return {
            "key": "group",
            "label": "Industry group",
            "passed": passed,
            "required": True,
            "tone": "up" if passed else "mixed",
            "detail": f"ticker {ticker_return:+.1f}% / {benchmark_label} {benchmark_return:+.1f}%",
        }
    return {
        "key": "group",
        "label": "Industry group",
        "passed": False,
        "required": False,
        "tone": "mixed",
        "detail": "\u89c0\u5bdf\u6e05\u55ae\u5167\u7121\u53ef\u6bd4\u8f03\u65cf\u7fa4",
    }


def _trade_journal_summary_legacy(report: DailyReport, minimum_sample: int = 20) -> dict[str, object]:
    """Compute P/L, R, MFE, and MAE for persisted trade-journal entries."""
    items = {item.ticker.symbol: item for item in report.ticker_reports}
    rows: list[dict[str, object]] = []
    for trade in report.trade_journal:
        if trade.status == "cancelled":
            continue
        item = items.get(trade.ticker)
        last = _metric_float(item, "last_close") if item else None
        closed = trade.status == "closed" and trade.exit_price is not None
        mark_price = trade.exit_price if closed else last
        shares = trade.shares if trade.shares is not None and trade.shares > 0 else None
        per_unit_risk = None
        planned_risk = None
        if (
            trade.entry_price is not None
            and trade.initial_stop is not None
            and trade.entry_price > trade.initial_stop
        ):
            per_unit_risk = trade.entry_price - trade.initial_stop
            if shares is not None:
                planned_risk = per_unit_risk * shares

        gross_pl = None
        net_pl = None
        r_multiple = None
        if trade.entry_price is not None and mark_price is not None and shares is not None:
            gross_pl = (mark_price - trade.entry_price) * shares
            net_pl = gross_pl - trade.fees
            if planned_risk:
                r_multiple = net_pl / planned_risk

        end_date = trade.exit_date if closed and trade.exit_date else report.report_date
        holding_days = (
            max(0, (end_date - trade.entry_date).days)
            if trade.entry_date is not None
            else None
        )
        extremes = _trade_path_extremes(item, trade.entry_date, end_date) if item else {}
        mfe_r = mae_r = None
        if trade.entry_price is not None and per_unit_risk:
            high = _as_float(extremes.get("high"))
            low = _as_float(extremes.get("low"))
            if high is not None:
                mfe_r = (high - trade.entry_price) / per_unit_risk
            if low is not None:
                mae_r = (low - trade.entry_price) / per_unit_risk

        rows.append({
            "trade": trade,
            "item": item,
            "closed": closed,
            "mark_price": round(mark_price, 4) if mark_price is not None else None,
            "planned_risk": round(planned_risk, 2) if planned_risk is not None else None,
            "gross_pl": round(gross_pl, 2) if gross_pl is not None else None,
            "net_pl": round(net_pl, 2) if net_pl is not None else None,
            "r_multiple": round(r_multiple, 2) if r_multiple is not None else None,
            "mfe_r": round(mfe_r, 2) if mfe_r is not None else None,
            "mae_r": round(mae_r, 2) if mae_r is not None else None,
            "holding_days": holding_days,
            "path_complete": bool(extremes.get("complete", False)),
        })

    closed_rows = [row for row in rows if row["closed"] and row["r_multiple"] is not None]
    wins = [row for row in closed_rows if float(row["r_multiple"]) > 0]
    average_r = (
        sum(float(row["r_multiple"]) for row in closed_rows) / len(closed_rows)
        if closed_rows
        else None
    )
    total_r = sum(float(row["r_multiple"]) for row in closed_rows) if closed_rows else None

    losing_streak = max_losing_streak = 0
    ordered_closed = sorted(
        closed_rows,
        key=lambda row: (
            row["trade"].exit_date or date.min,
            row["trade"].trade_id,
        ),
    )
    for row in ordered_closed:
        if float(row["r_multiple"]) <= 0:
            losing_streak += 1
            max_losing_streak = max(max_losing_streak, losing_streak)
        else:
            losing_streak = 0

    market_stats: list[dict[str, object]] = []
    for market in ("us", "taiwan", "crypto", "other"):
        market_rows = [
            row
            for row in closed_rows
            if _market_bucket(str(row["trade"].market)) == market
        ]
        if not market_rows:
            continue
        market_stats.append({
            "market": market,
            "sample_size": len(market_rows),
            "win_rate": round(sum(float(row["r_multiple"]) > 0 for row in market_rows) / len(market_rows) * 100.0, 1),
            "average_r": round(sum(float(row["r_multiple"]) for row in market_rows) / len(market_rows), 2),
            "reliable": len(market_rows) >= minimum_sample,
        })

    rows.sort(
        key=lambda row: (
            row["closed"],
            row["trade"].entry_date or date.min,
            row["trade"].trade_id,
        ),
        reverse=True,
    )
    return {
        "rows": rows,
        "open_count": sum(not row["closed"] for row in rows),
        "closed_count": sum(row["closed"] for row in rows),
        "measured_count": len(closed_rows),
        "win_rate": round(len(wins) / len(closed_rows) * 100.0, 1) if closed_rows else None,
        "average_r": round(average_r, 2) if average_r is not None else None,
        "total_r": round(total_r, 2) if total_r is not None else None,
        "max_losing_streak": max_losing_streak,
        "minimum_sample": minimum_sample,
        "reliable": len(closed_rows) >= minimum_sample,
        "market_stats": market_stats,
    }


def _normalized_trade_fills(trade: TradeJournalEntry) -> list[TradeFill]:
    valid = [
        fill
        for fill in trade.fills
        if fill.side in {"buy", "sell"}
        and fill.price is not None
        and fill.price > 0
        and fill.shares is not None
        and fill.shares > 0
    ]
    if valid:
        return sorted(valid, key=lambda fill: (fill.fill_date or date.min, fill.fill_id))
    fills: list[TradeFill] = []
    if trade.entry_price and trade.shares and trade.shares > 0:
        fills.append(TradeFill(
            fill_id=f"{trade.trade_id}-entry",
            side="buy",
            fill_date=trade.entry_date,
            price=trade.entry_price,
            shares=trade.shares,
        ))
    if trade.exit_price and trade.shares and trade.shares > 0:
        fills.append(TradeFill(
            fill_id=f"{trade.trade_id}-exit",
            side="sell",
            fill_date=trade.exit_date,
            price=trade.exit_price,
            shares=trade.shares,
        ))
    return fills


def _trade_lifecycle_metrics(
    trade: TradeJournalEntry,
    mark_price: float | None,
) -> dict[str, object]:
    if trade.status == "planned":
        shares = trade.shares if trade.shares is not None and trade.shares > 0 else None
        planned_risk = trade.initial_risk
        if (
            planned_risk is None
            and shares is not None
            and trade.entry_price is not None
            and trade.initial_stop is not None
            and trade.entry_price > trade.initial_stop
        ):
            planned_risk = (trade.entry_price - trade.initial_stop) * shares
        return {
            "planned": True,
            "closed": False,
            "average_entry": trade.entry_price,
            "average_exit": None,
            "bought_shares": shares or 0.0,
            "sold_shares": 0.0,
            "remaining_shares": 0.0,
            "planned_shares": shares,
            "initial_risk": planned_risk,
            "current_risk": 0.0,
            "gross_pl": None,
            "net_pl": None,
            "net_pl_base": None,
            "fees_total": trade.fees,
            "fill_count": 0,
            "entry_date": trade.entry_date,
            "exit_date": None,
            "current_stop": trade.current_stop or trade.initial_stop,
        }

    fills = _normalized_trade_fills(trade)
    buys = [fill for fill in fills if fill.side == "buy"]
    sells = [fill for fill in fills if fill.side == "sell"]
    bought_shares = sum(float(fill.shares or 0.0) for fill in buys)
    raw_sold_shares = sum(float(fill.shares or 0.0) for fill in sells)
    sold_shares = min(bought_shares, raw_sold_shares)
    remaining_shares = max(0.0, bought_shares - sold_shares)
    buy_cost = sum(float(fill.price or 0.0) * float(fill.shares or 0.0) for fill in buys)
    sell_proceeds = sum(float(fill.price or 0.0) * float(fill.shares or 0.0) for fill in sells)
    average_entry = buy_cost / bought_shares if bought_shares else None
    average_exit = sell_proceeds / raw_sold_shares if raw_sold_shares else None
    if raw_sold_shares > bought_shares and average_exit is not None:
        sell_proceeds = average_exit * sold_shares

    gross_pl = None
    if average_entry is not None:
        realized = (
            (average_exit - average_entry) * sold_shares
            if average_exit is not None
            else 0.0
        )
        unrealized = (
            (mark_price - average_entry) * remaining_shares
            if mark_price is not None and remaining_shares > 0
            else 0.0
        )
        gross_pl = realized + unrealized
    fees_total = trade.fees + sum(float(fill.fees or 0.0) for fill in fills)
    net_pl = gross_pl - fees_total if gross_pl is not None else None

    initial_risk = trade.initial_risk
    if initial_risk is None and trade.initial_stop is not None:
        initial_risk = sum(
            max(0.0, float(fill.price or 0.0) - trade.initial_stop)
            * float(fill.shares or 0.0)
            for fill in buys
        ) or None
    current_stop = trade.current_stop or trade.initial_stop
    current_risk = None
    if mark_price is not None and current_stop is not None and remaining_shares > 0:
        current_risk = max(0.0, mark_price - current_stop) * remaining_shares
    closed = (
        trade.status == "closed"
        or (bought_shares > 0 and remaining_shares <= max(1e-8, bought_shares * 1e-8))
    )
    entry_dates = [fill.fill_date for fill in buys if fill.fill_date is not None]
    exit_dates = [fill.fill_date for fill in sells if fill.fill_date is not None]
    fx_rate = trade.fx_rate_to_base if trade.fx_rate_to_base > 0 else 1.0
    return {
        "planned": False,
        "closed": closed,
        "average_entry": average_entry,
        "average_exit": average_exit,
        "bought_shares": bought_shares,
        "sold_shares": sold_shares,
        "remaining_shares": remaining_shares,
        "planned_shares": None,
        "initial_risk": initial_risk,
        "current_risk": current_risk,
        "gross_pl": gross_pl,
        "net_pl": net_pl,
        "net_pl_base": net_pl * fx_rate if net_pl is not None else None,
        "fees_total": fees_total,
        "fill_count": len(fills),
        "entry_date": min(entry_dates) if entry_dates else trade.entry_date,
        "exit_date": max(exit_dates) if exit_dates else trade.exit_date,
        "current_stop": current_stop,
    }


def trade_journal_summary(report: DailyReport, minimum_sample: int = 20) -> dict[str, object]:
    """Review complete trade lifecycles while keeping the inception risk immutable."""
    items = {item.ticker.symbol: item for item in report.ticker_reports}
    rows: list[dict[str, object]] = []
    for trade in report.trade_journal:
        if trade.status == "cancelled":
            continue
        item = items.get(trade.ticker)
        last = _metric_float(item, "last_close") if item else None
        lifecycle = _trade_lifecycle_metrics(trade, last)
        initial_risk = _as_float(lifecycle.get("initial_risk"))
        net_pl = _as_float(lifecycle.get("net_pl"))
        r_multiple = net_pl / initial_risk if net_pl is not None and initial_risk else None
        entry_date = lifecycle.get("entry_date")
        exit_date = lifecycle.get("exit_date")
        end_date = (
            exit_date
            if lifecycle["closed"] and isinstance(exit_date, date)
            else report.report_date
        )
        holding_days = (
            max(0, (end_date - entry_date).days)
            if isinstance(entry_date, date)
            else None
        )
        extremes = (
            _trade_path_extremes(item, entry_date, end_date)
            if item and isinstance(entry_date, date) and not lifecycle["planned"]
            else {}
        )
        average_entry = _as_float(lifecycle.get("average_entry"))
        per_unit_risk = (
            average_entry - trade.initial_stop
            if average_entry is not None
            and trade.initial_stop is not None
            and average_entry > trade.initial_stop
            else None
        )
        mfe_r = mae_r = None
        if average_entry is not None and per_unit_risk:
            high = _as_float(extremes.get("high"))
            low = _as_float(extremes.get("low"))
            if high is not None:
                mfe_r = (high - average_entry) / per_unit_risk
            if low is not None:
                mae_r = (low - average_entry) / per_unit_risk
        rows.append({
            "trade": trade,
            "item": item,
            **lifecycle,
            "mark_price": round(last, 4) if last is not None else None,
            "planned_risk": round(initial_risk, 2) if initial_risk is not None else None,
            "gross_pl": round(float(lifecycle["gross_pl"]), 2) if lifecycle["gross_pl"] is not None else None,
            "net_pl": round(net_pl, 2) if net_pl is not None else None,
            "r_multiple": round(r_multiple, 2) if r_multiple is not None else None,
            "mfe_r": round(mfe_r, 2) if mfe_r is not None else None,
            "mae_r": round(mae_r, 2) if mae_r is not None else None,
            "holding_days": holding_days,
            "path_complete": bool(extremes.get("complete", False)),
        })

    closed_rows = [
        row
        for row in rows
        if row["closed"] and row["r_multiple"] is not None
    ]
    r_values = [float(row["r_multiple"]) for row in closed_rows]
    wins = [value for value in r_values if value > 0]
    losses = [value for value in r_values if value <= 0]
    average_win = sum(wins) / len(wins) if wins else None
    average_loss = sum(losses) / len(losses) if losses else None
    payoff_ratio = (
        average_win / abs(average_loss)
        if average_win is not None and average_loss not in (None, 0)
        else None
    )
    profit_factor = (
        sum(wins) / abs(sum(losses))
        if wins and losses and sum(losses) != 0
        else None
    )
    losing_streak = max_losing_streak = 0
    for row in sorted(
        closed_rows,
        key=lambda value: (value["exit_date"] or date.min, value["trade"].trade_id),
    ):
        if float(row["r_multiple"]) <= 0:
            losing_streak += 1
            max_losing_streak = max(max_losing_streak, losing_streak)
        else:
            losing_streak = 0

    market_stats: list[dict[str, object]] = []
    for market in ("us", "taiwan", "crypto", "other"):
        market_rows = [
            row for row in closed_rows
            if _market_bucket(str(row["trade"].market)) == market
        ]
        if not market_rows:
            continue
        market_r = [float(row["r_multiple"]) for row in market_rows]
        market_stats.append({
            "market": market,
            "sample_size": len(market_r),
            "win_rate": round(sum(value > 0 for value in market_r) / len(market_r) * 100.0, 1),
            "average_r": round(sum(market_r) / len(market_r), 2),
            "reliable": len(market_r) >= minimum_sample,
        })
    rows.sort(
        key=lambda row: (
            bool(row["planned"]),
            not bool(row["closed"]),
            row["entry_date"] or date.min,
            row["trade"].trade_id,
        ),
        reverse=True,
    )
    return {
        "rows": rows,
        "planned_count": sum(bool(row["planned"]) for row in rows),
        "open_count": sum(not row["closed"] and not row["planned"] for row in rows),
        "closed_count": sum(bool(row["closed"]) for row in rows),
        "measured_count": len(closed_rows),
        "win_rate": round(len(wins) / len(r_values) * 100.0, 1) if r_values else None,
        "average_r": round(sum(r_values) / len(r_values), 2) if r_values else None,
        "expectancy_r": round(sum(r_values) / len(r_values), 2) if r_values else None,
        "median_r": round(median(r_values), 2) if r_values else None,
        "average_win_r": round(average_win, 2) if average_win is not None else None,
        "average_loss_r": round(average_loss, 2) if average_loss is not None else None,
        "payoff_ratio": round(payoff_ratio, 2) if payoff_ratio is not None else None,
        "profit_factor": round(profit_factor, 2) if profit_factor is not None else None,
        "total_r": round(sum(r_values), 2) if r_values else None,
        "max_losing_streak": max_losing_streak,
        "minimum_sample": minimum_sample,
        "reliable": len(closed_rows) >= minimum_sample,
        "market_stats": market_stats,
    }


def _trade_path_extremes(
    item: TickerReport,
    start: date | None,
    end: date,
) -> dict[str, object]:
    if start is None or not item.valuation:
        return {}
    dates = item.valuation.metrics.get("chart_dates_60")
    highs = item.valuation.metrics.get("chart_high_60")
    lows = item.valuation.metrics.get("chart_low_60")
    if not isinstance(dates, list) or not isinstance(highs, list) or not isinstance(lows, list):
        return {}
    selected_highs: list[float] = []
    selected_lows: list[float] = []
    parsed_dates: list[date] = []
    for label, high_raw, low_raw in zip(dates, highs, lows):
        try:
            session_date = date.fromisoformat(str(label)[:10])
        except ValueError:
            continue
        if session_date < start or session_date > end:
            continue
        high = _as_float(high_raw)
        low = _as_float(low_raw)
        if high is not None:
            selected_highs.append(high)
        if low is not None:
            selected_lows.append(low)
        parsed_dates.append(session_date)
    if not selected_highs or not selected_lows:
        return {}
    first_chart_date = None
    if dates:
        try:
            first_chart_date = date.fromisoformat(str(dates[0])[:10])
        except ValueError:
            first_chart_date = None
    return {
        "high": max(selected_highs),
        "low": min(selected_lows),
        "complete": first_chart_date is not None and first_chart_date <= start,
        "sessions": len(set(parsed_dates)),
    }


def _portfolio_risk_overview_legacy(report: DailyReport) -> dict[str, object]:
    """Account risk by currency plus high-correlation holding pairs."""
    holdings = [
        item
        for item in report.ticker_reports
        if item.ticker.position.status == "holding"
    ]
    by_currency: dict[tuple[str, str], dict[str, object]] = {}
    missing_stops: list[dict[str, str]] = []
    for item in holdings:
        pos = item.ticker.position
        last = _metric_float(item, "last_close")
        if last is None or pos.shares is None or pos.shares <= 0:
            continue
        currency = item.ticker.currency.upper()
        market = _market_bucket(item.ticker.market)
        row = by_currency.setdefault((market, currency), {
            "market": market,
            "currency": currency,
            "market_value": 0.0,
            "risk_at_stop": 0.0,
            "positions": 0,
            "with_stop": 0,
        })
        market_value = last * pos.shares
        row["market_value"] = float(row["market_value"]) + market_value
        row["positions"] = int(row["positions"]) + 1
        if pos.stop_loss is not None and 0 < pos.stop_loss < last:
            risk = (last - pos.stop_loss) * pos.shares
            row["risk_at_stop"] = float(row["risk_at_stop"]) + risk
            row["with_stop"] = int(row["with_stop"]) + 1
        else:
            missing_stops.append({"symbol": item.ticker.symbol, "market": market})

    settings = report.settings.portfolio if report.settings else None
    currency_rows: list[dict[str, object]] = []
    for (_market, currency), row in sorted(by_currency.items()):
        market_value = float(row["market_value"])
        risk_at_stop = float(row["risk_at_stop"])
        budget = settings.risk_budget_by_currency.get(currency) if settings else None
        currency_rows.append({
            **row,
            "market_value": round(market_value, 2),
            "risk_at_stop": round(risk_at_stop, 2),
            "risk_pct": round(risk_at_stop / market_value * 100.0, 2) if market_value else None,
            "risk_budget": budget,
            "budget_usage_pct": round(risk_at_stop / budget * 100.0, 1) if budget else None,
            "over_budget": bool(budget and risk_at_stop > budget),
        })

    return_series = {
        item.ticker.symbol: _dated_close_returns(item)
        for item in holdings
    }
    correlated_pairs: list[dict[str, object]] = []
    for left_index, left in enumerate(holdings):
        for right in holdings[left_index + 1:]:
            if _market_bucket(left.ticker.market) != _market_bucket(right.ticker.market):
                continue
            left_values = return_series.get(left.ticker.symbol, {})
            right_values = return_series.get(right.ticker.symbol, {})
            shared = sorted(set(left_values) & set(right_values))
            if len(shared) < 20:
                continue
            correlation = _pearson_correlation(
                [left_values[key] for key in shared],
                [right_values[key] for key in shared],
            )
            if correlation is None or correlation < 0.75:
                continue
            correlated_pairs.append({
                "left": left.ticker.symbol,
                "right": right.ticker.symbol,
                "market": _market_bucket(left.ticker.market),
                "correlation": round(correlation, 2),
                "sessions": len(shared),
                "combined_weight": round(
                    float(left.ticker.position.portfolio_weight or 0.0)
                    + float(right.ticker.position.portfolio_weight or 0.0),
                    2,
                ),
            })
    correlated_pairs.sort(
        key=lambda row: (float(row["correlation"]), float(row["combined_weight"])),
        reverse=True,
    )
    return {
        "currencies": currency_rows,
        "missing_stops": missing_stops,
        "correlated_pairs": correlated_pairs[:8],
        "holding_count": len(holdings),
    }


def _fx_rate_to_base(report: DailyReport, currency: str, base_currency: str) -> float | None:
    currency = currency.upper()
    base_currency = base_currency.upper()
    if currency == base_currency:
        return 1.0
    rates = report.market_context.fx_rates if report.market_context else {}
    direct = _as_float(rates.get(f"{currency}/{base_currency}"))
    if direct is not None and direct > 0:
        return direct
    inverse = _as_float(rates.get(f"{base_currency}/{currency}"))
    if inverse is not None and inverse > 0:
        return 1.0 / inverse
    return None


def portfolio_risk_overview(report: DailyReport) -> dict[str, object]:
    """Show open, reserved, and gap-stressed account risk without double counting."""
    items = {item.ticker.symbol: item for item in report.ticker_reports}
    holdings = [
        item
        for item in report.ticker_reports
        if item.ticker.position.status == "holding"
    ]
    journal = trade_journal_summary(report)
    by_market_currency: dict[tuple[str, str], dict[str, object]] = {}
    missing_stops: list[dict[str, str]] = []
    liquidity_alerts: list[dict[str, object]] = []
    tracked_shares: dict[str, float] = {}

    def bucket(item: TickerReport) -> dict[str, object]:
        market = _market_bucket(item.ticker.market)
        currency = item.ticker.currency.upper()
        return by_market_currency.setdefault((market, currency), {
            "market": market,
            "currency": currency,
            "market_value": 0.0,
            "open_risk": 0.0,
            "pending_risk": 0.0,
            "stress_risk": 0.0,
            "positions": 0,
            "planned_orders": 0,
            "with_stop": 0,
        })

    def add_liquidity(
        item: TickerReport,
        shares: float,
        price: float,
        *,
        kind: str,
    ) -> None:
        notional = shares * price
        average = _metric_float(item, "avg_dollar_volume_20d")
        if average is None or average <= 0:
            return
        adv_pct = notional / average * 100.0
        days = notional / (average * 0.10)
        alert = adv_pct > 1.0 if kind == "planned" else days > 1.0
        if alert:
            liquidity_alerts.append({
                "symbol": item.ticker.symbol,
                "market": _market_bucket(item.ticker.market),
                "currency": item.ticker.currency.upper(),
                "kind": kind,
                "notional": round(notional, 2),
                "adv_pct": round(adv_pct, 2),
                "days_to_liquidate": round(days, 2),
            })

    for journal_row in journal["rows"]:
        trade = journal_row["trade"]
        item = items.get(trade.ticker)
        if item is None:
            continue
        row = bucket(item)
        if journal_row["planned"]:
            planned_shares = _as_float(journal_row.get("planned_shares"))
            entry = _as_float(journal_row.get("average_entry"))
            planned_risk = _as_float(journal_row.get("initial_risk"))
            if planned_shares and entry:
                add_liquidity(item, planned_shares, entry, kind="planned")
            row["planned_orders"] = int(row["planned_orders"]) + 1
            if planned_risk is not None:
                row["pending_risk"] = float(row["pending_risk"]) + planned_risk
                notional = (planned_shares or 0.0) * (entry or 0.0)
                atr = _metric_float(item, "atr_20")
                gap_buffer = max(
                    (atr or 0.0) * (planned_shares or 0.0),
                    notional * 0.03,
                )
                row["stress_risk"] = float(row["stress_risk"]) + planned_risk + gap_buffer
            else:
                missing_stops.append({
                    "symbol": trade.ticker,
                    "market": _market_bucket(item.ticker.market),
                    "kind": "planned",
                })
            continue

        remaining = _as_float(journal_row.get("remaining_shares")) or 0.0
        if journal_row["closed"] or remaining <= 0:
            continue
        mark = _as_float(journal_row.get("mark_price"))
        if mark is None:
            continue
        tracked_shares[trade.ticker] = tracked_shares.get(trade.ticker, 0.0) + remaining
        market_value = mark * remaining
        row["market_value"] = float(row["market_value"]) + market_value
        row["positions"] = int(row["positions"]) + 1
        add_liquidity(item, remaining, mark, kind="position")
        current_risk = _as_float(journal_row.get("current_risk"))
        if current_risk is None:
            missing_stops.append({
                "symbol": trade.ticker,
                "market": _market_bucket(item.ticker.market),
                "kind": "open",
            })
            continue
        row["open_risk"] = float(row["open_risk"]) + current_risk
        row["with_stop"] = int(row["with_stop"]) + 1
        atr = _metric_float(item, "atr_20")
        gap_buffer = max((atr or 0.0) * remaining, market_value * 0.03)
        row["stress_risk"] = float(row["stress_risk"]) + current_risk + gap_buffer

    for item in holdings:
        position = item.ticker.position
        last = _metric_float(item, "last_close")
        total_shares = position.shares or 0.0
        residual_shares = max(0.0, total_shares - tracked_shares.get(item.ticker.symbol, 0.0))
        if last is None or residual_shares <= 0:
            continue
        row = bucket(item)
        market_value = last * residual_shares
        row["market_value"] = float(row["market_value"]) + market_value
        row["positions"] = int(row["positions"]) + 1
        add_liquidity(item, residual_shares, last, kind="position")
        if position.stop_loss is None or not 0 < position.stop_loss < last:
            missing_stops.append({
                "symbol": item.ticker.symbol,
                "market": _market_bucket(item.ticker.market),
                "kind": "holding",
            })
            continue
        current_risk = (last - position.stop_loss) * residual_shares
        row["open_risk"] = float(row["open_risk"]) + current_risk
        row["with_stop"] = int(row["with_stop"]) + 1
        atr = _metric_float(item, "atr_20")
        gap_buffer = max((atr or 0.0) * residual_shares, market_value * 0.03)
        row["stress_risk"] = float(row["stress_risk"]) + current_risk + gap_buffer

    settings = report.settings.portfolio if report.settings else None
    totals_by_currency: dict[str, float] = {}
    for row in by_market_currency.values():
        currency = str(row["currency"])
        combined = float(row["open_risk"]) + float(row["pending_risk"])
        totals_by_currency[currency] = totals_by_currency.get(currency, 0.0) + combined

    currency_rows: list[dict[str, object]] = []
    for (_market, currency), row in sorted(by_market_currency.items()):
        market_value = float(row["market_value"])
        open_risk = float(row["open_risk"])
        pending_risk = float(row["pending_risk"])
        combined_risk = open_risk + pending_risk
        currency_risk = totals_by_currency[currency]
        budget = settings.risk_budget_by_currency.get(currency) if settings else None
        remaining_budget = budget - currency_risk if budget is not None else None
        currency_rows.append({
            **row,
            "market_value": round(market_value, 2),
            "risk_at_stop": round(open_risk, 2),
            "open_risk": round(open_risk, 2),
            "pending_risk": round(pending_risk, 2),
            "combined_risk": round(combined_risk, 2),
            "stress_risk": round(float(row["stress_risk"]), 2),
            "risk_pct": round(open_risk / market_value * 100.0, 2) if market_value else None,
            "risk_budget": budget,
            "remaining_budget": round(remaining_budget, 2) if remaining_budget is not None else None,
            "budget_usage_pct": round(currency_risk / budget * 100.0, 1) if budget else None,
            "over_budget": bool(budget and currency_risk > budget),
        })

    base_currency = settings.base_currency if settings else "TWD"
    consolidated = {
        "base_currency": base_currency,
        "market_value": 0.0,
        "open_risk": 0.0,
        "pending_risk": 0.0,
        "stress_risk": 0.0,
        "complete": True,
        "missing_currencies": [],
        "as_of": report.market_context.retrieved_at if report.market_context else None,
    }
    for row in currency_rows:
        rate = _fx_rate_to_base(report, str(row["currency"]), base_currency)
        if rate is None:
            consolidated["complete"] = False
            consolidated["missing_currencies"].append(row["currency"])
            continue
        for key in ("market_value", "open_risk", "pending_risk", "stress_risk"):
            consolidated[key] = float(consolidated[key]) + float(row[key]) * rate
    for key in ("market_value", "open_risk", "pending_risk", "stress_risk"):
        consolidated[key] = round(float(consolidated[key]), 2)
    consolidated["risk_pct"] = (
        round(float(consolidated["open_risk"]) / float(consolidated["market_value"]) * 100.0, 2)
        if consolidated["market_value"]
        else None
    )

    return_series = {item.ticker.symbol: _dated_close_returns(item) for item in holdings}
    correlated_pairs: list[dict[str, object]] = []
    for left_index, left in enumerate(holdings):
        for right in holdings[left_index + 1:]:
            if _market_bucket(left.ticker.market) != _market_bucket(right.ticker.market):
                continue
            left_values = return_series.get(left.ticker.symbol, {})
            right_values = return_series.get(right.ticker.symbol, {})
            shared = sorted(set(left_values) & set(right_values))
            if len(shared) < 20:
                continue
            correlation = _pearson_correlation(
                [left_values[key] for key in shared],
                [right_values[key] for key in shared],
            )
            if correlation is None or correlation < 0.75:
                continue
            correlated_pairs.append({
                "left": left.ticker.symbol,
                "right": right.ticker.symbol,
                "market": _market_bucket(left.ticker.market),
                "correlation": round(correlation, 2),
                "sessions": len(shared),
                "combined_weight": round(
                    float(left.ticker.position.portfolio_weight or 0.0)
                    + float(right.ticker.position.portfolio_weight or 0.0),
                    2,
                ),
            })
    correlated_pairs.sort(
        key=lambda row: (float(row["correlation"]), float(row["combined_weight"])),
        reverse=True,
    )
    liquidity_alerts.sort(
        key=lambda row: (float(row["days_to_liquidate"]), float(row["adv_pct"])),
        reverse=True,
    )

    market_summaries: dict[str, dict[str, object]] = {}
    for market in ("us", "taiwan", "crypto"):
        market_rows = [row for row in currency_rows if row["market"] == market]
        market_missing = [row for row in missing_stops if row["market"] == market]
        if not market_rows and not market_missing:
            continue
        market_summary: dict[str, object] = {
            "base_currency": base_currency,
            "market_value": 0.0,
            "open_risk": 0.0,
            "pending_risk": 0.0,
            "stress_risk": 0.0,
            "complete": True,
            "missing_currencies": [],
            "missing_stops": len(market_missing),
            "planned_count": sum(int(row["planned_orders"]) for row in market_rows),
        }
        for row in market_rows:
            rate = _fx_rate_to_base(report, str(row["currency"]), base_currency)
            if rate is None:
                market_summary["complete"] = False
                market_summary["missing_currencies"].append(row["currency"])
                continue
            for key in ("market_value", "open_risk", "pending_risk", "stress_risk"):
                market_summary[key] = float(market_summary[key]) + float(row[key]) * rate
        for key in ("market_value", "open_risk", "pending_risk", "stress_risk"):
            market_summary[key] = round(float(market_summary[key]), 2)
        market_value = float(market_summary["market_value"])
        market_summary["risk_pct"] = (
            round(float(market_summary["open_risk"]) / market_value * 100.0, 2)
            if market_value
            else None
        )
        market_summaries[market] = market_summary

    return {
        "currencies": currency_rows,
        "consolidated": consolidated,
        "market_summaries": market_summaries,
        "missing_stops": missing_stops,
        "liquidity_alerts": liquidity_alerts[:8],
        "correlated_pairs": correlated_pairs[:8],
        "holding_count": len(holdings),
        "planned_count": int(journal["planned_count"]),
    }


def _dated_close_returns(item: TickerReport) -> dict[str, float]:
    if not item.valuation:
        return {}
    dates = item.valuation.metrics.get("chart_dates_60")
    closes = item.valuation.metrics.get("chart_close_60")
    if not isinstance(dates, list) or not isinstance(closes, list):
        return {}
    cleaned: list[tuple[str, float]] = []
    for label, raw_close in zip(dates, closes):
        close = _as_float(raw_close)
        if close is not None and close > 0:
            cleaned.append((str(label), close))
    returns: dict[str, float] = {}
    for index in range(1, len(cleaned)):
        previous = cleaned[index - 1][1]
        if previous > 0:
            returns[cleaned[index][0]] = (cleaned[index][1] - previous) / previous
    return returns


def _pearson_correlation(left: list[float], right: list[float]) -> float | None:
    count = min(len(left), len(right))
    if count < 2:
        return None
    left = left[:count]
    right = right[:count]
    left_mean = sum(left) / count
    right_mean = sum(right) / count
    numerator = sum((a - left_mean) * (b - right_mean) for a, b in zip(left, right))
    left_var = sum((value - left_mean) ** 2 for value in left)
    right_var = sum((value - right_mean) ** 2 for value in right)
    denominator = (left_var * right_var) ** 0.5
    if denominator == 0:
        return None
    return numerator / denominator


def price_structure_chart(item: TickerReport, width: int = 640, height: int = 190) -> str:
    """Render an offline 60-session close/SMA/volume structure chart."""
    if not item.valuation:
        return ""
    metrics = item.valuation.metrics
    dates = metrics.get("chart_dates_60")
    closes_raw = metrics.get("chart_close_60")
    volumes_raw = metrics.get("chart_volume_60")
    sma20_raw = metrics.get("chart_sma20_60")
    sma60_raw = metrics.get("chart_sma60_60")
    if not all(isinstance(value, list) for value in (dates, closes_raw, volumes_raw, sma20_raw, sma60_raw)):
        return ""
    count = min(len(dates), len(closes_raw), len(volumes_raw), len(sma20_raw), len(sma60_raw))
    if count < 2:
        return ""

    closes = [_as_float(value) for value in closes_raw[:count]]
    volumes = [_as_float(value) or 0.0 for value in volumes_raw[:count]]
    sma20 = [_as_float(value) for value in sma20_raw[:count]]
    sma60 = [_as_float(value) for value in sma60_raw[:count]]
    adam = adam_reflection_scenario(item)
    projection = [
        value
        for raw in (adam["projection"] if adam else [])
        if (value := _as_float(raw)) is not None
    ]
    total_count = count + len(projection)
    price_values = [value for value in closes + sma20 + sma60 + projection if value is not None]
    if len(price_values) < 2:
        return ""
    low = min(price_values)
    high = max(price_values)
    span = (high - low) or 1.0
    left, right = 8.0, float(width - 8)
    price_top, price_bottom = 8.0, float(height - 48)
    volume_top, volume_bottom = float(height - 38), float(height - 16)

    def x_at(index: int) -> float:
        return left + index / max(1, total_count - 1) * (right - left)

    def y_at(value: float) -> float:
        return price_bottom - (value - low) / span * (price_bottom - price_top)

    def polyline(values: list[float | None], css_class: str, start_index: int = 0) -> str:
        points = [
            f"{x_at(start_index + index):.1f},{y_at(value):.1f}"
            for index, value in enumerate(values)
            if value is not None
        ]
        if len(points) < 2:
            return ""
        return f'<polyline class="{css_class}" points="{" ".join(points)}"/>'

    historical_right = x_at(count - 1)
    max_volume = max(volumes) or 1.0
    bar_width = max(1.0, (right - left) / total_count * 0.62)
    bars = []
    for index, volume in enumerate(volumes):
        bar_height = volume / max_volume * (volume_bottom - volume_top)
        bars.append(
            f'<rect x="{x_at(index) - bar_width / 2:.1f}" y="{volume_bottom - bar_height:.1f}" '
            f'width="{bar_width:.1f}" height="{bar_height:.1f}"/>'
        )

    levels = []
    for css_class, raw_value in (
        ("price-level-pivot", metrics.get("breakout_pivot")),
        ("price-level-stop", item.ticker.position.stop_loss),
    ):
        value = _as_float(raw_value)
        if value is not None and low <= value <= high:
            levels.append(
                f'<line class="{css_class}" x1="{left:.1f}" x2="{historical_right:.1f}" '
                f'y1="{y_at(value):.1f}" y2="{y_at(value):.1f}"/>'
            )

    scenario_line = ""
    scenario_label = ""
    scenario_divider = ""
    if projection and closes[-1] is not None:
        scenario_line = polyline(
            [closes[-1], *projection],
            "price-line-adam",
            count - 1,
        )
        scenario_divider = (
            f'<line class="price-chart-scenario-divider" '
            f'x1="{historical_right:.1f}" x2="{historical_right:.1f}" '
            f'y1="{price_top:.1f}" y2="{volume_bottom:.1f}"/>'
        )
        scenario_label = (
            f'<text class="price-chart-date price-chart-scenario-label" '
            f'x="{right}" y="{height - 2}" text-anchor="end">\u53cd\u5c04\u60c5\u5883 +{len(projection)}D</text>'
        )

    first_date = str(dates[0])[:10]
    last_date = str(dates[count - 1])[:10]
    return (
        f'<svg class="price-structure-svg" viewBox="0 0 {width} {height}" '
        f'role="img" aria-label="60 \u500b\u4ea4\u6613\u65e5\u50f9\u91cf\u7d50\u69cb\u8207\u4e9e\u7576\u53cd\u5c04\u60c5\u5883">'
        f'<title>{item.ticker.symbol} 60 \u500b\u4ea4\u6613\u65e5\u50f9\u91cf\u7d50\u69cb</title>'
        f'<line class="price-chart-divider" x1="{left}" x2="{right}" y1="{volume_top - 5}" y2="{volume_top - 5}"/>'
        f'<g class="price-volume-bars">{"".join(bars)}</g>'
        f'{"".join(levels)}'
        f'{scenario_divider}'
        f'{polyline(sma60, "price-line-sma60")}'
        f'{polyline(sma20, "price-line-sma20")}'
        f'{polyline(closes, "price-line-close")}'
        f'{scenario_line}'
        f'<text class="price-chart-date" x="{left}" y="{height - 2}">{first_date}</text>'
        f'<text class="price-chart-date" x="{historical_right:.1f}" y="{height - 2}" text-anchor="end">{last_date}</text>'
        f'{scenario_label}'
        f'</svg>'
    )

def _trade_price(value: float) -> str:
    return f"{value:.4f}" if abs(value) < 10 else f"{value:.2f}"

def post_earnings_status(item: TickerReport, anchor: date) -> dict[str, object] | None:
    """If the ticker reported earnings within the last N days, return a small
    banner descriptor so the card can prompt the user to log a review.

    Returns None when the ticker hasn't reported recently (or has no earnings
    date). Returns {"days_ago", "earnings_date"} otherwise. The actual review
    fields (EPS beat/miss, guidance, conclusion) are persisted client-side via
    localStorage — this descriptor only controls when the banner shows.
    """
    if not item.earnings or not isinstance(item.earnings.earnings_date, date):
        return None
    delta = (anchor - item.earnings.earnings_date).days
    if 0 < delta <= 7:
        return {"days_ago": delta, "earnings_date": item.earnings.earnings_date}
    return None


def post_earnings_items(report: DailyReport, days: int = 7) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for item in report.ticker_reports:
        status = post_earnings_status(item, report.report_date)
        if not status:
            continue
        reaction = daily_change_pct(item)
        rows.append({
            "item": item,
            "days_ago": status["days_ago"],
            "earnings_date": status["earnings_date"],
            "reaction": reaction,
        })
    return sorted(rows, key=lambda row: (int(row["days_ago"]), row["item"].ticker.symbol))


def post_earnings_defaults(report: DailyReport, item: TickerReport) -> dict[str, object]:
    """Best-effort post-earnings defaults from fetched valuation metrics."""
    eps_surprise = _metric_float(item, "latest_eps_surprise_pct")
    rev_surprise = _metric_float(item, "latest_revenue_surprise_pct")
    review = post_earnings_review_for(report, item.ticker.symbol)
    return {
        "eps": review.eps if review and review.eps else _surprise_label(eps_surprise),
        "eps_surprise": review.eps_surprise_pct if review and review.eps_surprise_pct is not None else eps_surprise,
        "rev": review.revenue if review and review.revenue else _surprise_label(rev_surprise),
        "rev_surprise": review.revenue_surprise_pct if review and review.revenue_surprise_pct is not None else rev_surprise,
        "guide": review.guide if review else None,
        "fy1_eps_revision_after": review.fy1_eps_revision_after if review and review.fy1_eps_revision_after is not None else _metric_float(item, "fy1_eps_revision_30d"),
        "fy1_revenue_revision_after": review.fy1_revenue_revision_after if review and review.fy1_revenue_revision_after is not None else _metric_float(item, "fy1_revenue_revision_30d"),
        "conclusion": review.conclusion if review else "",
        "next_step": review.next_step if review else "",
        "gross_margin_change": review.gross_margin_change if review else "",
        "management_keywords": review.management_keywords if review else "",
        "thesis_changed": review.thesis_changed if review else "",
    }


def pre_earnings_card(report: DailyReport, item: TickerReport) -> dict[str, object] | None:
    """Pre-earnings briefing for tickers reporting within the next 0-7 days.

    Surfaces consensus estimates, the 30D EPS-revision drift, the recent stock
    move and RSI, plus an overextended flag, so the user can frame the setup
    before the print. Returns None outside the 0-7 day window.
    """
    anchor = report.report_date
    delta = earnings_delta(item, anchor)
    if delta is None or not (0 <= delta <= 7):
        return None
    state = research_state_for(report, item.ticker.symbol)
    questions = list(state.earnings_questions) if state else []
    # Always render 3 slots so the UI is stable; fill known ones from state.
    slots = [questions[i] if i < len(questions) else "" for i in range(3)]
    return {
        "symbol": item.ticker.symbol,
        "company": item.ticker.company_name,
        "days_until": delta,
        "action": earnings_action(item, anchor),
        "eps_estimate": item.earnings.eps_estimate if item.earnings else None,
        "revenue_estimate": item.earnings.revenue_estimate if item.earnings else None,
        "eps_revision_30d": _metric_float(item, "fy1_eps_revision_30d"),
        "move_30d": _metric_float(item, "return_20d"),
        "rsi": _metric_float(item, "rsi_14"),
        "from_52w_high": from_52w_high_pct(item),
        "overextended": _is_overextended(item),
        "questions": slots,
    }


def _is_overextended(item: TickerReport) -> bool:
    """Stretched setup heuristic: hot RSI or pinned to the 52-week high."""
    rsi = _metric_float(item, "rsi_14")
    from_high = from_52w_high_pct(item)
    if rsi is not None and rsi >= 75:
        return True
    if from_high is not None and from_high >= -2.0:
        return True
    return False


def data_quality_overview(report: DailyReport) -> dict[str, object]:
    """Roll-up of per-ticker data-quality confidence for the dashboard section.

    Returns the average confidence and the list of tickers scoring below 80
    (with the flags that fired), so the user can spot questionable inputs at a
    glance rather than auditing every card.
    """
    rows: list[dict[str, object]] = []
    scores: list[int] = []
    for item in report.ticker_reports:
        result = data_quality_confidence(
            item,
            report.report_date,
            premarket_move=premarket_move_for(report, item.ticker.symbol),
        )
        score = int(result["score"])
        scores.append(score)
        if score < 80:
            rows.append(
                {
                    "symbol": item.ticker.symbol,
                    "company": item.ticker.company_name,
                    "score": score,
                    "tag": result["tag"],
                    "flags": result["flags"],
                    "missing_fields": result["missing_fields"],
                    "fallback": result["fallback"],
                }
            )
    rows.sort(key=lambda r: r["score"])  # type: ignore[index,arg-type]
    average = round(sum(scores) / len(scores)) if scores else 100
    return {
        "average": average,
        "checked": len(scores),
        "flagged": rows,
    }


def _surprise_label(value: float | None) -> str | None:
    if value is None:
        return None
    if value > 1.0:
        return "beat"
    if value < -1.0:
        return "miss"
    return "inline"


def premarket_change_pct(report: DailyReport, symbol: str) -> float | None:
    if not report.premarket:
        return None
    for move in report.premarket.watchlist_movers:
        if move.symbol == symbol:
            return move.change_pct
    return None


def premarket_move_for(report: DailyReport, symbol: str) -> object | None:
    if not report.premarket:
        return None
    for move in report.premarket.watchlist_movers:
        if move.symbol == symbol:
            return move
    return None


def _ticker_map(report: DailyReport) -> dict[str, TickerReport]:
    return {item.ticker.symbol: item for item in report.ticker_reports}


def _history_points(report: DailyReport, symbol: str) -> list[TickerHistoryPoint]:
    return report.ticker_history.get(symbol, [])


def _current_history_point(report: DailyReport, symbol: str) -> TickerHistoryPoint | None:
    points = _history_points(report, symbol)
    return points[0] if points else None


def _previous_history_point(report: DailyReport, symbol: str) -> TickerHistoryPoint | None:
    points = _history_points(report, symbol)
    return points[1] if len(points) > 1 else None


def _window_history_point(report: DailyReport, symbol: str, days: int) -> TickerHistoryPoint | None:
    cutoff = report.report_date - timedelta(days=days)
    points = _history_points(report, symbol)
    for point in reversed(points):
        if point.report_date <= cutoff:
            return point
    return points[-1] if len(points) > 1 else None


_VALUATION_RISK_ORDER: dict[str, int] = {"None": 0, "Elevated": 1, "High": 2, "Extreme": 3}


def _valuation_risk_direction(prev: str | None, curr: str | None) -> str:
    po = _VALUATION_RISK_ORDER.get(prev or "", -1)
    co = _VALUATION_RISK_ORDER.get(curr or "", -1)
    if po < 0 or co < 0 or po == co:
        return "same"
    return "up" if co > po else "down"


@dataclass(frozen=True)
class TickerDelta:
    attention_score_delta: float | None
    rsi_delta: float | None
    news_count_delta: int | None
    valuation_risk_direction: str  # "up" | "down" | "same"


def ticker_delta(report: DailyReport, symbol: str) -> TickerDelta | None:
    curr = _current_history_point(report, symbol)
    prev = _previous_history_point(report, symbol)
    if curr is None or prev is None:
        return None
    return TickerDelta(
        attention_score_delta=(
            round(curr.attention_score - prev.attention_score, 1)
            if curr.attention_score is not None and prev.attention_score is not None
            else None
        ),
        rsi_delta=(
            round(curr.rsi - prev.rsi, 1)
            if curr.rsi is not None and prev.rsi is not None
            else None
        ),
        news_count_delta=(
            curr.news_count - prev.news_count
            if curr.news_count is not None and prev.news_count is not None
            else None
        ),
        valuation_risk_direction=_valuation_risk_direction(prev.valuation_risk, curr.valuation_risk),
    )


def _checklist_review_status(checklist: list[str]) -> str:
    count = len(set(checklist))
    if count >= 4:
        return "reviewed"
    if count >= 1:
        return "in-progress"
    return "not-reviewed"


def _review_complete(state: TickerResearchState) -> bool:
    status = state.review_status or _checklist_review_status(state.checklist)
    return status == "reviewed"


def _post_earnings_review_complete(review: PostEarningsReview | None) -> bool:
    if review is None:
        return False
    return any(
        bool(value)
        for value in (
            review.eps,
            review.revenue,
            review.guide,
            review.conclusion.strip(),
            review.next_step.strip(),
        )
    )


def _days_since_last_review(state: TickerResearchState, anchor: datetime) -> int | None:
    if state.last_reviewed_at is None:
        return None
    reviewed_at = state.last_reviewed_at
    if reviewed_at.tzinfo is None:
        reviewed_at = reviewed_at.replace(tzinfo=anchor.tzinfo or reviewed_at.tzinfo)
    delta = anchor.astimezone(reviewed_at.tzinfo) - reviewed_at
    return max(0, delta.days)


def changes_since_last_run(report: DailyReport) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for item in report.ticker_reports:
        symbol = item.ticker.symbol
        current = _current_history_point(report, symbol)
        previous = _previous_history_point(report, symbol)
        if current is None or previous is None:
            continue
        if current.thesis_state != previous.thesis_state and current.thesis_state:
            rows.append({
                "symbol": symbol,
                "title": "Thesis state changed",
                "detail": f"{previous.thesis_state or 'unmarked'} -> {current.thesis_state}",
                "anchor": f"#ticker-{symbol.lower()}",
                "priority": 10,
            })
        if current.review_status != previous.review_status:
            rows.append({
                "symbol": symbol,
                "title": "Review status changed",
                "detail": f"{previous.review_status} -> {current.review_status}",
                "anchor": f"#ticker-{symbol.lower()}",
                "priority": 7,
            })
        if current.top_news_count > previous.top_news_count:
            rows.append({
                "symbol": symbol,
                "title": "Top-news count increased",
                "detail": f"{previous.top_news_count} -> {current.top_news_count}",
                "anchor": f"#ticker-{symbol.lower()}",
                "priority": 6 + current.top_news_count,
            })
        if current.valuation_risk != previous.valuation_risk:
            rows.append({
                "symbol": symbol,
                "title": "Valuation risk changed",
                "detail": f"{previous.valuation_risk} -> {current.valuation_risk}",
                "anchor": f"#ticker-{symbol.lower()}",
                "priority": 6,
            })
        if current.warning_count > previous.warning_count:
            rows.append({
                "symbol": symbol,
                "title": "More data warnings",
                "detail": f"{previous.warning_count} -> {current.warning_count}",
                "anchor": f"#ticker-{symbol.lower()}",
                "priority": 5,
            })
    return sorted(rows, key=lambda row: (-int(row["priority"]), str(row["symbol"])))[:12]


def changes_in_window(report: DailyReport, *, days: int) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for item in report.ticker_reports:
        symbol = item.ticker.symbol
        current = _current_history_point(report, symbol)
        baseline = _window_history_point(report, symbol, days)
        if current is None or baseline is None or baseline.generated_at == current.generated_at:
            continue
        news_delta = current.top_news_count - baseline.top_news_count
        if news_delta > 0:
            rows.append({
                "symbol": symbol,
                "title": f"More top-news in {days}d",
                "detail": f"{baseline.top_news_count} -> {current.top_news_count}",
                "anchor": f"#ticker-{symbol.lower()}",
                "priority": 4 + news_delta,
            })
        if current.attention_score - baseline.attention_score >= 5:
            rows.append({
                "symbol": symbol,
                "title": f"Attention score rose in {days}d",
                "detail": f"{baseline.attention_score:.1f} -> {current.attention_score:.1f}",
                "anchor": f"#ticker-{symbol.lower()}",
                "priority": 5,
            })
        if current.thesis_state != baseline.thesis_state and current.thesis_state:
            rows.append({
                "symbol": symbol,
                "title": f"Thesis moved in {days}d",
                "detail": f"{baseline.thesis_state or 'unmarked'} -> {current.thesis_state}",
                "anchor": f"#ticker-{symbol.lower()}",
                "priority": 8,
            })
    return sorted(rows, key=lambda row: (-int(row["priority"]), str(row["symbol"])))[:12]


def research_review_queue(report: DailyReport) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for item in report.ticker_reports:
        symbol = item.ticker.symbol
        state = research_state_for(report, symbol)
        current = _current_history_point(report, symbol)
        review = post_earnings_review_for(report, symbol)
        post_status = post_earnings_status(item, report.report_date)
        reasons: list[str] = []
        score = current.attention_score if current is not None else 0.0

        if post_status and not _post_earnings_review_complete(review):
            reasons.append(f"post-earnings review due ({post_status['days_ago']}d ago)")
            score += 8
        if state.thesis_state in {"weakening", "broken"}:
            reasons.append(f"thesis {state.thesis_state}")
            score += 7
        if current is not None and current.news_burst_score >= 1.0 and not _review_complete(state):
            reasons.append(f"news burst {current.news_burst_score:+.1f}")
            score += 5
        if valuation_risk_label(item) in {"High", "Extreme"} and state.thesis_state in {"building", "active"}:
            reasons.append(f"{valuation_risk_label(item)} valuation with active thesis")
            score += 4
        stale_days = _days_since_last_review(state, report.generated_at)
        if stale_days is None and state.thesis_state in {"building", "active"}:
            reasons.append("thesis never reviewed")
            score += 5
        elif stale_days is not None and stale_days >= 14 and state.thesis_state in {"building", "active"}:
            reasons.append(f"last reviewed {stale_days}d ago")
            score += 4

        if reasons:
            rows.append({
                "symbol": symbol,
                "reasons": reasons[:4],
                "anchor": f"#ticker-{symbol.lower()}",
                "score": round(score, 2),
            })
    return sorted(rows, key=lambda row: (-float(row["score"]), str(row["symbol"])))[:8]


def recent_thesis_changes(report: DailyReport) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for item in report.ticker_reports:
        symbol = item.ticker.symbol
        current = _current_history_point(report, symbol)
        previous = _previous_history_point(report, symbol)
        if current is None or previous is None:
            continue
        if current.thesis_state and current.thesis_state != previous.thesis_state:
            rows.append({
                "symbol": symbol,
                "detail": f"{previous.thesis_state or 'unmarked'} -> {current.thesis_state}",
                "anchor": f"#ticker-{symbol.lower()}",
                "score": 1 if current.thesis_state in {"weakening", "broken"} else 0,
            })
    return sorted(rows, key=lambda row: (-int(row["score"]), str(row["symbol"])))[:8]


def post_earnings_due(report: DailyReport) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for row in post_earnings_items(report):
        symbol = row["item"].ticker.symbol
        review = post_earnings_review_for(report, symbol)
        if _post_earnings_review_complete(review):
            continue
        rows.append({
            "symbol": symbol,
            "detail": f"reported {row['days_ago']}d ago",
            "anchor": f"#ticker-{symbol.lower()}",
            "days_ago": int(row["days_ago"]),
        })
    return sorted(rows, key=lambda row: (int(row["days_ago"]), str(row["symbol"])))[:8]


def research_drift(report: DailyReport) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for item in report.ticker_reports:
        symbol = item.ticker.symbol
        state = research_state_for(report, symbol)
        if state.thesis_state not in {"building", "active"}:
            continue
        stale_days = _days_since_last_review(state, report.generated_at)
        current = _current_history_point(report, symbol)
        drift_reasons: list[str] = []
        score = 0
        if stale_days is None:
            drift_reasons.append("never reviewed")
            score += 6
        elif stale_days >= 21:
            drift_reasons.append(f"last reviewed {stale_days}d ago")
            score += 5
        if current is not None and current.news_burst_score >= 1.0:
            drift_reasons.append(f"news burst {current.news_burst_score:+.1f}")
            score += 3
        if current is not None and current.warning_count:
            drift_reasons.append(f"{current.warning_count} warning(s)")
            score += 2
        if drift_reasons:
            rows.append({
                "symbol": symbol,
                "detail": " | ".join(drift_reasons[:3]),
                "anchor": f"#ticker-{symbol.lower()}",
                "score": score,
            })
    return sorted(rows, key=lambda row: (-int(row["score"]), str(row["symbol"])))[:8]


def todays_catalysts(report: DailyReport) -> dict[str, list[object]]:
    catalysts: dict[str, list[object]] = {
        "before_open": [],
        "after_close": [],
        "during_market": [],
        "unknown": [],
        "macro": [],
        "post_earnings": [],
    }
    for item in report.ticker_reports:
        if not item.earnings or item.earnings.earnings_date != report.report_date:
            continue
        bucket = item.earnings.time_of_day
        if bucket not in ("before_market", "after_market", "during_market"):
            bucket = "unknown"
        key = {
            "before_market": "before_open",
            "after_market": "after_close",
            "during_market": "during_market",
            "unknown": "unknown",
        }[bucket]
        catalysts[key].append(item)

    catalysts["macro"] = [
        event for event in report.economic_events
        if event.event_datetime.date() == report.report_date
    ]
    catalysts["post_earnings"] = post_earnings_items(report)
    return catalysts


def todays_focus(report: DailyReport) -> dict[str, list[dict[str, object]]]:
    """Condense the morning dashboard into direct trading-status buckets."""
    review_candidates: list[tuple[float, TickerReport, list[str]]] = []
    no_action_before_event: list[tuple[float, TickerReport, list[str]]] = []
    pullback_setup: list[tuple[float, TickerReport, list[str]]] = []
    avoid_chase: list[tuple[float, TickerReport, list[str]]] = []

    alert_ranks = {str(alert["symbol"]): float(alert.get("rank", 0)) for alert in rule_alerts(report)}
    gaps = {m.symbol: abs(m.change_pct or 0.0) for m in report.premarket.gap_movers} if report.premarket else {}

    for item in report.ticker_reports:
        symbol = item.ticker.symbol
        state = research_state_for(report, symbol)
        current_point = _current_history_point(report, symbol)
        reasons: list[str] = []
        score = alert_ranks.get(symbol, 0.0)

        delta = earnings_delta(item, report.report_date)
        event_blocked = delta is not None and 0 <= delta <= 1
        if delta == 0:
            reasons.append("earnings today")
            score += 8
        elif delta == 1:
            reasons.append("earnings tomorrow")
            score += 5
        elif delta is not None and -2 <= delta < 0:
            reasons.append("post-earnings review")
            score += 6

        pmove = premarket_change_pct(report, symbol)
        if pmove is not None and abs(pmove) >= 2.0:
            reasons.append(f"premarket {format_pct(pmove)}")
            score += min(abs(pmove), 8)

        top_count = top_news_count(item)
        if top_count:
            reasons.append(f"{top_count} top headline{'s' if top_count != 1 else ''}")
            score += top_count * 3
        if current_point is not None and current_point.news_burst_score >= 1.0:
            reasons.append(f"news burst {current_point.news_burst_score:+.1f}")
            score += min(current_point.news_burst_score * 4, 8)

        if item.ticker.position.status == "holding":
            reasons.append("holding")
            score += 3
        book_view = position_view(item)
        book_impact = _as_float(book_view.get("book_impact"))
        if book_impact is not None:
            reasons.append(f"book impact {format_pct(book_impact)}")
            score += min(abs(book_impact) * 2, 8)

        eps_revision = _metric_float(item, "fy1_eps_revision_30d")
        if eps_revision is not None:
            if eps_revision < -0.5:
                reasons.append(f"EPS rev {format_pct(eps_revision)}")
                score += 4
            elif eps_revision > 1.0:
                reasons.append(f"EPS rev {format_pct(eps_revision)}")
                score += 2

        revenue_growth = _metric_float(item, "revenue_growth_pct")
        if revenue_growth is not None and revenue_growth < 0:
            reasons.append(f"revenue growth {format_pct(revenue_growth, sign=False)}")
            score += 2
        revenue_revision = _metric_float(item, "fy1_revenue_revision_30d")
        if revenue_revision is not None:
            if revenue_revision < -0.5:
                reasons.append(f"revenue rev {format_pct(revenue_revision)}")
                score += 3
            elif revenue_revision > 1.0:
                reasons.append(f"revenue rev {format_pct(revenue_revision)}")
                score += 2
        if state.thesis_state in {"weakening", "broken"}:
            reasons.append(f"thesis {state.thesis_state}")
            score += 6
        stale_days = _days_since_last_review(state, report.generated_at)
        if stale_days is None and state.thesis_state in {"building", "active"}:
            reasons.append("thesis never reviewed")
            score += 4
        elif stale_days is not None and stale_days >= 14 and state.thesis_state in {"building", "active"}:
            reasons.append(f"review stale {stale_days}d")
            score += 3
        review = post_earnings_review_for(report, symbol)
        if delta is not None and -7 <= delta < 0 and not _post_earnings_review_complete(review):
            reasons.append("post-earnings review due")
            score += 5

        if score > 0:
            review_candidates.append((score, item, reasons))

        if event_blocked:
            event_reasons = [
                "event risk",
                "no action before earnings review" if delta == 0 else "no action before event review",
            ]
            if pmove is not None and abs(pmove) >= 2.0:
                event_reasons.append(f"premarket {format_pct(pmove)}")
            if top_count:
                event_reasons.append(f"{top_count} top headline{'s' if top_count != 1 else ''}")
            no_action_before_event.append((score + abs(pmove or 0), item, event_reasons))
            continue

        overextended = valuation_risk_label(item) in ("High", "Extreme")
        rsi = rsi_value(item)
        q = quality_of_move(item)
        if (pmove is not None and pmove >= 2.0) or (daily_change_pct(item) or 0) >= 3.0:
            chase_reasons = []
            if pmove is not None and pmove >= 2.0:
                chase_reasons.append(f"premarket {format_pct(pmove)}")
            if rsi is not None and rsi >= 70:
                chase_reasons.append(f"RSI {rsi:.0f}")
            if overextended:
                chase_reasons.append(f"{valuation_risk_label(item)} valuation")
            if q:
                chase_reasons.extend(q[:1])
            if len(chase_reasons) >= 2:
                avoid_chase.append((len(chase_reasons) + abs(pmove or 0), item, chase_reasons))

        from_high = from_52w_high_pct(item)
        if from_high is not None and -12.0 <= from_high <= -3.0:
            pb_reasons = [f"{abs(from_high):.1f}% below 52w high"]
            if item.articles:
                pb_reasons.append(f"{len(item.articles)} headline{'s' if len(item.articles) != 1 else ''}")
            if valuation_risk_label(item) in ("None", "Elevated"):
                pb_reasons.append("less stretched")
            pullback_setup.append((100 + from_high + len(item.articles), item, pb_reasons))
        elif symbol in gaps and (pmove := premarket_change_pct(report, symbol)) is not None and pmove < -2.0:
            pullback_setup.append((abs(pmove), item, [f"premarket pullback {format_pct(pmove)}"]))

    def pack(rows: list[tuple[float, TickerReport, list[str]]]) -> list[dict[str, object]]:
        return [
            {"item": item, "score": score, "reasons": reasons[:6]}
            for score, item, reasons in sorted(rows, key=lambda row: (-row[0], row[1].ticker.symbol))[:3]
        ]

    return {
        "review_first": pack(review_candidates),
        "no_action_before_event": pack(no_action_before_event),
        "pullback_setup": pack(pullback_setup),
        "avoid_chase": pack(avoid_chase),
        "do_not_chase": pack(avoid_chase),
        "watch_pullback": pack(pullback_setup),
    }


def capital_allocation_queue(report: DailyReport) -> dict[str, list[dict[str, object]]]:
    """Rank tickers by deployable-capital action buckets."""
    benchmarks = report.market_context.benchmark_returns if report.market_context else {}
    buckets: dict[str, list[dict[str, object]]] = {grade: [] for grade in ("A", "B", "C", "D", "E")}

    for item in report.ticker_reports:
        symbol = item.ticker.symbol
        state = research_state_for(report, symbol)
        score = right_side_score(item, benchmarks) or {}
        score_value = int(score.get("score", 0) or 0)
        status = str(score.get("status", "Unscored"))
        eps_revision = _metric_float(item, "fy1_eps_revision_30d")
        rsi = rsi_value(item)
        delta = earnings_delta(item, report.report_date)
        thesis = state.thesis_state or "unmarked"
        reasons: list[str] = []

        if thesis != "unmarked":
            reasons.append(f"thesis {thesis}")
        if score_value:
            reasons.append(f"score {score_value}")
        if eps_revision is not None:
            reasons.append(f"EPS rev {format_pct(eps_revision)}")
        if rsi is not None:
            reasons.append(f"RSI {rsi:.0f}")
        if delta is not None and 0 <= delta <= 1:
            reasons.append("event window")

        overhot = (rsi is not None and rsi >= 70) or status == "Extended, do not chase" or _is_overextended(item)
        eps_up = eps_revision is not None and eps_revision > 0.5
        eps_down = eps_revision is not None and eps_revision < -0.5

        if thesis in {"weakening", "broken"} or eps_down:
            grade, action = "E", "Do not add / consider trim"
        elif delta is not None and 0 <= delta <= 1:
            grade, action = "C", "Review only before event"
        elif overhot:
            grade, action = "D", "No chase"
        elif thesis == "active" and score_value > 70 and eps_up:
            grade, action = "A", "Priority add candidate"
        elif thesis == "active" and score_value >= 60:
            grade, action = "B", "Wait for pullback"
        else:
            grade, action = "C", "Watch / no fresh capital"

        buckets[grade].append(
            {
                "grade": grade,
                "action": action,
                "item": item,
                "score": score_value,
                "status": status,
                "reasons": reasons[:5],
            }
        )

    for rows in buckets.values():
        rows.sort(key=lambda row: (-int(row["score"]), row["item"].ticker.symbol))
    return buckets


def book_impact_ranking(report: DailyReport) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for item in report.ticker_reports:
        pos = item.ticker.position
        if pos.status != "holding" or pos.portfolio_weight is None:
            continue
        move = premarket_change_pct(report, item.ticker.symbol)
        move_source = "premarket"
        if move is None:
            move = daily_change_pct(item)
            move_source = "latest daily"
        if move is None:
            continue
        impact = pos.portfolio_weight * (move / 100.0)
        action = "Review now" if abs(impact) >= 0.25 or top_news_count(item) or earnings_delta(item, report.report_date) in (0, 1) else "Monitor"
        rows.append({
            "item": item,
            "move": move,
            "move_source": move_source,
            "weight": pos.portfolio_weight,
            "impact": impact,
            "action": action,
        })
    return sorted(rows, key=lambda row: abs(float(row["impact"])), reverse=True)[:8]


def book_today_summary(report: DailyReport) -> list[dict[str, object]]:
    """Four-card portfolio lens for the morning home view."""
    impact_rows = book_impact_ranking(report)
    holdings = [item for item in report.ticker_reports if item.ticker.position.status == "holding"]
    cards: list[dict[str, object]] = []

    positive = [row for row in impact_rows if isinstance(row.get("impact"), (int, float)) and float(row["impact"]) > 0]
    negative = [row for row in impact_rows if isinstance(row.get("impact"), (int, float)) and float(row["impact"]) < 0]
    if positive:
        row = max(positive, key=lambda r: float(r["impact"]))
        cards.append(_book_card(
            "Biggest positive impact",
            row["item"],
            format_pct(row["impact"]),
            f"{format_pct(row['move'])} {row['move_source']} | {format_pct(row['weight'], sign=False)} weight",
            "pos",
        ))
    if negative:
        row = min(negative, key=lambda r: float(r["impact"]))
        cards.append(_book_card(
            "Biggest negative impact",
            row["item"],
            format_pct(row["impact"]),
            f"{format_pct(row['move'])} {row['move_source']} | {format_pct(row['weight'], sign=False)} weight",
            "neg",
        ))

    risk_rows: list[tuple[float, TickerReport, list[str]]] = []
    risk_rank = {"None": 0, "Elevated": 2, "High": 5, "Extreme": 8}
    for item in holdings:
        reasons: list[str] = []
        score = 0.0
        risk = valuation_risk_label(item)
        score += risk_rank.get(risk, 0)
        if risk != "None":
            reasons.append(f"{risk} valuation")
        rsi = rsi_value(item)
        if rsi is not None and rsi >= 70:
            score += 3
            reasons.append(f"RSI {rsi:.0f}")
        eps_revision = _metric_float(item, "fy1_eps_revision_30d")
        if eps_revision is not None and eps_revision < -0.5:
            score += 3
            reasons.append(f"EPS rev {format_pct(eps_revision)}")
        revenue_revision = _metric_float(item, "fy1_revenue_revision_30d")
        if revenue_revision is not None and revenue_revision < -0.5:
            score += 2
            reasons.append(f"revenue rev {format_pct(revenue_revision)}")
        delta = earnings_delta(item, report.report_date)
        if delta is not None and 0 <= delta <= 7:
            score += 3
            reasons.append("event soon")
        impact = next((float(row["impact"]) for row in impact_rows if row["item"] is item), 0.0)
        score += min(abs(impact) * 2, 4)
        if impact:
            reasons.append(f"book {format_pct(impact)}")
        if score > 0:
            risk_rows.append((score, item, reasons))
    if risk_rows:
        _score, item, reasons = sorted(risk_rows, key=lambda row: (-row[0], row[1].ticker.symbol))[0]
        cards.append(_book_card(
            "Highest risk holding",
            item,
            item.ticker.symbol,
            " | ".join(reasons[:3]),
            "warn",
        ))

    event_rows: list[tuple[int, float, TickerReport]] = []
    for item in holdings:
        delta = earnings_delta(item, report.report_date)
        if delta is not None and 0 <= delta <= 7:
            weight = item.ticker.position.portfolio_weight or 0.0
            event_rows.append((delta, -weight, item))
    if event_rows:
        delta, _weight_sort, item = sorted(event_rows)[0]
        when = "today" if delta == 0 else "tomorrow" if delta == 1 else f"in {delta}d"
        weight = item.ticker.position.portfolio_weight
        detail = f"earnings {when}"
        if weight is not None:
            detail += f" | {format_pct(weight, sign=False)} weight"
        cards.append(_book_card("Holding with event soon", item, item.ticker.symbol, detail, "info"))

    return cards[:4]


def _book_card(label: str, item: TickerReport, value: object, detail: str, tone: str) -> dict[str, object]:
    return {
        "label": label,
        "item": item,
        "value": value,
        "detail": detail,
        "tone": tone,
    }


def position_view(item: TickerReport) -> dict[str, object]:
    pos = item.ticker.position
    last = _as_float(item.valuation.metrics.get("last_close")) if item.valuation else None
    prev = _as_float(item.valuation.metrics.get("previous_close")) if item.valuation else None
    shares = pos.shares
    avg_cost = pos.avg_cost
    position_size = pos.position_size
    if position_size is None and shares is not None and last is not None:
        position_size = shares * last
    pl_pct = None
    pl_dollar = None
    if avg_cost is not None and avg_cost > 0 and last is not None:
        pl_pct = (last - avg_cost) / avg_cost * 100.0
        if shares is not None:
            pl_dollar = (last - avg_cost) * shares
    book_impact = None
    if pos.portfolio_weight is not None and prev is not None and last is not None and prev:
        book_impact = pos.portfolio_weight * ((last - prev) / prev)
    stop_distance_pct = None
    stop_distance_tone = "flat"
    if pos.stop_loss is not None and pos.stop_loss > 0 and last is not None:
        stop_distance_pct = (last - pos.stop_loss) / pos.stop_loss * 100.0
        if stop_distance_pct <= 2.0:
            stop_distance_tone = "danger"
        elif stop_distance_pct <= 5.0:
            stop_distance_tone = "warn"
        else:
            stop_distance_tone = "ok"
    sector = pos.sector
    if not sector and item.valuation:
        sector_value = item.valuation.metrics.get("sector")
        if isinstance(sector_value, str):
            sector = sector_value
    return {
        "status": pos.status,
        "shares": shares,
        "avg_cost": avg_cost,
        "portfolio_weight": pos.portfolio_weight,
        "position_size": position_size,
        "pl_pct": pl_pct,
        "pl_dollar": pl_dollar,
        "book_impact": book_impact,
        "stop_loss": pos.stop_loss,
        "stop_distance_pct": stop_distance_pct,
        "stop_distance_tone": stop_distance_tone,
        "sector": sector,
    }


def daily_change_pct(item: TickerReport) -> float | None:
    """Return today's price change % vs previous close, or None if unavailable."""
    if not item.valuation:
        return None
    last = item.valuation.metrics.get("last_close")
    prev = item.valuation.metrics.get("previous_close")
    if not isinstance(last, (int, float)) or not isinstance(prev, (int, float)):
        return None
    if last != last or prev != prev or prev == 0:
        return None
    return (last - prev) / prev * 100.0


def format_pct(value: object, *, sign: bool = True) -> str:
    """Format a percentage with optional sign. Returns 'N/A' for missing/NaN."""
    if not isinstance(value, (int, float)):
        return "N/A"
    if value != value:
        return "N/A"
    fmt = "{:+.2f}%" if sign else "{:.2f}%"
    return fmt.format(value)


def format_twn_timestamp(value: object) -> str:
    """Format a report timestamp in Taiwan time for static HTML headers."""
    if not isinstance(value, datetime):
        return "N/A"
    if value.tzinfo is not None:
        value = value.astimezone(ZoneInfo("Asia/Taipei"))
    return f"{value.strftime('%Y-%m-%d %H:%M')} TWN / UTC+8"


def format_twn_datetime(value: object) -> str:
    """Format as Taiwan Time with an explicit UTC+8 label."""
    if not isinstance(value, datetime):
        return "N/A"
    if value.tzinfo is not None:
        value = value.astimezone(ZoneInfo("Asia/Taipei"))
    return f"{value.strftime('%Y-%m-%d %H:%M')} Taiwan Time (UTC+8)"


def format_utc_timestamp(value: object) -> str:
    """Format as an unambiguous UTC timestamp."""
    if not isinstance(value, datetime):
        return "N/A"
    if value.tzinfo is not None:
        value = value.astimezone(ZoneInfo("UTC"))
    return f"{value.strftime('%Y-%m-%d %H:%M')} UTC"


def format_et_timestamp(value: object) -> str:
    """Format as US Eastern time with ET rather than ambiguous zone names."""
    if not isinstance(value, datetime):
        return "N/A"
    if value.tzinfo is not None:
        value = value.astimezone(ZoneInfo("America/New_York"))
    return f"{value.strftime('%Y-%m-%d %H:%M')} ET"


def format_ratio(value: object) -> str:
    if not isinstance(value, (int, float)):
        return "N/A"
    if value != value:
        return "N/A"
    return f"{value:.2f}x"


def eps_revision_class(value: object) -> str:
    if not isinstance(value, (int, float)) or value != value:
        return "flat"
    if value > 0.5:
        return "pos"
    if value < -0.5:
        return "neg"
    return "flat"


def eps_power_summary(item: TickerReport) -> str:
    if not item.valuation:
        return ""
    metrics = item.valuation.metrics
    growth = _as_float(metrics.get("eps_growth_pct"))
    revision = _as_float(metrics.get("fy1_eps_revision_30d"))
    ttm_eps = _as_float(metrics.get("ttm_eps"))
    next_fy_eps = _as_float(metrics.get("next_fy_eps"))

    parts: list[str] = []
    if ttm_eps is not None and ttm_eps <= 0:
        parts.append("EPS negative / unstable")
    elif growth is not None:
        if growth >= 5:
            parts.append(f"EPS: FY1 +{growth:.0f}%")
        elif growth <= -5:
            parts.append(f"EPS: FY1 {growth:.0f}%")
        else:
            parts.append("EPS: flat")
    elif next_fy_eps is not None:
        parts.append(f"Next FY EPS {next_fy_eps:.2f}")

    if revision is not None:
        if revision > 0.5:
            parts.append("revisions up")
        elif revision < -0.5:
            parts.append("revisions down")
        else:
            parts.append("flat revisions")

    return " | ".join(parts)


def change_class(value: object, *, threshold: float = 0.0) -> str:
    """CSS class for a percentage value: pos / neg / flat."""
    if not isinstance(value, (int, float)) or value != value:
        return ""
    if value > threshold:
        return "pos"
    if value < -threshold:
        return "neg"
    return "flat"


def from_52w_high_pct(item: TickerReport) -> float | None:
    """Distance from 52-week high as a (negative) percentage."""
    if not item.valuation:
        return None
    last = item.valuation.metrics.get("last_close")
    high = item.valuation.metrics.get("fifty_two_week_high")
    if not isinstance(last, (int, float)) or not isinstance(high, (int, float)):
        return None
    if last != last or high != high or high == 0:
        return None
    return (last - high) / high * 100.0


def quality_of_move(item: TickerReport) -> list[str]:
    """Compact quality signals for whether a daily move has confirmation."""
    if not item.valuation:
        return []
    metrics = item.valuation.metrics
    parts: list[str] = []

    change = daily_change_pct(item)
    volume_x = _as_float(metrics.get("volume_vs_20d"))
    if change is not None and volume_x is not None:
        parts.append(f"{format_pct(change)} on {volume_x:.1f}x volume")
    elif change is not None:
        parts.append(f"{format_pct(change)} today")
    elif volume_x is not None:
        parts.append(f"{volume_x:.1f}x volume")

    gap = _as_float(metrics.get("gap_percent"))
    if gap is not None and abs(gap) >= 1.0:
        direction = "up" if gap > 0 else "down"
        parts.append(f"gap {direction} {abs(gap):.1f}%")

    move_vs_atr = _as_float(metrics.get("move_vs_atr"))
    if move_vs_atr is not None:
        if move_vs_atr >= 1.0:
            parts.append(f"move > 20D ATR ({move_vs_atr:.1f}x)")
        elif move_vs_atr >= 0.7:
            parts.append(f"move {move_vs_atr:.1f}x ATR")

    return parts


def sectors_in_use(report: DailyReport) -> list[str]:
    """Distinct sectors present in the watchlist, sorted alphabetically."""
    seen: set[str] = set()
    for tr in report.ticker_reports:
        if tr.valuation:
            sector = tr.valuation.metrics.get("sector")
            if isinstance(sector, str) and sector.strip():
                seen.add(sector.strip())
    return sorted(seen)


def clusters_in_use(report: DailyReport) -> list[str]:
    """Distinct custom sector clusters for matching keywords."""
    return [label for label, _ in SECTOR_GROUPS]


def ticker_cluster(item: TickerReport) -> str | None:
    """Which custom cluster does this ticker belong to (based on keywords)?"""
    for label, terms in SECTOR_GROUPS:
        if _matches_sector_group(item, terms):
            return label.lower()
    return None


def holding_currencies(tickers: list[object]) -> set[str]:
    """Currencies across holdings that can contribute to P&L math.

    Shared predicate for the mixed-currency guards: a holding only affects
    summed P&L when it has a share count, so a shares-less "holding" must not
    trip the warning while the weight math happily proceeds.
    """
    return {
        ticker.currency  # type: ignore[attr-defined]
        for ticker in tickers
        if ticker.position.status == "holding" and ticker.position.shares is not None  # type: ignore[attr-defined]
    }


def derive_portfolio_weights(report: DailyReport) -> DailyReport:
    """Fill in portfolio_weight for holdings that lack one, from position size.

    Weight = position_size / total holdings size, where size = shares × last_close
    (falling back to shares × avg_cost when price is unavailable). Manually-set
    weights are preserved, so a user override always wins.
    """
    sizes: dict[str, float] = {}
    for tr in report.ticker_reports:
        pos = tr.ticker.position
        if pos.status != "holding" or pos.shares is None:
            continue
        last = _as_float(tr.valuation.metrics.get("last_close")) if tr.valuation else None
        price = last if last is not None else pos.avg_cost
        if price is None or price <= 0:
            continue
        sizes[tr.ticker.symbol] = pos.shares * price

    if len(holding_currencies([tr.ticker for tr in report.ticker_reports])) > 1:
        return report
    total = sum(sizes.values())
    if total <= 0:
        return report

    new_reports: list[TickerReport] = []
    changed = False
    for tr in report.ticker_reports:
        pos = tr.ticker.position
        if pos.status == "holding" and pos.portfolio_weight is None and tr.ticker.symbol in sizes:
            weight = round(sizes[tr.ticker.symbol] / total * 100.0, 2)
            new_pos = replace(pos, portfolio_weight=weight)
            new_reports.append(replace(tr, ticker=replace(tr.ticker, position=new_pos)))
            changed = True
        else:
            new_reports.append(tr)

    if not changed:
        return report
    return replace(report, ticker_reports=new_reports)


def portfolio_impact_summary(report: DailyReport) -> dict[str, object]:
    """Aggregate today's per-position impact for the My Book panel.

    For each ticker with status='holding' and a non-zero portfolio_weight:
      - daily_change %
      - book_impact = daily_change × (weight/100) → portfolio % contribution
      - has_event_soon = earnings within 3 days
      - has_thesis_risk = ticker is overextended OR has data warnings
    """
    anchor = report.report_date
    overextended_symbols = {
        entry["item"].ticker.symbol for entry in overextended_tickers(report)
    }

    rows: list[dict[str, object]] = []
    for tr in report.ticker_reports:
        pos = tr.ticker.position
        if not pos or pos.status != "holding":
            continue
        weight = pos.portfolio_weight
        if not isinstance(weight, (int, float)) or weight == 0:
            continue

        change_raw = daily_change_pct(tr)
        change_pct = None
        book_impact = None
        if isinstance(change_raw, (int, float)) and change_raw == change_raw:
            change_pct = round(float(change_raw), 2)
            book_impact = round(change_pct * (float(weight) / 100.0), 3)

        delta = None
        if tr.earnings and tr.earnings.earnings_date:
            delta = (tr.earnings.earnings_date - anchor).days
        event_soon = isinstance(delta, int) and 0 <= delta <= 3

        thesis_risk = (
            tr.ticker.symbol in overextended_symbols
            or bool(tr.warnings)
        )

        last = _as_float(tr.valuation.metrics.get("last_close")) if tr.valuation else None
        pl_pct = None
        pl_dollar = None
        cost_basis = None
        market_value = None
        if pos.avg_cost is not None and pos.avg_cost > 0 and last is not None:
            pl_pct = round((last - pos.avg_cost) / pos.avg_cost * 100.0, 2)
            if pos.shares is not None:
                pl_dollar = round((last - pos.avg_cost) * pos.shares, 2)
                cost_basis = pos.shares * pos.avg_cost
                market_value = pos.shares * last

        rows.append({
            "symbol": tr.ticker.symbol,
            "company": tr.ticker.company_name,
            "currency": tr.ticker.currency,
            "weight": round(float(weight), 2),
            "change_pct": change_pct,
            "book_impact": book_impact,
            "pl_pct": pl_pct,
            "pl_dollar": pl_dollar,
            "cost_basis": cost_basis,
            "market_value": market_value,
            "earnings_days": delta,
            "event_soon": event_soon,
            "thesis_risk": thesis_risk,
            "ticker_report": tr,
        })

    rows.sort(key=lambda r: abs(r["book_impact"] or 0), reverse=True)

    impactful = [r for r in rows if isinstance(r["book_impact"], (int, float))]
    winners = sorted(
        (r for r in impactful if r["book_impact"] > 0),
        key=lambda r: r["book_impact"],
        reverse=True,
    )[:3]
    losers = sorted(
        (r for r in impactful if r["book_impact"] < 0),
        key=lambda r: r["book_impact"],
    )[:3]

    pl_rows = [r for r in rows if isinstance(r["pl_pct"], (int, float))]
    pl_leaders = sorted(
        (r for r in pl_rows if r["pl_pct"] > 0),
        key=lambda r: r["pl_pct"],
        reverse=True,
    )[:3]
    pl_laggards = sorted(
        (r for r in pl_rows if r["pl_pct"] < 0),
        key=lambda r: r["pl_pct"],
    )[:3]

    event_soon = [r for r in rows if r["event_soon"]]
    thesis_risk = [r for r in rows if r["thesis_risk"]]

    total_impact = round(sum(r["book_impact"] or 0 for r in rows), 3)
    total_weight = round(sum(float(r["weight"]) for r in rows), 2)

    holding_currencies = sorted({str(r["currency"]) for r in rows if r.get("currency")})
    mixed_currency = len(holding_currencies) > 1
    total_cost = sum(r["cost_basis"] for r in rows if isinstance(r["cost_basis"], (int, float)))
    total_mv = sum(r["market_value"] for r in rows if isinstance(r["market_value"], (int, float)))
    total_pl_dollar = round(total_mv - total_cost, 2) if total_cost > 0 and not mixed_currency else None
    total_pl_pct = round((total_mv - total_cost) / total_cost * 100.0, 2) if total_cost > 0 and not mixed_currency else None

    sectors = sector_concentration(report)
    stop_warnings = stop_distance_warnings(report)

    settings = getattr(report, "settings", None)
    portfolio_settings = getattr(settings, "portfolio", None) if settings else None
    addable_cash = getattr(portfolio_settings, "addable_cash", None) if portfolio_settings else None
    total_value = getattr(portfolio_settings, "total_value", None) if portfolio_settings else None
    max_single_weight = getattr(portfolio_settings, "max_single_weight", None) if portfolio_settings else None

    concentration_threshold = max_single_weight if max_single_weight is not None else DEFAULT_MAX_SINGLE_WEIGHT
    over_concentrated = sorted(
        (r for r in rows if isinstance(r["weight"], (int, float)) and r["weight"] > concentration_threshold),
        key=lambda r: r["weight"],
        reverse=True,
    )

    return {
        "holdings": rows,
        "winners": winners,
        "losers": losers,
        "pl_leaders": pl_leaders,
        "pl_laggards": pl_laggards,
        "event_soon": event_soon,
        "thesis_risk": thesis_risk,
        "total_impact_pct": total_impact,
        "total_weight_pct": total_weight,
        "total_pl_dollar": total_pl_dollar,
        "total_pl_pct": total_pl_pct,
        "currencies": holding_currencies,
        "mixed_currency": mixed_currency,
        "sectors": sectors,
        "stop_warnings": stop_warnings,
        "addable_cash": addable_cash,
        "total_value": total_value,
        "over_concentrated": over_concentrated,
        "max_single_weight": max_single_weight,
        "concentration_threshold": concentration_threshold,
    }


def portfolio_brief(report: DailyReport) -> str:
    """Compact plain-text portfolio summary (3–6 lines) for pasting into notes."""
    summary = portfolio_impact_summary(report)
    rows = summary["holdings"]
    lines = [f"Portfolio Brief - {report.report_date.isoformat()}"]
    if not rows:
        lines.append("No holdings configured.")
        return "\n".join(lines)

    parts = [f"Net impact today {format_pct(summary['total_impact_pct'])}"]
    if summary["total_pl_dollar"] is not None:
        parts.append(f"unrealized P&L ${summary['total_pl_dollar']:+,.0f} ({format_pct(summary['total_pl_pct'])})")
    parts.append(f"invested {format_pct(summary['total_weight_pct'], sign=False)}")
    lines.append(" | ".join(parts))

    impactful = [r for r in rows if isinstance(r["book_impact"], (int, float))]
    if impactful:
        drag = min(impactful, key=lambda r: r["book_impact"])
        if drag["book_impact"] < 0:
            lines.append(
                f"Biggest drag: {drag['symbol']} {format_pct(drag['book_impact'])} "
                f"({format_pct(drag['change_pct'])} x {format_pct(drag['weight'], sign=False)}w)"
            )
        lift = max(impactful, key=lambda r: r["book_impact"])
        if lift["book_impact"] > 0:
            lines.append(
                f"Biggest lift: {lift['symbol']} {format_pct(lift['book_impact'])} "
                f"({format_pct(lift['change_pct'])} x {format_pct(lift['weight'], sign=False)}w)"
            )

    leaders = ", ".join(f"{r['symbol']} {format_pct(r['pl_pct'])}" for r in summary["pl_leaders"])
    laggards = ", ".join(f"{r['symbol']} {format_pct(r['pl_pct'])}" for r in summary["pl_laggards"])
    ret_parts = []
    if leaders:
        ret_parts.append(f"Leaders: {leaders}")
    if laggards:
        ret_parts.append(f"Laggards: {laggards}")
    if ret_parts:
        lines.append(" | ".join(ret_parts))

    flags = []
    if summary["over_concentrated"]:
        flags.append(
            "concentration "
            + ", ".join(f"{r['symbol']} {format_pct(r['weight'], sign=False)}" for r in summary["over_concentrated"])
        )
    risk_names = [
        tr.ticker.symbol
        for tr in report.ticker_reports
        if tr.ticker.position.status == "holding" and valuation_risk_label(tr) in ("High", "Extreme")
    ]
    if risk_names:
        flags.append("valuation risk " + ", ".join(risk_names))
    if flags:
        lines.append("Flags - " + " | ".join(flags))

    soon = []
    for tr in report.ticker_reports:
        if tr.ticker.position.status != "holding":
            continue
        delta = earnings_delta(tr, report.report_date)
        if delta is not None and 0 <= delta <= 7:
            when = "today" if delta == 0 else "tomorrow" if delta == 1 else f"in {delta}d"
            soon.append(f"{tr.ticker.symbol} {when}")
    if soon:
        lines.append("Earnings <=7d: " + ", ".join(soon))

    return "\n".join(lines)


def sector_concentration(report: DailyReport) -> list[dict[str, object]]:
    """Group holdings by sector and aggregate weight + count.

    Sector source: PositionConfig.sector first, valuation.metrics["sector"] fallback.
    """
    buckets: dict[str, dict[str, object]] = {}
    for tr in report.ticker_reports:
        pos = tr.ticker.position
        if not pos or pos.status != "holding":
            continue
        weight = pos.portfolio_weight
        if not isinstance(weight, (int, float)) or weight == 0:
            continue
        sector = pos.sector or ""
        if not sector and tr.valuation:
            raw = tr.valuation.metrics.get("sector")
            if isinstance(raw, str):
                sector = raw
        if not sector and tr.ticker.market == "crypto":
            sector = "Crypto"
        sector = (sector or "Unspecified").strip() or "Unspecified"
        bucket = buckets.setdefault(sector, {"sector": sector, "weight": 0.0, "tickers": []})
        bucket["weight"] = float(bucket["weight"]) + float(weight)
        bucket["tickers"].append(tr.ticker.symbol)  # type: ignore[union-attr]
    out = list(buckets.values())
    for bucket in out:
        bucket["weight"] = round(float(bucket["weight"]), 2)
        bucket["count"] = len(bucket["tickers"])  # type: ignore[arg-type]
    out.sort(key=lambda b: float(b["weight"]), reverse=True)

    settings = getattr(report, "settings", None)
    portfolio_settings = getattr(settings, "portfolio", None) if settings else None
    cap = getattr(portfolio_settings, "max_sector_weight", None) if portfolio_settings else None
    if cap is not None:
        for bucket in out:
            bucket["over_cap"] = float(bucket["weight"]) > float(cap)
            bucket["cap"] = float(cap)
    return out


def stop_distance_warnings(report: DailyReport) -> list[dict[str, object]]:
    """Holdings whose last_close is within 5% of stop_loss, sorted by distance."""
    out: list[dict[str, object]] = []
    for tr in report.ticker_reports:
        pos = tr.ticker.position
        if not pos or pos.status != "holding":
            continue
        if pos.stop_loss is None or pos.stop_loss <= 0:
            continue
        last = _as_float(tr.valuation.metrics.get("last_close")) if tr.valuation else None
        if last is None:
            continue
        distance_pct = (last - pos.stop_loss) / pos.stop_loss * 100.0
        if distance_pct > 5.0:
            continue
        out.append({
            "symbol": tr.ticker.symbol,
            "last": last,
            "stop_loss": pos.stop_loss,
            "distance_pct": round(distance_pct, 2),
            "tone": "danger" if distance_pct <= 2.0 else "warn",
            "weight": pos.portfolio_weight,
        })
    return sorted(out, key=lambda row: float(row["distance_pct"]))


def overextended_tickers(report: DailyReport) -> list[dict[str, object]]:
    """Tickers ringing multiple "danger" bells at once — caution-on-entry list.

    Three core conditions:
      - RSI ≥ 70                                  (overbought)
      - Within 5% of 52-week high                 (no margin from peak)
      - Trailing or Forward P/E ≥ 100             (extreme valuation)

    Threshold: at least 2 of the 3 must trigger. A ticker hitting all 3 is
    the loudest "wait for pullback" signal the dashboard can produce.
    """
    out: list[dict[str, object]] = []
    for tr in report.ticker_reports:
        if not tr.valuation:
            continue
        m = tr.valuation.metrics
        flags: list[str] = []

        rsi = _as_float(m.get("rsi_14"))
        if rsi is not None and rsi >= 70:
            flags.append(f"RSI {rsi:.0f}")

        from_high = from_52w_high_pct(tr)
        if from_high is not None and from_high >= -5.0:
            flags.append("near 52w high")

        for key in ("trailing_pe", "forward_pe"):
            pe = _as_float(m.get(key))
            if pe is not None and pe >= 100:
                flags.append(f"{METRIC_LABELS[key]} {pe:.0f}")
                break

        if len(flags) >= 2:
            out.append({"item": tr, "score": len(flags), "reasons": flags})

    return sorted(out, key=lambda entry: entry["score"], reverse=True)


def macro_risk_meter(context: MarketContext | None) -> list[dict[str, str]]:
    if context is None:
        return []

    rates = context.rates
    yields = [r for r in rates if r.unit == "bp"]
    dxy = next((r for r in rates if r.name == "DXY"), None)
    wti = next((r for r in rates if r.name == "WTI"), None)
    rows: list[dict[str, str]] = []

    if yields:
        avg_bp = sum(r.change for r in yields) / len(yields)
        rows.append({
            "name": "Rates pressure",
            "level": _risk_level(avg_bp, medium=2.0, high=5.0),
            "detail": f"{avg_bp:+.1f}bp avg yield move",
        })

    if dxy is not None:
        rows.append({
            "name": "Dollar pressure",
            "level": _risk_level(dxy.change, medium=0.25, high=0.50),
            "detail": f"DXY {dxy.change:+.2f}%",
        })

    if wti is not None:
        rows.append({
            "name": "Oil inflation pressure",
            "level": _risk_level(wti.change, medium=1.0, high=2.0),
            "detail": f"WTI {wti.change:+.2f}%",
        })

    return rows


# Order matters: assignment is exclusive (first match wins), so the more
# specific groups sit above the broader ones — Memory before Semis keeps MU in
# Memory; Internet/ads before software keeps GOOGL out of the "cloud" bucket.
# ETF sits after Crypto so BTC's "ETF flows" keyword doesn't hijack it.
SECTOR_GROUPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Memory", ("memory", "dram", "nand", "hbm", "ssd", "wdc", "stx", "記憶體")),
    ("Semis", ("semiconductor", "semi", "chip", "gpu", "soxx", "nvda", "amd", "avgo", "tsm", "asml", "arm", "半導體", "晶圓")),
    ("Internet / ads", ("advertising", "ads", "search", "social", "internet", "googl", "meta", "amzn")),
    ("Mega-cap software", ("software", "cloud", "azure", "copilot", "msft", "crm", "adbe", "orcl")),
    ("EV", ("electric vehicle", "autonomous", "tesla", "tsla", "rivn", "nio", "電動車")),
    ("Consumer hardware", ("iphone", "consumer electronics", "wearables", "smartphone", "aapl")),
    ("Space", ("space launch", "rocket", "satellite", "spacex", "rklb")),
    ("Crypto", ("crypto", "bitcoin", "ethereum", "blockchain", "btc-usd", "eth-usd", "加密")),
    ("ETF / Index", ("etf", "指數", "index fund")),
    ("AI infra", ("ai", "data center", "server", "networking", "accelerator", "gpu", "伺服器")),
)

SECTOR_GROUP_LABELS_ZH: dict[str, str] = {
    "Semis": "半導體",
    "Mega-cap software": "大型軟體",
    "Memory": "記憶體",
    "EV": "電動車",
    "Internet / ads": "網路 / 廣告",
    "Consumer hardware": "消費電子",
    "Space": "太空",
    "Crypto": "加密貨幣",
    "ETF / Index": "ETF / 指數",
    "AI infra": "AI 基礎設施",
    "Other watchlist": "其他觀察",
}

# Taiwan-market sector chains — matched against watchlist keywords/aliases.
# Same exclusive first-match rule: specific chains sit above broad ones, so
# 載板 / PCB is checked before the broader 封測 (封裝/測試) group, and 代工 in
# the assembly group cannot steal 晶圓代工 names.
TW_SECTOR_GROUPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("載板 / PCB", ("abf 載板", "bt 載板", "ic 載板", "載板", "substrate", "pcb", "hdi")),
    ("封測", ("封測", "封裝", "測試", "osat", "sip")),
    ("晶圓代工", ("晶圓代工", "晶圓", "先進製程", "cowos", "foundry")),
    ("IC 設計", ("ic 設計", "ic設計", "fabless", "矽智財")),
    ("記憶體", ("記憶體", "dram", "nand")),
    ("功率元件", ("功率元件", "功率半導體", "mosfet", "igbt", "碳化矽", "氮化鎵")),
    ("被動元件", ("被動元件", "mlcc", "電容", "電阻", "電感")),
    ("電源 / 重電", ("電源", "重電", "變壓器", "充電樁")),
    ("散熱", ("散熱", "均熱", "水冷")),
    ("光通訊 / 網通", ("光通訊", "光收發", "矽光子", "cpo", "網通")),
    ("AI 伺服器 / 組裝", ("伺服器", "組裝", "ems", "代工", "機殼")),
    ("金融", ("金融", "金控", "銀行", "壽險")),
    ("航運", ("航運", "貨櫃", "散裝")),
    ("ETF / 指數", ("etf", "指數")),
)

# Crypto pairs all end in -USD, so this is a catch-all single group.
CRYPTO_SECTOR_GROUPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("加密貨幣", ("crypto", "bitcoin", "ethereum", "blockchain", "加密", "-usd")),
)

# Keys are MARKET_PANELS panel keys, not raw ticker markets.
SECTOR_GROUPS_BY_MARKET: dict[str, tuple[tuple[str, tuple[str, ...]], ...]] = {
    "taiwan": TW_SECTOR_GROUPS,
    "crypto": CRYPTO_SECTOR_GROUPS,
}

# Sector-map view panels: (panel key, member ticker markets, display label).
# twse + tpex share one 台股 panel — they trade in the same session. Keys must
# match the ticker-card market tabs ("us" / "taiwan" / "crypto") so both UIs
# share one market state in the report.
MARKET_PANELS: tuple[tuple[str, tuple[str, ...], str], ...] = (
    ("us", ("us",), "美股"),
    ("taiwan", ("twse", "tpex"), "台股"),
    ("crypto", ("crypto",), "加密貨幣"),
)


def map_change_bin(value: object) -> str:
    """Diverging bin for the sector-map tile: intensity in 3 steps per side.

    Thresholds ±0.5 / ±1.5 / ±3.0 (%) keep the map at 7 color classes; |v| ≤ 0.5
    reads as neutral so small noise doesn't paint the map.
    """
    if not isinstance(value, (int, float)) or value != value:
        return "na"
    if value >= 3.0:
        return "up-3"
    if value >= 1.5:
        return "up-2"
    if value > 0.5:
        return "up-1"
    if value <= -3.0:
        return "down-3"
    if value <= -1.5:
        return "down-2"
    if value < -0.5:
        return "down-1"
    return "flat"


def _map_tile(item: TickerReport) -> dict[str, object]:
    change = daily_change_pct(item)
    return {
        "symbol": item.ticker.display_symbol,
        "anchor": f"ticker-{item.ticker.symbol.lower()}",
        "company": item.ticker.company_name,
        "change": change,
        "bin": map_change_bin(change),
        "ret_5d": _metric_float(item, "return_5d"),
        "ret_20d": _metric_float(item, "return_20d"),
        "market_cap": _metric_float(item, "market_cap"),
    }


def sector_map_markets(report: DailyReport) -> list[dict[str, object]]:
    """Sector map split into one panel per market (美股 / 台股 / 加密貨幣).

    Markets trade in different sessions, so group averages are only meaningful
    within one market. Panels follow MARKET_PANELS order; markets absent from
    the watchlist render no panel. An unknown future market gets its own panel
    at the end rather than being silently dropped.
    """
    spy_20d = None
    if report.market_context and report.market_context.benchmark_returns:
        spy_20d = report.market_context.benchmark_returns.get("spy_20d")

    panels: list[dict[str, object]] = []
    known_markets: set[str] = set()
    for key, markets, label in MARKET_PANELS:
        known_markets.update(markets)
        items = [item for item in report.ticker_reports if item.ticker.market in markets]
        # SPY is only a sensible benchmark for the US session.
        rows = _sector_rows(items, spy_20d if key == "us" else None, key, label)
        if rows:
            panels.append(_market_panel(key, label, rows))

    leftover = [item for item in report.ticker_reports if item.ticker.market not in known_markets]
    if leftover:
        rows = _sector_rows(leftover, None, "other", "其他市場")
        panels.append(_market_panel("other", "其他市場", rows))
    return panels


def _market_panel(key: str, label: str, rows: list[dict[str, object]]) -> dict[str, object]:
    """Panel dict with market breadth (漲跌家數) derived from the map tiles.

    Every ticker appears in exactly one tile (exclusive group assignment plus
    the Other-watchlist catch-all), so tiles are the single source for both the
    ticker count and today's advance/decline tally — breadth can never disagree
    with the tiles it sits above.
    """
    advancers = decliners = flat = 0
    ticker_count = 0
    for row in rows:
        for tile in row["tiles"]:  # type: ignore[union-attr]
            ticker_count += 1
            change = tile["change"]
            if not isinstance(change, (int, float)):
                continue
            if change > 0:
                advancers += 1
            elif change < 0:
                decliners += 1
            else:
                flat += 1
    return {
        "key": key,
        "label": label,
        "rows": rows,
        "ticker_count": ticker_count,
        "advancers": advancers,
        "decliners": decliners,
        "flat": flat,
    }


def sector_leadership(report: DailyReport) -> list[dict[str, object]]:
    """Flat sector rows across all market panels, for the detail table."""
    return [row for panel in sector_map_markets(report) for row in panel["rows"]]


def _sector_rows(
    items: list[TickerReport],
    benchmark_20d: object,
    market_key: str,
    market_label: str,
) -> list[dict[str, object]]:
    """Group one market's tickers into sector rows ranked by today's move.

    Each market uses its own sector taxonomy (SECTOR_GROUPS_BY_MARKET) — the
    台股 panel groups by local chains like 封測/功率元件/被動元件 rather than
    the US watchlist themes. Assignment is exclusive — the first matching group
    wins — so a ticker never shows up twice on the sector map. Each row also
    carries `tiles` (per-member map cells, biggest market cap first) and
    `label_zh`.
    """
    sector_groups = SECTOR_GROUPS_BY_MARKET.get(market_key, SECTOR_GROUPS)
    grouped: dict[str, list[TickerReport]] = {label: [] for label, _ in sector_groups}
    other: list[TickerReport] = []
    for item in items:
        for label, terms in sector_groups:
            if _matches_sector_group(item, terms):
                grouped[label].append(item)
                break
        else:
            other.append(item)
    if other:
        grouped["Other watchlist"] = other

    rows: list[dict[str, object]] = []
    for label, members in grouped.items():
        if not members:
            continue
        one_day = _avg_metric(members, daily_change_pct)
        ret_5d = _avg_metric(members, lambda item: _metric_float(item, "return_5d"))
        ret_20d = _avg_metric(members, lambda item: _metric_float(item, "return_20d"))
        rel_spy = (
            ret_20d - benchmark_20d
            if ret_20d is not None and isinstance(benchmark_20d, (int, float))
            else None
        )
        by_cap = sorted(
            members,
            key=lambda item: -(_metric_float(item, "market_cap") or 0.0),
        )
        rows.append({
            "label": label,
            "label_zh": SECTOR_GROUP_LABELS_ZH.get(label, label),
            "market": market_key,
            "market_label": market_label,
            "symbols": ", ".join(item.ticker.symbol for item in members[:6]),
            "tiles": [_map_tile(item) for item in by_cap],
            "one_day": one_day,
            "ret_5d": ret_5d,
            "ret_20d": ret_20d,
            "rel_spy": rel_spy,
        })

    return sorted(
        rows,
        key=lambda row: (
            row["one_day"] is None,
            -(row["one_day"] if row["one_day"] is not None else -999),
        ),
    )


def premarket_triage(report: DailyReport) -> dict[str, list[dict[str, object]]]:
    if not report.premarket:
        return {"catalyst_backed": [], "unclear": []}
    by_symbol = _ticker_map(report)
    catalyst_backed: list[dict[str, object]] = []
    unclear: list[dict[str, object]] = []
    for move in report.premarket.watchlist_movers:
        item = by_symbol.get(move.symbol)
        if item is None:
            continue
        headline_count = len(item.articles)
        best_source = max((int(source_reliability(article)["score"]) for article in item.articles), default=0)
        best_label = "no linked headline"
        if item.articles:
            best_article = max(item.articles, key=lambda article: int(source_reliability(article)["score"]))
            best_label = str(source_reliability(best_article)["label"])
        delta = earnings_delta(item, report.report_date)
        move_vs_atr = _metric_float(item, "move_vs_atr")
        volume_x = _metric_float(item, "volume_vs_20d")
        reasons: list[str] = []
        if headline_count:
            reasons.append(f"{headline_count} headline{'s' if headline_count != 1 else ''}")
            reasons.append(best_label)
        if delta is not None and -1 <= delta <= 1:
            reasons.append("earnings window")
        if move_vs_atr is not None and move_vs_atr >= 1.0:
            reasons.append(f"> ATR ({move_vs_atr:.1f}x)")
        if volume_x is not None and volume_x >= 1.5:
            reasons.append(f"{volume_x:.1f}x volume")
        confidence = "high" if best_source >= 2 or len(reasons) >= 3 else "medium" if headline_count or len(reasons) >= 2 else "low"
        row = {
            "move": move,
            "item": item,
            "reasons": reasons,
            "headline_count": headline_count,
            "source_tier": best_label,
            "confidence": confidence,
        }
        if headline_count or (delta is not None and -1 <= delta <= 1) or len(reasons) >= 2:
            catalyst_backed.append(row)
        else:
            unclear.append(row)

    return {
        "catalyst_backed": catalyst_backed[:8],
        "unclear": unclear[:8],
    }


def _matches_sector_group(item: TickerReport, terms: tuple[str, ...]) -> bool:
    text = " ".join([
        item.ticker.symbol,
        item.ticker.company_name,
        *item.ticker.aliases,
        *item.ticker.keywords,
        str(item.valuation.metrics.get("sector", "")) if item.valuation else "",
        str(item.valuation.metrics.get("industry", "")) if item.valuation else "",
    ]).lower()
    return any(_sector_term_matches(text, term) for term in terms)


def _sector_term_matches(text: str, term: str) -> bool:
    """Match a sector-group term, guarding short ASCII tokens with boundaries.

    Bare substring matching let "mu" fire inside "communication", "ai" inside
    "sustain", "ems" inside "systems". Short alphanumeric ASCII tokens (≤4
    chars: symbols and acronyms like ai / tsm / hbm / etf) therefore require
    non-alphanumeric neighbours; longer terms and CJK terms keep substring
    semantics ("semiconductor" in "semiconductors", "封裝" in "半導體封裝").
    """
    term = term.lower()
    if len(term) <= 4 and term.isascii() and term.isalnum():
        return re.search(rf"(?<![a-z0-9]){re.escape(term)}(?![a-z0-9])", text) is not None
    return term in text


def _metric_float(item: TickerReport, key: str) -> float | None:
    if not item.valuation:
        return None
    return _as_float(item.valuation.metrics.get(key))


def _avg_metric(items: list[TickerReport], getter: object) -> float | None:
    values = []
    for item in items:
        value = getter(item)  # type: ignore[operator]
        if value is not None:
            values.append(value)
    if not values:
        return None
    return round(sum(values) / len(values), 2)


def _risk_level(value: float, *, medium: float, high: float) -> str:
    if value >= high:
        return "high"
    if value >= medium:
        return "medium"
    return "low"


# Within this percent of 20D SMA (from above) - "Near 20D support".
# Defined as a module constant so the rule is documented and uniform.
NEAR_SUPPORT_PCT = 2.0


def ma_signals(item: TickerReport) -> list[str]:
    """Short trend signals from simple moving averages.

    Unified grammar - direction first, MAs joined by " / ":
      - "Above 20D / 60D / 120D"
      - "Above 20D / 60D, below 120D"
      - "Below 20D / 60D / 120D"
      - "Near 20D support"   (within NEAR_SUPPORT_PCT% above SMA20)
      - "5D below 20D"       (SMA5 >=1% below SMA20)

    Empty list when SMAs are unavailable (new IPOs, halted symbols).
    """
    if not item.valuation:
        return []
    metrics = item.valuation.metrics
    last = _as_float(metrics.get("last_close"))
    if last is None:
        return []

    sma5 = _as_float(metrics.get("sma_5"))
    sma20 = _as_float(metrics.get("sma_20"))
    sma60 = _as_float(metrics.get("sma_60"))
    sma120 = _as_float(metrics.get("sma_120"))

    above: list[str] = []
    below: list[str] = []
    for label, sma in (("20D", sma20), ("60D", sma60), ("120D", sma120)):
        if sma is None:
            continue
        if last >= sma:
            above.append(label)
        else:
            below.append(label)

    signals: list[str] = []
    if above and below:
        signals.append(f"Above {' / '.join(above)}, below {' / '.join(below)}")
    elif above:
        signals.append(f"Above {' / '.join(above)}")
    elif below:
        signals.append(f"Below {' / '.join(below)}")

    if sma20 and last >= sma20 and (last - sma20) / sma20 * 100 <= NEAR_SUPPORT_PCT:
        signals.append("Near 20D support")

    if sma5 is not None and sma20 is not None and sma5 < sma20 * 0.99:
        signals.append("5D below 20D")

    return signals


def ma_distances(item: TickerReport) -> dict[str, float]:
    """Distance from each available SMA in percent (signed).

    Example: {"20D": 2.1, "60D": 5.3, "120D": 8.4}
    Useful for hover tooltips and the compare panel.
    """
    if not item.valuation:
        return {}
    metrics = item.valuation.metrics
    last = _as_float(metrics.get("last_close"))
    if last is None:
        return {}
    out: dict[str, float] = {}
    for label, key in (("20D", "sma_20"), ("60D", "sma_60"), ("120D", "sma_120")):
        sma = _as_float(metrics.get(key))
        if sma is None or sma == 0:
            continue
        out[label] = round((last - sma) / sma * 100.0, 2)
    return out


def format_ma_distances(item: TickerReport) -> str:
    """Compact one-liner for the Trend tooltip: '20D +2.1% | 60D +5.3% | 120D +8.4%'."""
    parts: list[str] = []
    for label, pct in ma_distances(item).items():
        sign = "+" if pct >= 0 else ""
        parts.append(f"{label} {sign}{pct:.1f}%")
    return " | ".join(parts)


def trend_tone(signals: list[str]) -> str:
    """Color-tone class for the Trend insight row."""
    if not signals:
        return ""
    text = " ".join(signals)
    has_above = "Above" in text
    has_below = "Below" in text or "5D below" in text or "below" in text
    if has_below and not has_above:
        return "down"
    if has_above and has_below:
        return "mixed"
    if has_above:
        return "up"
    return ""


def _as_float(value: object) -> float | None:
    if not isinstance(value, (int, float)):
        return None
    if value != value:  # NaN
        return None
    return float(value)


def from_52w_low_pct(item: TickerReport) -> float | None:
    """Distance above 52-week low as a positive percentage."""
    if not item.valuation:
        return None
    last = item.valuation.metrics.get("last_close")
    low = item.valuation.metrics.get("fifty_two_week_low")
    if not isinstance(last, (int, float)) or not isinstance(low, (int, float)):
        return None
    if last != last or low != low or low == 0:
        return None
    return (last - low) / low * 100.0


_MARKET_SORT_RANK: dict[str, int] = {
    market: rank for rank, (_key, markets, _label) in enumerate(MARKET_PANELS) for market in markets
}


def sort_by_market_cap(items: list[TickerReport]) -> list[TickerReport]:
    """Sort tickers by market, then market cap descending within each market.

    Market caps are in local currency (TWD vs USD), so a global sort would rank
    2330's 26T TWD ahead of every US name; comparing caps is only meaningful
    within one market. Missing/NaN market cap goes last within its market.
    """
    def key(item: TickerReport) -> tuple[int, int, float, str]:
        rank = _MARKET_SORT_RANK.get(item.ticker.market, len(MARKET_PANELS))
        if item.valuation:
            mc = item.valuation.metrics.get("market_cap")
            if isinstance(mc, (int, float)) and mc == mc:
                return (rank, 0, -float(mc), item.ticker.symbol)
        return (rank, 1, 0.0, item.ticker.symbol)
    return sorted(items, key=key)


def news_tier(article: object) -> str:
    score = getattr(article, "importance_score", None)
    if not isinstance(score, (int, float)):
        return "minor"
    if score >= 1.0:
        return "top"
    if score >= 0.7:
        return "primary"
    return "minor"


def hero_items(report: DailyReport) -> list[dict[str, object]]:
    """The 1-3 most decision-pressing things today.

    Priorities by tone (loudest first): revisit dates due today, imminent
    earnings cluster, imminent macro event, valuation-watch list (tickers
    with stretched P/E), top news fallback. Returns at most 3 cards.
    """
    anchor = report.report_date
    items: list[dict[str, object]] = []

    revisit_due = [
        s
        for s, state in report.research_states.items()
        if state.revisit_date and state.revisit_date == anchor
    ]
    if revisit_due:
        items.append({
            "kind": "revisit",
            "tone": "imminent",
            "label": "Revisit due today",
            "headline": ", ".join(sorted(revisit_due)),
            "subtitle": f"{len(revisit_due)} ticker{'s' if len(revisit_due) != 1 else ''}",
            "anchor": "#ticker-grid",
        })

    earnings_by_day: dict[int, list[TickerReport]] = {}
    for tr in report.ticker_reports:
        if tr.earnings and tr.earnings.earnings_date:
            delta = (tr.earnings.earnings_date - anchor).days
            if 0 <= delta <= 3:
                earnings_by_day.setdefault(delta, []).append(tr)

    for delta in sorted(earnings_by_day):
        tickers = earnings_by_day[delta]
        symbols = [t.ticker.symbol for t in tickers]
        when = "today" if delta == 0 else "tomorrow" if delta == 1 else f"in {delta}d"
        items.append({
            "kind": "earnings",
            "tone": "imminent" if delta <= 1 else "soon",
            "label": f"Earnings {when}",
            "headline": ", ".join(symbols),
            "subtitle": f"{len(symbols)} ticker{'s' if len(symbols) != 1 else ''}",
            "anchor": "#earnings",
        })

    for ev in report.economic_events:
        delta = (ev.event_datetime.date() - anchor).days
        if 0 <= delta <= 2:
            when = "today" if delta == 0 else "tomorrow" if delta == 1 else f"in {delta}d"
            items.append({
                "kind": "macro",
                "tone": "imminent" if delta == 0 else "soon",
                "label": f"Macro {when}",
                "headline": ev.name,
                "subtitle": f"{format_twn_timestamp(ev.event_datetime)} / {format_et_timestamp(ev.event_datetime)}",
                "anchor": "#macro",
            })
            break

    if report.market_sentiment and len(items) < 3:
        sentiment = report.market_sentiment
        tone = "info"
        if sentiment.score <= 24 or sentiment.score >= 76:
            tone = "imminent"
        elif sentiment.score <= 44 or sentiment.score >= 56:
            tone = "soon"
        items.append({
            "kind": "sentiment",
            "tone": tone,
            "label": "Market sentiment",
            "headline": f"{sentiment.score} / 100",
            "subtitle": sentiment.label,
            "anchor": "#market-sentiment",
        })

    stretched = _stretched_valuation_tickers(report)
    if stretched and len(items) < 3:
        symbols = [t.ticker.symbol for t in stretched[:5]]
        items.append({
            "kind": "valuation",
            "tone": "info",
            "label": "Valuation watch",
            "headline": ", ".join(symbols),
            "subtitle": f"{len(stretched)} ticker{'s' if len(stretched) != 1 else ''} with P/E >=100",
            "anchor": "#valuation",
        })

    if not items:
        top = important_news(report, limit=1)
        if top:
            tr, article, _tier = top[0]
            items.append({
                "kind": "news",
                "tone": "info",
                "label": event_label(article.event_type),
                "headline": article.title,
                "subtitle": f"{tr.ticker.symbol} | {article.source}",
                "anchor": "#news",
            })

    return items[:3]


def morning_briefing_cards(report: DailyReport) -> list[dict[str, object]]:
    """First-screen briefing: regime, premarket tone, top risk, and focus."""
    cards: list[dict[str, object]] = []

    regime_headline = "盤勢檢查"
    regime_subtitle = "沒有市場背景資料。"
    regime_tone = "info"
    risks = macro_risk_meter(report.market_context)
    high_risks = [risk for risk in risks if risk["level"] == "high"]
    medium_risks = [risk for risk in risks if risk["level"] == "medium"]
    if high_risks:
        lead = high_risks[0]
        regime_headline = zh_text(str(lead["name"]).replace(" pressure", " 壓力"))
        regime_subtitle = zh_text(lead["detail"])
        regime_tone = "soon"
    elif medium_risks:
        lead = medium_risks[0]
        regime_headline = zh_text(str(lead["name"]).replace(" pressure", " 壓力升溫"))
        regime_subtitle = zh_text(lead["detail"])
        regime_tone = "info"
    elif report.market_sentiment:
        regime_headline = f"{zh_text(report.market_sentiment.label)} 盤勢"
        regime_subtitle = f"市場情緒 {report.market_sentiment.score} / 100"
        regime_tone = "imminent" if report.market_sentiment.score <= 24 or report.market_sentiment.score >= 76 else "info"
    cards.append({
        "kind": "regime",
        "label": "盤勢",
        "headline": regime_headline,
        "subtitle": regime_subtitle,
        "tone": regime_tone,
        "anchor": "#rates" if report.market_context and report.market_context.rates else "#market-sentiment",
    })

    pm_headline = "無盤前快照"
    pm_subtitle = "啟用行情抓取後可顯示 ES/NQ/SPY/QQQ 盤前基調。"
    pm_tone = "info"
    if report.premarket and report.premarket.benchmarks:
        parts = []
        values: list[float] = []
        for move in report.premarket.benchmarks[:3]:
            if move.change_pct is None:
                continue
            parts.append(f"{move.symbol} {format_pct(move.change_pct)}")
            values.append(move.change_pct)
        if parts:
            avg = sum(values) / len(values)
            pm_headline = ", ".join(parts[:2])
            pm_subtitle = "盤前偏多" if avg > 0.15 else "盤前偏空" if avg < -0.15 else "盤前中性"
            pm_tone = "info" if avg >= 0 else "soon"
    cards.append({
        "kind": "premarket",
        "label": "盤前",
        "headline": pm_headline,
        "subtitle": pm_subtitle,
        "tone": pm_tone,
        "anchor": "#premarket",
    })

    stretched = overextended_tickers(report)
    macro_warning_count = sum(1 for warning in report.warnings if "macro" in warning.lower())
    risk_bits: list[str] = []
    if stretched:
        risk_bits.append(f"{len(stretched)} 檔過熱")
    if macro_warning_count:
        risk_bits.append(f"{macro_warning_count} 個總經警示")
    if not risk_bits and rule_alerts(report):
        risk_bits.append(f"{len(rule_alerts(report))} 個規則警示")
    cards.append({
        "kind": "risk",
        "label": "主要風險",
        "headline": "、".join(risk_bits) if risk_bits else "沒有主要盤面風險",
        "subtitle": "追價前先檢查估值與資料品質。" if risk_bits else "目前沒有明顯過熱或資料風險群聚。",
        "tone": "imminent" if macro_warning_count or len(stretched) >= 5 else "soon" if stretched else "info",
        "anchor": "#overextended" if stretched else "#global-warnings" if macro_warning_count else "#rule-alerts",
    })

    focus = todays_focus(report)
    focus_symbols = [str(row["item"].ticker.symbol) for row in focus["review_first"][:3]]
    cards.append({
        "kind": "focus",
        "label": "今日焦點",
        "headline": " / ".join(focus_symbols) if focus_symbols else "沒有急件",
        "subtitle": "依持股、催化、缺口、預估修正與警示排序。" if focus_symbols else "目前規則下沒有需要優先檢視的項目。",
        "tone": "info",
        "anchor": "#todays-focus",
    })
    return cards


def daily_summary(report: DailyReport, limit: int = 6) -> dict[str, object]:
    """Compact first-read summary for deciding whether to drill in.

    This deliberately reuses existing report signals instead of inventing new
    sentiment. The output is short, clickable, and ordered by decision value.
    """
    actions = morning_actions(report)
    focus = todays_focus(report)
    news = important_news(report, limit=5)
    earnings = earnings_soon(report)
    macro_near = [
        event for event in report.economic_events
        if 0 <= (event.event_datetime.date() - report.report_date).days <= 1
    ]
    items: list[dict[str, object]] = []
    seen: set[str] = set()

    def add(
        label: str,
        headline: str,
        detail: str,
        anchor: str,
        tone: str = "info",
        *,
        key: str | None = None,
    ) -> None:
        if len(items) >= limit:
            return
        item_key = key or anchor
        if item_key in seen:
            return
        seen.add(item_key)
        items.append({
            "label": label,
            "headline": headline,
            "detail": detail,
            "anchor": anchor,
            "tone": tone,
        })

    for action in actions[:2]:
        label, headline, detail = _daily_summary_action_text(action)
        add(
            label,
            headline,
            detail,
            str(action.get("anchor") or "#morning-actions"),
            str(action.get("tone") or "warn"),
            key=str(action.get("ticker") or action.get("anchor") or headline),
        )

    def add_focus_bucket(bucket: str, label: str, headline_suffix: str, fallback: str, tone: str) -> None:
        rows = focus.get(bucket, [])[:3]
        if not rows:
            return
        symbols = [row["item"].ticker.symbol for row in rows]
        detail = _daily_summary_reasons(rows[0].get("reasons", [])) or fallback
        first_symbol = symbols[0]
        add(
            label,
            f"{', '.join(symbols)} {headline_suffix}",
            detail,
            f"#ticker-{first_symbol.lower()}",
            tone,
            key=f"{bucket}:{','.join(symbols)}",
        )

    add_focus_bucket(
        "no_action_before_event",
        "事件前暫停",
        "先不要動作",
        "事件窗口內，等財報或催化落地後再判斷。",
        "warn",
    )
    add_focus_bucket(
        "avoid_chase",
        "避免追高",
        "先不要追",
        "技術或估值已延伸，等回檔或新催化。",
        "warn",
    )
    add_focus_bucket(
        "pullback_setup",
        "回檔機會",
        "可列入觀察",
        "接近回檔買點，確認價格和風險後再決定。",
        "good",
    )
    add_focus_bucket(
        "review_first",
        "需要研究",
        "需要先看",
        "同時有持股、催化、缺口或研究狀態訊號。",
        "info",
    )

    for card in book_today_summary(report)[:2]:
        item = card["item"]
        symbol = item.ticker.symbol
        add(
            _daily_summary_book_label(str(card["label"])),
            f"{symbol} {card['value']}",
            _daily_summary_reasons([str(card["detail"])]),
            f"#ticker-{symbol.lower()}",
            str(card.get("tone") or "info"),
            key=symbol,
        )

    for tr, article, tier in news[:3]:
        symbol = tr.ticker.symbol
        tone = "danger" if tier == "top" else "info"
        add(
            "重點新聞",
            f"{symbol}: {article.title}",
            f"{article.source} · {event_label(article.event_type)}",
            "#news",
            tone,
            key=f"news:{symbol}:{article.url}",
        )

    if earnings:
        symbols = ", ".join(item.ticker.symbol for item in earnings[:4])
        more = "" if len(earnings) <= 4 else f" 等 {len(earnings)} 檔"
        add(
            "財報提醒",
            f"{symbols}{more}",
            "7 天內有財報，先看持股、估值和最近新聞。",
            "#earnings",
            "warn",
            key="earnings",
        )

    if macro_near:
        event = sorted(macro_near, key=lambda ev: ev.event_datetime)[0]
        add(
            "總經提醒",
            event.name,
            f"{format_twn_timestamp(event.event_datetime)} / {format_et_timestamp(event.event_datetime)}",
            "#macro",
            "warn",
            key="macro",
        )

    if not items:
        add(
            "今日摘要",
            "沒有明顯急件",
            "可先快速掃過持股、新聞與個股卡，再決定是否深入研究。",
            "#tickers",
            "info",
            key="quiet",
        )

    detail_parts: list[str] = []
    if actions:
        detail_parts.append(f"{len(actions)} 個先處理")
    if focus.get("avoid_chase"):
        detail_parts.append(f"{len(focus['avoid_chase'])} 檔避免追高")
    if focus.get("pullback_setup"):
        detail_parts.append(f"{len(focus['pullback_setup'])} 檔回檔機會")
    if focus.get("review_first"):
        detail_parts.append(f"{len(focus['review_first'])} 檔需要研究")
    if news:
        detail_parts.append(f"{len(news)} 則重點新聞")
    if earnings:
        detail_parts.append(f"{len(earnings)} 檔 7 天內財報")
    if macro_near:
        detail_parts.append(f"{len(macro_near)} 個近端總經事件")
    if not detail_parts:
        detail_parts.append("目前沒有高優先級訊號")

    tone = "danger" if actions else "warn" if earnings or macro_near else "info"
    headline = f"今天分成 {len(items)} 個決策入口" if items and items[0]["headline"] != "沒有明顯急件" else "今天偏平穩"
    return {
        "headline": headline,
        "detail": " · ".join(detail_parts),
        "tone": tone,
        "items": items,
    }


def _daily_summary_action_text(action: dict[str, object]) -> tuple[str, str, str]:
    symbol = str(action.get("ticker") or "").strip()
    raw_label = str(action.get("label") or "")
    raw_headline = str(action.get("headline") or "")
    raw_detail = str(action.get("detail") or "")

    if raw_label == "Earnings":
        return "先決定", f"{symbol} 財報即將公布", "先確認指引、估值和最近新聞。"
    if raw_label == "Gap":
        return "盤前缺口", zh_text(raw_headline).replace("gapped", "盤前跳空"), "先確認隔夜原因，再決定是否追價。"
    if raw_label == "Thesis":
        return "論點風險", f"{symbol} 投資論點需要重看", "論點已轉弱或失效，先不要直接加碼。"
    if "Stop" in raw_label or "stop" in raw_label.lower():
        return "停損提醒", f"{symbol} 接近停損", zh_text(raw_detail)
    if raw_label in _PLAN_KIND_LABELS.values():
        return "交易計畫", zh_text(raw_headline), zh_text(raw_detail)
    return "先決定", zh_text(raw_headline), zh_text(raw_detail)


def _daily_summary_book_label(label: str) -> str:
    labels = {
        "Biggest positive impact": "持股助攻",
        "Biggest negative impact": "持股拖累",
        "Highest risk holding": "持股風險",
        "Holding with event soon": "持股財報",
    }
    return labels.get(label, "持股")


def _daily_summary_reasons(reasons: object) -> str:
    if isinstance(reasons, str):
        parts = [reasons]
    else:
        parts = [str(reason) for reason in list(reasons)[:3]]
    text = "、".join(part for part in parts if part)
    replacements = {
        "earnings today": "今日財報",
        "earnings tomorrow": "明日財報",
        "post-earnings review": "財報後檢視",
        "post-earnings review due": "待做財報後檢視",
        "premarket": "盤前",
        "top headlines": "則重點新聞",
        "top headline": "則重點新聞",
        "news burst": "新聞放量",
        "holding": "已持有",
        "book impact": "持股影響",
        "EPS rev": "EPS 預估",
        "revenue rev": "營收預估",
        "revenue growth": "營收成長",
        "thesis never reviewed": "論點尚未檢視",
        "review stale": "檢視已過久",
        "event soon": "近期事件",
        "valuation": "估值",
        "weight": "持股比重",
        "latest daily": "最新日線",
        "less stretched": "估值壓力較低",
        " on ": " / ",
        "book": "持股影響",
    }
    for src, dest in replacements.items():
        text = text.replace(src, dest)
    return zh_text(text)


def priority_items(report: DailyReport) -> list[dict[str, object]]:
    """Small ordered worklist for the top of the HTML dashboard."""
    priorities: list[dict[str, object]] = []
    for item in hero_items(report):
        priorities.append({
            "label": item["label"],
            "headline": item["headline"],
            "subtitle": item["subtitle"],
            "anchor": item["anchor"],
            "tone": item["tone"],
        })

    existing = {str(item["headline"]) for item in priorities}
    for alert in rule_alerts(report):
        headline = str(alert["title"])
        if headline in existing:
            continue
        priorities.append({
            "label": "Rule alert",
            "headline": headline,
            "subtitle": alert["detail"],
            "anchor": alert["anchor"],
            "tone": alert["tone"],
        })
        existing.add(headline)
        if len(priorities) >= 4:
            break
    return priorities[:4]


def rule_alerts(report: DailyReport) -> list[dict[str, object]]:
    """Merged rule-based alerts from existing report data only; no invented facts."""
    alerts: list[dict[str, object]] = []
    for tr in report.ticker_reports:
        symbol = tr.ticker.symbol
        anchor = f"#ticker-{symbol.lower()}"
        delta = earnings_delta(tr, report.report_date)
        earnings_soon_flag = delta is not None and 0 <= delta <= 7
        highest_news = max((article.importance_score for article in tr.articles), default=0.0)
        top_news_count = sum(1 for article in tr.articles if article.importance_score >= 1.0)
        high_pe = _highest_pe(tr)
        rsi = rsi_value(tr)
        eps_revision = _metric_float(tr, "fy1_eps_revision_30d")
        signals: list[str] = []
        details: list[str] = []
        rank = 0
        tone = "warn"

        def add(signal: str, detail: str, *, signal_tone: str = "warn", signal_rank: int = 1) -> None:
            nonlocal rank, tone
            if signal not in signals:
                signals.append(signal)
            if detail and detail not in details:
                details.append(detail)
            rank += signal_rank
            if signal_tone == "danger":
                tone = "danger"

        if earnings_soon_flag:
            when = days_until(tr.earnings.earnings_date, report.report_date)
            if delta is not None and delta <= 1:
                add(f"earnings {when}", "Review guidance, valuation, and recent news before the print.", signal_tone="danger", signal_rank=5)
            elif high_pe is not None or highest_news >= 1.0 or not tr.articles:
                add(f"earnings {when}", "Earnings date is inside the 7-day review window.", signal_rank=2)

        if high_pe is not None and high_pe[1] >= 100:
            label, value = high_pe
            signal = "extreme valuation" if value >= 200 else "stretched valuation"
            alert_tone = "danger" if value >= 200 else "warn"
            add(signal, f"{METRIC_LABELS[label]} {value:.0f}.", signal_tone=alert_tone, signal_rank=4 if value >= 200 else 3)

        if eps_revision is not None:
            if eps_revision < -0.5:
                add("EPS revisions down", f"FY1 EPS revision {eps_revision:.1f}% over 30D.", signal_tone="danger" if high_pe else "warn", signal_rank=3)
            elif eps_revision > 1.0 and high_pe is not None and high_pe[1] >= 100:
                add("high multiple but EPS revisions up", f"FY1 EPS revision +{eps_revision:.1f}% over 30D.", signal_rank=2)

        if earnings_soon_flag and not tr.articles:
            add("no trusted news", f"{days_until(tr.earnings.earnings_date, report.report_date)}; verify company and source updates.", signal_rank=2)

        if earnings_soon_flag and highest_news >= 1.0:
            signal = "heavy news flow" if len(tr.articles) >= 4 else "top-tier news"
            add(signal, f"{len(tr.articles)} trusted headline(s), {top_news_count} top-tier.", signal_tone="danger", signal_rank=4)

        if high_pe is not None and high_pe[1] >= 100 and (highest_news >= 1.0 or len(tr.articles) >= 4):
            add("crowded setup", f"{len(tr.articles)} headline(s); revisit thesis before chasing.", signal_rank=2)

        if rsi is not None and rsi >= 70:
            if high_pe is not None and high_pe[1] >= 100:
                add("overbought technicals", _overbought_detail(tr, rsi, "stretched valuation"), signal_rank=3)
            elif tr.articles and card_state(tr, report.report_date) == "hot":
                add("hot but overbought", _overbought_detail(tr, rsi, "avoid chasing without a fresh catalyst"), signal_rank=2)

        if rsi is not None and rsi <= 30 and earnings_soon_flag:
            add("oversold into earnings", f"RSI 14 {rsi:.0f}; review whether weakness is technical or thesis-related.", signal_rank=2)

        stop_alert = _stop_loss_alert(tr)
        if stop_alert is not None:
            detail, alert_tone, alert_rank = stop_alert
            add("stop-loss alert", detail, signal_tone=alert_tone, signal_rank=alert_rank)

        if tr.warnings:
            add("data warnings", f"{len(tr.warnings)} data warning(s).", signal_rank=1)

        if not signals:
            continue

        alerts.append({
            "symbol": symbol,
            "title": f"{symbol}: {' + '.join(signals[:3])}",
            "detail": " ".join(details[:3]),
            "tone": tone,
            "anchor": anchor,
            "rank": rank,
            "delta": delta if delta is not None and delta >= 0 else 999,
        })

    tone_rank = {"danger": 0, "warn": 1, "info": 2}
    return sorted(alerts, key=lambda item: (tone_rank.get(str(item["tone"]), 9), item["delta"], -item["rank"], str(item["symbol"])))


def _overbought_detail(item: TickerReport, rsi: float, conclusion: str) -> str:
    detail = f"RSI 14 {rsi:.0f}"
    from_high = from_52w_high_pct(item)
    if from_high is not None:
        detail += f", {format_pct(from_high)} from 52W high"
    return f"{detail}; {conclusion}."


def _stop_loss_alert(item: TickerReport) -> tuple[str, str, int] | None:
    pos = item.ticker.position
    if pos.status != "holding" or pos.stop_loss is None or pos.stop_loss <= 0:
        return None
    last = _as_float(item.valuation.metrics.get("last_close")) if item.valuation else None
    if last is None:
        return None
    distance_pct = (last - pos.stop_loss) / pos.stop_loss * 100.0
    if distance_pct > 5.0:
        return None
    tone = "danger" if distance_pct <= 2.0 else "warn"
    rank = 4 if tone == "danger" else 3
    detail = f"Last ${last:.2f} is {format_pct(distance_pct)} from stop ${pos.stop_loss:.2f}."
    if pos.portfolio_weight is not None:
        detail += f" {format_pct(pos.portfolio_weight, sign=False)} weight."
    return detail, tone, rank


_PRICE_TOKEN_RE = re.compile(r"\d+(?:,\d{3})*(?:\.\d+)?")

_PLAN_KIND_LABELS = {
    "entry": "Entry zone",
    "add": "Add zone",
    "reduce": "Reduce zone",
    "stop": "Plan stop",
}


def _parse_price_levels(text: str) -> list[float]:
    """Pull positive numeric price tokens out of free-text plan fields."""
    if not text:
        return []
    levels: list[float] = []
    for token in _PRICE_TOKEN_RE.findall(text):
        try:
            value = float(token.replace(",", ""))
        except ValueError:
            continue
        if value > 0:
            levels.append(value)
    return sorted(set(levels))


def _plausible_levels(levels: list[float], last_close: float | None) -> list[float]:
    """Drop tokens that are implausible as a price near the current close.

    Guards against stray numbers in plan text (e.g. "hold 30 days") by keeping
    only values within 0.3x–3x of the last close.
    """
    if last_close is None or last_close <= 0:
        return levels
    lo, hi = last_close * 0.3, last_close * 3.0
    return [level for level in levels if lo <= level <= hi]


def _evaluate_zone(direction: str, last: float, lo: float, hi: float) -> tuple[str, str] | None:
    """Return (status, tone) if the price triggers the zone, else None."""
    if direction == "buy":
        if last <= hi:
            return ("in_zone" if last >= lo else "below_zone"), "good"
        return None
    if direction == "sell":
        if last >= lo:
            return ("in_zone" if last <= hi else "above_zone"), "info"
        return None
    if direction == "stop":
        if last <= hi:
            return "breached", "danger"
        return None
    return None


def plan_triggers(report: DailyReport) -> list[dict[str, object]]:
    """Live triggers where the current price has reached a plan zone.

    Parses the free-text investment-plan fields into numeric levels and compares
    them against last_close, so written plans become actionable signals.
    """
    triggers: list[dict[str, object]] = []
    for tr in report.ticker_reports:
        symbol = tr.ticker.symbol
        last = _as_float(tr.valuation.metrics.get("last_close")) if tr.valuation else None
        if last is None:
            continue
        state = research_state_for(report, symbol)
        anchor = f"#ticker-{symbol.lower()}"
        for kind, text, direction in (
            ("entry", state.entry_plan, "buy"),
            ("add", state.add_zone, "buy"),
            ("reduce", state.reduce_zone, "sell"),
            ("stop", state.stop_loss, "stop"),
        ):
            levels = _plausible_levels(_parse_price_levels(text), last)
            if not levels:
                continue
            lo, hi = levels[0], levels[-1]
            evaluated = _evaluate_zone(direction, last, lo, hi)
            if evaluated is None:
                continue
            status, tone = evaluated
            label = _PLAN_KIND_LABELS[kind]
            display_label = {
                "entry": "進場區",
                "add": "加碼區",
                "reduce": "減碼區",
                "stop": "計畫停損",
            }[kind]
            if kind == "stop":
                headline = f"{symbol} broke plan stop ${hi:,.2f}"
                display_headline = f"{symbol} 跌破計畫停損 ${hi:,.2f}"
            else:
                zone = f"${lo:,.2f}" if lo == hi else f"${lo:,.2f}–${hi:,.2f}"
                verb = {"in_zone": "entered", "below_zone": "below", "above_zone": "above"}[status]
                headline = f"{symbol} {verb} {label.lower()} {zone}"
                display_verb = {"in_zone": "進入", "below_zone": "跌破", "above_zone": "突破"}[status]
                display_headline = f"{symbol} {display_verb}{display_label} {zone}"
            triggers.append(
                {
                    "ticker": symbol,
                    "kind": kind,
                    "label": label,
                    "headline": headline,
                    "detail": f"Last ${last:,.2f}.",
                    "display_label": display_label,
                    "display_headline": display_headline,
                    "display_detail": f"現價 ${last:,.2f}。",
                    "anchor": anchor,
                    "tone": tone,
                    "status": status,
                    "low": lo,
                    "high": hi,
                    "last_close": last,
                }
            )
    return triggers


def _sparkline_svg(values: list[float | None], *, width: int = 64, height: int = 18) -> str:
    """Render a tiny inline SVG trend line from a numeric series (oldest→newest)."""
    points = [float(v) for v in values if isinstance(v, (int, float)) and v == v]
    if len(points) < 2:
        return ""
    lo, hi = min(points), max(points)
    span = (hi - lo) or 1.0
    count = len(points)
    coords = []
    for index, value in enumerate(points):
        x = index / (count - 1) * (width - 2) + 1
        y = (height - 1) - (value - lo) / span * (height - 2)
        coords.append(f"{x:.1f},{y:.1f}")
    color = "var(--good)" if points[-1] >= points[0] else "var(--danger)"
    return (
        f'<svg class="sparkline" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" preserveAspectRatio="none" aria-hidden="true">'
        f'<polyline points="{" ".join(coords)}" fill="none" stroke="{color}" '
        f'stroke-width="1.4" stroke-linejoin="round" stroke-linecap="round"/></svg>'
    )


def ticker_sparkline(report: DailyReport, symbol: str) -> str:
    """Attention-score trend sparkline for a ticker (stored history, oldest→newest)."""
    points = report.ticker_history.get(symbol, [])
    if len(points) < 2:
        return ""
    series = [point.attention_score for point in reversed(points)]
    return _sparkline_svg(series)


def morning_actions(report: DailyReport) -> list[dict[str, object]]:
    """Deduped, prioritized 'what must I decide today' list for the very top.

    Consolidates plan-zone triggers, stop-loss proximity, imminent earnings,
    thesis cracks, and large overnight gaps — only items that need a decision.
    """
    actions: list[dict[str, object]] = []
    seen: set[tuple[str, str]] = set()

    def add(
        symbol: str,
        label: str,
        headline: str,
        detail: str,
        anchor: str,
        tone: str,
        rank: int,
        *,
        display_label: str | None = None,
        display_headline: str | None = None,
        display_detail: str | None = None,
    ) -> None:
        key = (symbol, label)
        if key in seen:
            return
        seen.add(key)
        actions.append(
            {
                "ticker": symbol,
                "label": label,
                "headline": headline,
                "detail": detail,
                "display_label": display_label or zh_text(label),
                "display_headline": display_headline or zh_text(headline),
                "display_detail": display_detail or zh_text(detail),
                "anchor": anchor,
                "tone": tone,
                "rank": rank,
            }
        )

    for trigger in plan_triggers(report):
        kind = str(trigger["kind"])
        rank = 6 if kind == "stop" else (4 if kind == "reduce" else 3)
        add(
            str(trigger["ticker"]),
            str(trigger["label"]),
            str(trigger["headline"]),
            str(trigger["detail"]),
            str(trigger["anchor"]),
            str(trigger["tone"]),
            rank,
            display_label=str(trigger["display_label"]),
            display_headline=str(trigger["display_headline"]),
            display_detail=str(trigger["display_detail"]),
        )

    for tr in report.ticker_reports:
        symbol = tr.ticker.symbol
        anchor = f"#ticker-{symbol.lower()}"

        stop_alert = _stop_loss_alert(tr)
        if stop_alert is not None:
            detail, tone, _ = stop_alert
            add(
                symbol,
                "Stop nearby",
                f"{symbol} near stop-loss",
                detail,
                anchor,
                tone,
                5,
                display_label="停損提醒",
                display_headline=f"{symbol} 接近停損價",
                display_detail="現價已接近停損，先確認部位風險與執行方式。",
            )

        delta = earnings_delta(tr, report.report_date)
        if delta is not None and 0 <= delta <= 1:
            when = days_until(tr.earnings.earnings_date, report.report_date) if tr.earnings else "soon"
            tone = "danger" if delta == 0 else "warn"
            display_when = "今日" if delta == 0 else "明日"
            add(
                symbol,
                "Earnings",
                f"{symbol} reports {when}",
                "Finalize stance before the print.",
                anchor,
                tone,
                4,
                display_label="財報",
                display_headline=f"{symbol} {display_when}公布財報",
                display_detail="公布前先確認持有、加碼或減碼計畫。",
            )

        state = research_state_for(report, symbol)
        if state.thesis_state in {"weakening", "broken"}:
            state_label = "轉弱" if state.thesis_state == "weakening" else "失效"
            add(
                symbol,
                "Thesis",
                f"{symbol} thesis {state.thesis_state}",
                "Revisit the case before adding.",
                anchor,
                "danger",
                3,
                display_label="投資論點",
                display_headline=f"{symbol} 投資論點{state_label}",
                display_detail="加碼前先重新檢查原始假設與失效條件。",
            )

        gap = premarket_change_pct(report, symbol)
        if gap is not None and abs(gap) >= 3.0:
            tone = "warn" if gap < 0 else "good"
            add(
                symbol,
                "Gap",
                f"{symbol} gapped {format_pct(gap)} pre-market",
                "Check the overnight driver.",
                anchor,
                tone,
                2,
                display_label="盤前缺口",
                display_headline=f"{symbol} 盤前跳空 {format_pct(gap)}",
                display_detail="先確認隔夜催化或風險，再決定是否追價。",
            )

        framework = trading_framework_analysis(tr)
        if framework and int(framework["priority"]) >= 5:
            framework_tone = str(framework["tone"])
            wyckoff = framework["wyckoff"]
            vpa = framework["vpa"]
            operator = framework["operator"]
            is_risk = framework_tone == "down"
            add(
                symbol,
                "Structure risk" if is_risk else "Demand confirmed",
                f"{symbol} {wyckoff['event']} \u00b7 {vpa['event']}",
                str(operator["action"]),
                anchor,
                "danger" if is_risk else "good",
                5 if is_risk else 3,
                display_label="\u7d50\u69cb\u98a8\u96aa" if is_risk else "\u91cf\u50f9\u78ba\u8a8d",
                display_headline=f"{symbol} {wyckoff['event']} \u00b7 {vpa['event']}",
                display_detail=str(operator["action"]),
            )
    actions.sort(key=lambda item: item["rank"], reverse=True)
    return actions[:6]


def topic_tags(item: TickerReport) -> list[str]:
    """Map existing ticker terms/news titles into a few dashboard topics."""
    text = " ".join(
        [
            item.ticker.symbol,
            item.ticker.company_name,
            *item.ticker.aliases,
            *item.ticker.keywords,
            *(article.title for article in item.articles),
        ]
    ).lower()
    topic_terms = {
        "ai": (" ai", "artificial intelligence", "gpu", "copilot", "openai", "gemini", "aip", "custom silicon", "hbm"),
        "cloud": ("cloud", "azure", "aws", "google cloud", "data center"),
        "memory": ("memory", "dram", "nand", "hbm", "ssd", "flash storage"),
        "ev": (" ev", "electric vehicle", "tesla", "autonomous driving", "energy storage"),
    }
    return [topic for topic, terms in topic_terms.items() if any(term in f" {text}" for term in terms)]


def metric_raw(item: TickerReport, key: str) -> str:
    if not item.valuation:
        return ""
    value = item.valuation.metrics.get(key)
    if not isinstance(value, (int, float)) or not isfinite(float(value)):
        return ""
    return str(float(value))


def rsi_value(item: TickerReport) -> float | None:
    if not item.valuation:
        return None
    value = item.valuation.metrics.get("rsi_14")
    if not isinstance(value, (int, float)) or not isfinite(float(value)):
        return None
    return float(value)


def rsi_class(value: object) -> str:
    if not isinstance(value, (int, float)) or not isfinite(float(value)):
        return ""
    if value >= 80:
        return "extreme"
    if value >= 70:
        return "high"
    if value <= 20:
        return "extreme-low"
    if value <= 30:
        return "low"
    return "neutral"


def rsi_label(value: object) -> str:
    if not isinstance(value, (int, float)) or not isfinite(float(value)):
        return "N/A"
    if value >= 70:
        return "Overbought"
    if value <= 30:
        return "Oversold"
    return "Neutral"


def valuation_risk_label(item: TickerReport) -> str:
    high_pe = _highest_pe(item)
    if high_pe is None:
        return "None"
    _key, value = high_pe
    if value >= 200:
        return "Extreme"
    if value >= 100:
        return "High"
    if value >= 50:
        return "Elevated"
    return "None"


def top_news_count(item: TickerReport) -> int:
    return sum(1 for article in item.articles if article.importance_score >= 1.0)


def top_news_signatures(item: TickerReport) -> str:
    signatures = [
        normalize_title(article.title)
        for article in item.articles
        if article.importance_score >= 1.0
    ]
    return "|".join(signatures)


def has_risk_signal(item: TickerReport, anchor: date) -> bool:
    insights = ticker_insights(item, anchor)
    return bool(insights["risk"])


def _highest_pe(item: TickerReport) -> tuple[str, float] | None:
    if not item.valuation:
        return None
    values: list[tuple[str, float]] = []
    for key in ("trailing_pe", "forward_pe"):
        value = item.valuation.metrics.get(key)
        if isinstance(value, (int, float)) and isfinite(float(value)):
            values.append((key, float(value)))
    if not values:
        return None
    return max(values, key=lambda pair: pair[1])


def _stretched_valuation_tickers(report: DailyReport) -> list[TickerReport]:
    """Tickers with trailing or forward P/E >=100, ordered by the higher of the two."""
    stretched: list[tuple[float, TickerReport]] = []
    for tr in report.ticker_reports:
        if not tr.valuation:
            continue
        pe_values: list[float] = []
        for key in ("trailing_pe", "forward_pe"):
            value = tr.valuation.metrics.get(key)
            if isinstance(value, (int, float)) and value == value and value >= 100:
                pe_values.append(float(value))
        if pe_values:
            stretched.append((max(pe_values), tr))
    stretched.sort(key=lambda pair: pair[0], reverse=True)
    return [tr for _, tr in stretched]


def ticker_insights(item: TickerReport, anchor: date, *, benchmarks: dict[str, float] | None = None, portfolio: PortfolioSettings | None = None) -> dict[str, object]:
    """Auto-derived signals for a ticker card. Pure data summarization, no sentiment."""
    setup: list[str] = []
    risk: list[str] = []
    quality: list[str] = []

    if item.earnings and item.earnings.earnings_date:
        delta = (item.earnings.earnings_date - anchor).days
        if 0 <= delta <= 7:
            when = "today" if delta == 0 else "tomorrow" if delta == 1 else f"in {delta}d"
            setup.append(f"Earnings {when}")

    if item.articles:
        n = len(item.articles)
        top_count = sum(1 for a in item.articles if a.importance_score >= 1.0)
        if top_count >= 1:
            setup.append(f"{n} headlines | {top_count} top stor{'y' if top_count == 1 else 'ies'}")
        else:
            setup.append(f"{n} headlines")

    if item.x_signals:
        count = len(item.x_signals)
        setup.append(f"{count} X signal{'s' if count != 1 else ''}")

    if item.valuation:
        quality = quality_of_move(item)
        eps_power = eps_power_summary(item)
        if eps_power:
            setup.append(eps_power)
        rsi = rsi_value(item)
        if rsi is not None:
            if rsi >= 70:
                risk.append(f"RSI {rsi:.0f} overbought")
            elif rsi <= 30:
                setup.append(f"RSI {rsi:.0f} oversold")

        change = daily_change_pct(item)
        if isinstance(change, (int, float)):
            if abs(change) >= 5.0:
                # Big single-day move - surface as risk for awareness
                risk.append(f"{format_pct(change)} today")
            elif abs(change) >= 0.1:
                setup.append(f"{format_pct(change)} today")

        from_high = from_52w_high_pct(item)
        if isinstance(from_high, (int, float)):
            if from_high >= -5.0:
                setup.append("near 52w high")
            elif from_high <= -25.0:
                risk.append(f"{format_pct(from_high, sign=False).lstrip('-')} below 52w high")

        for key in ("trailing_pe", "forward_pe"):
            value = item.valuation.metrics.get(key)
            if isinstance(value, (int, float)) and value == value and value >= 100:
                risk.append(f"{METRIC_LABELS[key]} {value:.0f}")
                break
        revision = _as_float(item.valuation.metrics.get("fy1_eps_revision_30d"))
        if revision is not None and revision < -0.5:
            risk.append(f"FY1 EPS revisions {revision:.1f}% 30D")
        ev_ebitda = item.valuation.metrics.get("ev_to_ebitda")
        if isinstance(ev_ebitda, (int, float)) and ev_ebitda == ev_ebitda and ev_ebitda < 0:
            risk.append("Negative EV/EBITDA")

    if item.warnings:
        count = len(item.warnings)
        risk.append(f"{count} data warning{'s' if count != 1 else ''}")

    trend = ma_signals(item) if item.valuation else []
    watch = list(item.ticker.keywords[:3]) if item.ticker.keywords else []
    action = earnings_action(item, anchor)

    rs_phrases: list[str] = []
    rs_tone = ""
    if benchmarks:
        rs = relative_strength(item, benchmarks)
        rs_phrases = format_relative_strength(rs)
        if rs:
            both_pos = all(v >= 0 for v in rs.values())
            both_neg = all(v <= 0 for v in rs.values())
            if both_pos:
                rs_tone = "up"
            elif both_neg:
                rs_tone = "down"
            else:
                rs_tone = "mixed"

    score_info = right_side_score(item, benchmarks)
    technical = technical_playbook(item)
    right_side = right_side_check(item, benchmarks=benchmarks, portfolio=portfolio)
    framework = trading_framework_analysis(item)
    price_regime = price_regime_status(item)

    return {
        "setup": setup,
        "quality": quality,
        "trend": trend,
        "trend_tone": trend_tone(trend),
        "trend_title": format_ma_distances(item) if trend else "",
        "rs": rs_phrases,
        "rs_tone": rs_tone,
        "risk": risk,
        "watch": watch,
        "action": action,
        "score": score_info,
        "technical": technical,
        "right_side": right_side,
        "framework": framework,
        "price_regime": price_regime,
    }


def card_state(item: TickerReport, anchor: date) -> str:
    """Visual weight class for a ticker card: hot / warm / warn / quiet.

    Hot is reserved for the strongest catalysts so the red signal stays
    meaningful: earnings TODAY only, or 2+ top-tier articles. Earnings
    tomorrow / within-7-days drops to warm, where the warmer color band
    can stand on its own without diluting hot.
    """
    if item.earnings and item.earnings.earnings_date:
        delta = (item.earnings.earnings_date - anchor).days
        if delta == 0:
            return "hot"
    top_news_count = sum(1 for a in item.articles if a.importance_score >= 1.0)
    if top_news_count >= 2:
        return "hot"
    if item.warnings:
        return "warn"
    if item.articles or (
        item.earnings
        and item.earnings.earnings_date
        and 0 <= (item.earnings.earnings_date - anchor).days <= 7
    ):
        return "warm"
    return "quiet"


def pe_class(value: object) -> str:
    if value is None:
        return ""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return ""
    if number != number:  # NaN
        return ""
    if number < 0:
        return "neg"
    if number >= 200:
        return "extreme"
    if number >= 100:
        return "high"
    if number >= 50:
        return "elevated"
    return ""
