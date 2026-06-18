from __future__ import annotations

import re
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from math import isfinite
from pathlib import Path
from zoneinfo import ZoneInfo

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .data_quality import confidence as data_quality_confidence
from .models import DailyReport, MarketContext, NewsArticle, PositionConfig, PostEarningsReview, TickerHistoryPoint, TickerReport, TickerResearchState
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


@dataclass(frozen=True)
class ReportPaths:
    markdown: Path
    html: Path
    brief: Path


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
    env.filters["news_rationale"] = news_rationale
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
    env.filters["ticker_insights"] = lambda item: ticker_insights(item, report.report_date, benchmarks=benchmarks)
    env.filters["right_side_score"] = lambda item: right_side_score(item, benchmarks)
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
        morning_actions=morning_actions(report),
        todays_catalysts=todays_catalysts(report),
        post_earnings_items=post_earnings_items(report),
        macro_risk=macro_risk_meter(report.market_context),
        todays_focus=todays_focus(report),
        capital_allocation=capital_allocation_queue(report),
        book_today=book_today_summary(report),
        book_impact=book_impact_ranking(report),
        sector_leadership=sector_leadership(report),
        premarket_triage=premarket_triage(report),
        priority_items=priority_items(report),
        rule_alerts=rule_alerts(report),
        valuation_rows=sorted(report.ticker_reports, key=lambda item: item.ticker.symbol),
        ticker_cards=sort_by_market_cap(report.ticker_reports),
        sectors=sectors_in_use(report),
        overextended=overextended_tickers(report),
        data_quality=data_quality_overview(report),
        portfolio=portfolio_impact_summary(report),
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
    output_path = Path(output_dir)
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
    }


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
    return {
        "tickers": states,
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


def zh_text(value: object) -> str:
    """Display-only Traditional Chinese wording for common dashboard phrases."""
    text = str(value or "")
    replacements = {
        "Breakout confirmed": "突破確認",
        "Pullback buy zone": "回檔買點區",
        "Extended, do not chase": "已延伸，避免追高",
        "Mixed / neutral": "中性",
        "Thesis weakening": "投資論點轉弱",
        "Avoid": "暫避",
        "Reviewed": "已檢視",
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
        "top stories": "重點新聞",
        "top story": "重點新聞",
        "headlines": "則新聞",
        "headline": "則新聞",
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
        "volume": "成交量",
        "today": "今日",
    }
    for src, dest in replacements.items():
        text = text.replace(src, dest)
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


def relative_strength(item: TickerReport, benchmarks: dict[str, float]) -> dict[str, float]:
    """Return ticker's 20D return spread vs SPY and QQQ.

    benchmarks maps "spy_20d" / "qqq_20d" → return %. Returns
    {"vs_spy": spread, "vs_qqq": spread} for whichever is available.
    """
    if not item.valuation:
        return {}
    ticker_return = _as_float(item.valuation.metrics.get("return_20d"))
    if ticker_return is None:
        return {}
    out: dict[str, float] = {}
    for bench_label, bench_key in (("vs_spy", "spy_20d"), ("vs_qqq", "qqq_20d")):
        bench_return = benchmarks.get(bench_key)
        if isinstance(bench_return, (int, float)):
            out[bench_label] = round(ticker_return - bench_return, 2)
    return out


def format_relative_strength(rs: dict[str, float]) -> list[str]:
    """Compact phrases like '+2.3% vs SPY 20D'."""
    parts: list[str] = []
    for key, label in (("vs_spy", "vs SPY 20D"), ("vs_qqq", "vs QQQ 20D")):
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

    # RSI cool-down penalty
    rsi = _as_float(metrics.get("rsi_14"))
    if rsi is not None:
        if rsi >= 75:
            score -= 10
            reasons.append((-10, f"RSI {rsi:.0f}"))
        elif rsi >= 70:
            score -= 5
            reasons.append((-5, f"RSI {rsi:.0f}"))

    # Valuation overhang
    risk_tier = valuation_risk_label(item)
    if risk_tier == "Extreme":
        score -= 10
        reasons.append((-10, "Extreme P/E"))
    elif risk_tier == "High":
        score -= 5
        reasons.append((-5, "High P/E"))

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
    symbol = item.ticker.symbol.lower()
    keywords_text = " ".join([
        item.ticker.symbol.lower(),
        item.ticker.company_name.lower(),
        " ".join(item.ticker.keywords).lower(),
    ])
    for label, terms in SECTOR_GROUPS:
        for term in terms:
            if term.lower() in keywords_text or term.lower() in symbol:
                return label.lower()
    return None


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

    total_cost = sum(r["cost_basis"] for r in rows if isinstance(r["cost_basis"], (int, float)))
    total_mv = sum(r["market_value"] for r in rows if isinstance(r["market_value"], (int, float)))
    total_pl_dollar = round(total_mv - total_cost, 2) if total_cost > 0 else None
    total_pl_pct = round((total_mv - total_cost) / total_cost * 100.0, 2) if total_cost > 0 else None

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


SECTOR_GROUPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Semis", ("semiconductor", "semi", "chip", "gpu", "soxx", "nvda", "amd", "avgo", "tsm", "asml", "arm")),
    ("Mega-cap software", ("software", "cloud", "azure", "copilot", "msft", "crm", "adbe", "orcl")),
    ("Memory", ("memory", "dram", "nand", "hbm", "ssd", "mu", "wdc", "stx")),
    ("EV", ("ev", "electric vehicle", "autonomous", "tesla", "tsla", "rivn", "nio")),
    ("Internet / ads", ("advertising", "ads", "search", "social", "internet", "googl", "meta", "amzn")),
    ("AI infra", ("ai", "data center", "server", "networking", "accelerator", "gpu")),
)


def sector_leadership(report: DailyReport) -> list[dict[str, object]]:
    spy_20d = None
    if report.market_context and report.market_context.benchmark_returns:
        spy_20d = report.market_context.benchmark_returns.get("spy_20d")
    rows: list[dict[str, object]] = []
    assigned: set[str] = set()
    for label, terms in SECTOR_GROUPS:
        members = [
            item for item in report.ticker_reports
            if _matches_sector_group(item, terms)
        ]
        if not members:
            continue
        assigned.update(item.ticker.symbol for item in members)
        one_day = _avg_metric(members, daily_change_pct)
        ret_5d = _avg_metric(members, lambda item: _metric_float(item, "return_5d"))
        ret_20d = _avg_metric(members, lambda item: _metric_float(item, "return_20d"))
        rel_spy = ret_20d - spy_20d if ret_20d is not None and isinstance(spy_20d, (int, float)) else None
        rows.append({
            "label": label,
            "members": members,
            "symbols": ", ".join(item.ticker.symbol for item in members[:6]),
            "one_day": one_day,
            "ret_5d": ret_5d,
            "ret_20d": ret_20d,
            "rel_spy": rel_spy,
        })

    other = [item for item in report.ticker_reports if item.ticker.symbol not in assigned]
    if other:
        ret_20d = _avg_metric(other, lambda item: _metric_float(item, "return_20d"))
        rel_spy = ret_20d - spy_20d if ret_20d is not None and isinstance(spy_20d, (int, float)) else None
        rows.append({
            "label": "Other watchlist",
            "members": other,
            "symbols": ", ".join(item.ticker.symbol for item in other[:6]),
            "one_day": _avg_metric(other, daily_change_pct),
            "ret_5d": _avg_metric(other, lambda item: _metric_float(item, "return_5d")),
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
    return any(term in text for term in terms)


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


def sort_by_market_cap(items: list[TickerReport]) -> list[TickerReport]:
    """Sort tickers by market cap descending. Tickers with missing/NaN market cap go last."""
    def key(item: TickerReport) -> tuple[int, float, str]:
        if item.valuation:
            mc = item.valuation.metrics.get("market_cap")
            if isinstance(mc, (int, float)) and mc == mc:
                return (0, -float(mc), item.ticker.symbol)
        return (1, 0.0, item.ticker.symbol)
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

    regime_headline = "Regime check"
    regime_subtitle = "No market context available."
    regime_tone = "info"
    risks = macro_risk_meter(report.market_context)
    high_risks = [risk for risk in risks if risk["level"] == "high"]
    medium_risks = [risk for risk in risks if risk["level"] == "medium"]
    if high_risks:
        lead = high_risks[0]
        regime_headline = f"{lead['name'].replace(' pressure', '')}-led pressure"
        regime_subtitle = lead["detail"]
        regime_tone = "soon"
    elif medium_risks:
        lead = medium_risks[0]
        regime_headline = f"{lead['name'].replace(' pressure', '')} pressure building"
        regime_subtitle = lead["detail"]
        regime_tone = "info"
    elif report.market_sentiment:
        regime_headline = f"{report.market_sentiment.label} tape"
        regime_subtitle = f"Sentiment {report.market_sentiment.score} / 100"
        regime_tone = "imminent" if report.market_sentiment.score <= 24 or report.market_sentiment.score >= 76 else "info"
    cards.append({
        "kind": "regime",
        "label": "Regime",
        "headline": regime_headline,
        "subtitle": regime_subtitle,
        "tone": regime_tone,
        "anchor": "#rates" if report.market_context and report.market_context.rates else "#market-sentiment",
    })

    pm_headline = "No premarket snapshot"
    pm_subtitle = "Run with valuation fetching enabled for ES/NQ/SPY/QQQ tone."
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
            pm_subtitle = "Risk-on premarket tone" if avg > 0.15 else "Risk-off premarket tone" if avg < -0.15 else "Mixed premarket tone"
            pm_tone = "info" if avg >= 0 else "soon"
    cards.append({
        "kind": "premarket",
        "label": "Premarket tone",
        "headline": pm_headline,
        "subtitle": pm_subtitle,
        "tone": pm_tone,
        "anchor": "#premarket",
    })

    stretched = overextended_tickers(report)
    macro_warning_count = sum(1 for warning in report.warnings if "macro" in warning.lower())
    risk_bits: list[str] = []
    if stretched:
        risk_bits.append(f"{len(stretched)} stretched")
    if macro_warning_count:
        risk_bits.append(f"{macro_warning_count} macro warning{'s' if macro_warning_count != 1 else ''}")
    if not risk_bits and rule_alerts(report):
        risk_bits.append(f"{len(rule_alerts(report))} rule alert{'s' if len(rule_alerts(report)) != 1 else ''}")
    cards.append({
        "kind": "risk",
        "label": "Top risk",
        "headline": ", ".join(risk_bits) if risk_bits else "No major tape risk",
        "subtitle": "Check valuation and feed quality before chasing." if risk_bits else "No stretched or feed-risk cluster flagged.",
        "tone": "imminent" if macro_warning_count or len(stretched) >= 5 else "soon" if stretched else "info",
        "anchor": "#overextended" if stretched else "#global-warnings" if macro_warning_count else "#rule-alerts",
    })

    focus = todays_focus(report)
    focus_symbols = [str(row["item"].ticker.symbol) for row in focus["review_first"][:3]]
    cards.append({
        "kind": "focus",
        "label": "Focus",
        "headline": " / ".join(focus_symbols) if focus_symbols else "No urgent review queue",
        "subtitle": "Review first from holdings, catalysts, gaps, revisions, and alerts." if focus_symbols else "Dashboard is quiet after current rules.",
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

    for action in actions[:3]:
        label, headline, detail = _daily_summary_action_text(action)
        add(
            label,
            headline,
            detail,
            str(action.get("anchor") or "#morning-actions"),
            str(action.get("tone") or "warn"),
            key=str(action.get("ticker") or action.get("anchor") or headline),
        )

    for row in focus.get("review_first", [])[:3]:
        item = row["item"]
        symbol = item.ticker.symbol
        reasons = row.get("reasons", [])
        detail = _daily_summary_reasons(reasons)
        add(
            "優先檢視",
            f"{symbol} 需要先看",
            detail or "同時有持股、催化、缺口或研究狀態訊號。",
            f"#ticker-{symbol.lower()}",
            "warn" if has_risk_signal(item, report.report_date) else "info",
            key=symbol,
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
        detail_parts.append(f"{len(actions)} 個待決策訊號")
    if focus.get("review_first"):
        detail_parts.append(f"{len(focus['review_first'])} 檔優先檢視")
    if news:
        detail_parts.append(f"{len(news)} 則重點新聞")
    if earnings:
        detail_parts.append(f"{len(earnings)} 檔 7 天內財報")
    if macro_near:
        detail_parts.append(f"{len(macro_near)} 個近端總經事件")
    if not detail_parts:
        detail_parts.append("目前沒有高優先級訊號")

    tone = "danger" if actions else "warn" if earnings or macro_near else "info"
    headline = f"今天先看 {len(items)} 件事" if items and items[0]["headline"] != "沒有明顯急件" else "今天偏平穩"
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
            if kind == "stop":
                headline = f"{symbol} broke plan stop ${hi:,.2f}"
            else:
                zone = f"${lo:,.2f}" if lo == hi else f"${lo:,.2f}–${hi:,.2f}"
                verb = {"in_zone": "entered", "below_zone": "below", "above_zone": "above"}[status]
                headline = f"{symbol} {verb} {label.lower()} {zone}"
            triggers.append(
                {
                    "ticker": symbol,
                    "kind": kind,
                    "label": label,
                    "headline": headline,
                    "detail": f"Last ${last:,.2f}.",
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

    def add(symbol: str, label: str, headline: str, detail: str, anchor: str, tone: str, rank: int) -> None:
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
        )

    for tr in report.ticker_reports:
        symbol = tr.ticker.symbol
        anchor = f"#ticker-{symbol.lower()}"

        stop_alert = _stop_loss_alert(tr)
        if stop_alert is not None:
            detail, tone, _ = stop_alert
            add(symbol, "Stop nearby", f"{symbol} near stop-loss", detail, anchor, tone, 5)

        delta = earnings_delta(tr, report.report_date)
        if delta is not None and 0 <= delta <= 1:
            when = days_until(tr.earnings.earnings_date, report.report_date) if tr.earnings else "soon"
            tone = "danger" if delta == 0 else "warn"
            add(symbol, "Earnings", f"{symbol} reports {when}", "Finalize stance before the print.", anchor, tone, 4)

        state = research_state_for(report, symbol)
        if state.thesis_state in {"weakening", "broken"}:
            add(symbol, "Thesis", f"{symbol} thesis {state.thesis_state}", "Revisit the case before adding.", anchor, "danger", 3)

        gap = premarket_change_pct(report, symbol)
        if gap is not None and abs(gap) >= 3.0:
            tone = "warn" if gap < 0 else "good"
            add(symbol, "Gap", f"{symbol} gapped {format_pct(gap)} pre-market", "Check the overnight driver.", anchor, tone, 2)

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


def ticker_insights(item: TickerReport, anchor: date, *, benchmarks: dict[str, float] | None = None) -> dict[str, list[str]]:
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
