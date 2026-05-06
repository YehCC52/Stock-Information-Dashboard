from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from math import isfinite
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .models import DailyReport, TickerReport
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
    "market_cap": "Market Cap",
    "enterprise_value": "Enterprise Value",
    "trailing_pe": "Trailing P/E",
    "forward_pe": "Forward P/E",
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
    env.filters["post_earnings"] = lambda item: post_earnings_status(item, report.report_date)
    env.filters["ticker_insights"] = lambda item: ticker_insights(item, report.report_date)
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
    env.filters["format_pct"] = format_pct
    env.filters["change_class"] = change_class
    env.filters["rsi_class"] = rsi_class
    env.filters["rsi_label"] = rsi_label
    template = env.get_template("daily_report.html.j2")
    return template.render(
        report=report,
        metric_labels=METRIC_LABELS,
        summary=build_summary(report),
        earnings_soon=earnings_soon(report),
        important_news=important_news(report),
        hero=hero_items(report),
        priority_items=priority_items(report),
        rule_alerts=rule_alerts(report),
        valuation_rows=sorted(report.ticker_reports, key=lambda item: item.ticker.symbol),
        ticker_cards=sort_by_market_cap(report.ticker_reports),
        sectors=sectors_in_use(report),
        overextended=overextended_tickers(report),
        valuation_keys=[
            "last_close",
            "rsi_14",
            "market_cap",
            "trailing_pe",
            "forward_pe",
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
    return {
        "ticker_count": ticker_count,
        "tickers_with_news": tickers_with_news,
        "tickers_with_warnings": tickers_with_warnings,
        "earnings_soon_count": earnings_soon_count,
        "hot_count": hot_count,
        "global_warning_count": len(report.warnings),
        "economic_event_count": len(report.economic_events),
        "rsi_overbought_count": rsi_overbought_count,
        "rsi_oversold_count": rsi_oversold_count,
    }


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
        if 0 <= delta <= 1:
            score += 14
        elif 0 <= delta <= 7:
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


def sectors_in_use(report: DailyReport) -> list[str]:
    """Distinct sectors present in the watchlist, sorted alphabetically."""
    seen: set[str] = set()
    for tr in report.ticker_reports:
        if tr.valuation:
            sector = tr.valuation.metrics.get("sector")
            if isinstance(sector, str) and sector.strip():
                seen.add(sector.strip())
    return sorted(seen)


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

    if sma20 is not None and last >= sma20 and (last - sma20) / sma20 * 100 <= NEAR_SUPPORT_PCT:
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


def ticker_insights(item: TickerReport, anchor: date) -> dict[str, list[str]]:
    """Auto-derived signals for a ticker card. Pure data summarization, no sentiment."""
    setup: list[str] = []
    risk: list[str] = []

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
        ev_ebitda = item.valuation.metrics.get("ev_to_ebitda")
        if isinstance(ev_ebitda, (int, float)) and ev_ebitda == ev_ebitda and ev_ebitda < 0:
            risk.append("Negative EV/EBITDA")

    if item.warnings:
        count = len(item.warnings)
        risk.append(f"{count} data warning{'s' if count != 1 else ''}")

    trend = ma_signals(item) if item.valuation else []
    watch = list(item.ticker.keywords[:3]) if item.ticker.keywords else []
    action = earnings_action(item, anchor)

    return {
        "setup": setup,
        "trend": trend,
        "trend_tone": trend_tone(trend),
        "trend_title": format_ma_distances(item) if trend else "",
        "risk": risk,
        "watch": watch,
        "action": action,
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
