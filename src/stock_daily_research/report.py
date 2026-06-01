from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from math import isfinite
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .models import DailyReport, MarketContext, NewsArticle, PostEarningsReview, TickerHistoryPoint, TickerReport, TickerResearchState
from .news import EVENT_LABELS, normalize_title
from .valuation import format_metric_value


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
    return env


def render_markdown_report(report: DailyReport, template_dir: str | Path | None = None) -> str:
    env = _build_environment(template_dir)
    template = env.get_template("daily_report.md.j2")
    return template.render(report=report, metric_labels=METRIC_LABELS)


def render_html_report(report: DailyReport, template_dir: str | Path | None = None) -> str:
    env = _build_environment(template_dir, autoescape_html=True)
    env.filters["pe_class"] = pe_class
    env.filters["earnings_urgency"] = lambda value: earnings_urgency(value, report.report_date)
    env.filters["days_until"] = lambda value: days_until(value, report.report_date)
    env.filters["earnings_delta"] = lambda item: earnings_delta(item, report.report_date)
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
    env.filters["premarket_change"] = lambda item: premarket_change_pct(report, item.ticker.symbol)
    env.filters["position_view"] = position_view
    env.filters["eps_revision_class"] = eps_revision_class
    env.filters["source_reliability"] = source_reliability
    env.filters["post_earnings_defaults"] = lambda item: post_earnings_defaults(report, item)
    env.filters["format_pct"] = format_pct
    env.filters["change_class"] = change_class
    env.filters["format_ratio"] = format_ratio
    env.filters["rsi_class"] = rsi_class
    env.filters["rsi_label"] = rsi_label
    env.filters["research_state"] = lambda item: research_state_for(report, item.ticker.symbol)
    env.filters["history_points"] = lambda item: report.ticker_history.get(item.ticker.symbol, [])
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
        todays_catalysts=todays_catalysts(report),
        post_earnings_items=post_earnings_items(report),
        macro_risk=macro_risk_meter(report.market_context),
        todays_focus=todays_focus(report),
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
        portfolio=portfolio_impact_summary(report),
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
    markdown_path.write_text(_strip_bom(render_markdown_report(report)), encoding="utf-8")
    html_path.write_text(_strip_bom(render_html_report(report)), encoding="utf-8")
    return ReportPaths(markdown=markdown_path, html=html_path)


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
            },
        }
    return {
        "tickers": states,
        "history_days": int(report.history_overview.get("history_days", 30)) if report.history_overview else 30,
        "archive_dates": list(report.history_overview.get("archive_dates", [])) if report.history_overview else [],
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
        return f"{-delta}d ago"
    if delta == 0:
        return "today"
    if delta == 1:
        return "tomorrow"
    return f"in {delta}d"


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


def event_label(event_type: object) -> str:
    return EVENT_LABELS.get(str(event_type), str(event_type).replace("_", " ").title())


# One-line interpretation for top news, by event_type.
# Goal: turn "headline" into "judgment" — what should the reader take from it.
NEWS_RATIONALE: dict[str, str] = {
    "earnings": "Earnings read-through",
    "guidance": "Forward-look impact",
    "ai": "AI / capex implication",
    "deal": "Strategic positioning",
    "regulation": "Regulatory overhang",
    "lawsuit": "Litigation risk",
    "antitrust": "Antitrust overhang",
    "supply": "Supply-chain signal",
    "product": "Product cycle signal",
    "analyst": "Sell-side view shift",
    "analyst_call": "Sell-side view shift",
    "management": "Leadership transition",
    "macro": "Macro tape risk",
    "market": "Macro tape risk",
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
            return "Wait reaction (overextended)"
        if rsi is not None and rsi <= 30:
            return "Watch capitulation"
        return "Watch reaction"
    if delta == 1:
        return "Prepare plan"
    if 2 <= delta <= 7:
        return "Build thesis"
    if -7 <= delta <= -1:
        return "Review outcome"
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
    """Condense the morning dashboard into direct action buckets."""
    review_candidates: list[tuple[float, TickerReport, list[str]]] = []
    do_not_chase: list[tuple[float, TickerReport, list[str]]] = []
    pullback: list[tuple[float, TickerReport, list[str]]] = []

    alert_ranks = {str(alert["symbol"]): float(alert.get("rank", 0)) for alert in rule_alerts(report)}
    gaps = {m.symbol: abs(m.change_pct or 0.0) for m in report.premarket.gap_movers} if report.premarket else {}

    for item in report.ticker_reports:
        symbol = item.ticker.symbol
        state = research_state_for(report, symbol)
        current_point = _current_history_point(report, symbol)
        reasons: list[str] = []
        score = alert_ranks.get(symbol, 0.0)

        delta = earnings_delta(item, report.report_date)
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
                do_not_chase.append((len(chase_reasons) + abs(pmove or 0), item, chase_reasons))

        from_high = from_52w_high_pct(item)
        if from_high is not None and -12.0 <= from_high <= -3.0:
            pb_reasons = [f"{abs(from_high):.1f}% below 52w high"]
            if item.articles:
                pb_reasons.append(f"{len(item.articles)} headline{'s' if len(item.articles) != 1 else ''}")
            if valuation_risk_label(item) in ("None", "Elevated"):
                pb_reasons.append("less stretched")
            pullback.append((100 + from_high + len(item.articles), item, pb_reasons))
        elif symbol in gaps and (pmove := premarket_change_pct(report, symbol)) is not None and pmove < -2.0:
            pullback.append((abs(pmove), item, [f"premarket pullback {format_pct(pmove)}"]))

    def pack(rows: list[tuple[float, TickerReport, list[str]]]) -> list[dict[str, object]]:
        return [
            {"item": item, "score": score, "reasons": reasons[:6]}
            for score, item, reasons in sorted(rows, key=lambda row: (-row[0], row[1].ticker.symbol))[:3]
        ]

    return {
        "review_first": pack(review_candidates),
        "do_not_chase": pack(do_not_chase),
        "watch_pullback": pack(pullback),
    }


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

        rows.append({
            "symbol": tr.ticker.symbol,
            "company": tr.ticker.company_name,
            "weight": round(float(weight), 2),
            "change_pct": change_pct,
            "book_impact": book_impact,
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

    event_soon = [r for r in rows if r["event_soon"]]
    thesis_risk = [r for r in rows if r["thesis_risk"]]

    total_impact = round(sum(r["book_impact"] or 0 for r in rows), 3)
    total_weight = round(sum(float(r["weight"]) for r in rows), 2)

    sectors = sector_concentration(report)
    stop_warnings = stop_distance_warnings(report)

    settings = getattr(report, "settings", None)
    portfolio_settings = getattr(settings, "portfolio", None) if settings else None
    addable_cash = getattr(portfolio_settings, "addable_cash", None) if portfolio_settings else None
    total_value = getattr(portfolio_settings, "total_value", None) if portfolio_settings else None
    max_single_weight = getattr(portfolio_settings, "max_single_weight", None) if portfolio_settings else None

    over_concentrated: list[dict[str, object]] = []
    if max_single_weight is not None:
        over_concentrated = [
            r for r in rows if isinstance(r["weight"], (int, float)) and r["weight"] > max_single_weight
        ]

    return {
        "holdings": rows,
        "winners": winners,
        "losers": losers,
        "event_soon": event_soon,
        "thesis_risk": thesis_risk,
        "total_impact_pct": total_impact,
        "total_weight_pct": total_weight,
        "sectors": sectors,
        "stop_warnings": stop_warnings,
        "addable_cash": addable_cash,
        "total_value": total_value,
        "over_concentrated": over_concentrated,
        "max_single_weight": max_single_weight,
    }


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

    Priorities by tone (loudest first): imminent earnings cluster, imminent
    macro event, valuation-watch list (tickers with stretched P/E), top news
    fallback. Returns at most 3 cards.
    """
    anchor = report.report_date
    items: list[dict[str, object]] = []

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
                "subtitle": ev.event_datetime.strftime("%H:%M %Z"),
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
                add("overbought technicals", f"RSI 14 {rsi:.0f} with stretched valuation.", signal_rank=3)
            elif tr.articles and card_state(tr, report.report_date) == "hot":
                add("hot but overbought", f"RSI 14 {rsi:.0f}; avoid chasing without a fresh catalyst.", signal_rank=2)

        if rsi is not None and rsi <= 30 and earnings_soon_flag:
            add("oversold into earnings", f"RSI 14 {rsi:.0f}; review whether weakness is technical or thesis-related.", signal_rank=2)

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
