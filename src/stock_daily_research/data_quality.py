"""Per-ticker data-quality checks: anomaly flags + a 0-100 confidence score.

These guard against silently trusting bad inputs (stale snapshots, garbage
P/E from a thin data feed, a 30% one-day move that's really a split artefact).
Each detector returns a short human-readable flag string or None. The
confidence score aggregates them into a single high/medium/low tag surfaced
on the card and in a roll-up section.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

from .models import PremarketMove, TickerReport, ValuationSnapshot

PRICE_ANOMALY_PCT = 20.0
MARKET_CAP_DRIFT_PCT = 10.0
MARKET_CAP_PRICE_SYNC_PCT = 2.0
PE_CEILING = 1000.0
STALE_HOURS = 36
NEWS_OVERFLOW_COUNT = 12


def _as_float(value: Any) -> float | None:
    if not isinstance(value, (int, float)):
        return None
    if value != value:  # NaN
        return None
    return float(value)


def detect_price_anomaly(item: TickerReport) -> str | None:
    """Flag a daily move whose magnitude exceeds PRICE_ANOMALY_PCT."""
    if not item.valuation:
        return None
    last = _as_float(item.valuation.metrics.get("last_close"))
    prev = _as_float(item.valuation.metrics.get("previous_close"))
    if last is None or prev is None or prev == 0:
        return None
    change = (last - prev) / prev * 100.0
    if abs(change) > PRICE_ANOMALY_PCT:
        return f"Daily move {change:+.0f}% exceeds {PRICE_ANOMALY_PCT:.0f}% — verify split/feed"
    return None


def detect_price_regime_change(item: TickerReport) -> str | None:
    """Flag technical history that was reset after a large price discontinuity."""
    if not item.valuation:
        return None
    metrics = item.valuation.metrics
    change_date = metrics.get("price_regime_change_date")
    if not change_date:
        return None
    sessions = int(_as_float(metrics.get("price_history_sessions")) or 0)
    change_pct = _as_float(metrics.get("price_regime_change_pct"))
    change_text = f"{change_pct:+.1f}%" if change_pct is not None else "N/A"
    return (
        f"\u50f9\u683c\u57fa\u6e96\u65bc {change_date} \u767c\u751f {change_text} \u8df3\u8b8a\uff0c"
        f"\u50c5\u4fdd\u7559 {sessions} \u500b\u6709\u6548\u4ea4\u6613\u65e5\uff0c\u6280\u8853\u6307\u6a19\u91cd\u5efa\u4e2d"
    )

def detect_market_cap_drift(
    today_metrics: dict[str, Any], prior_metrics: dict[str, Any]
) -> str | None:
    """Flag a market-cap jump > MARKET_CAP_DRIFT_PCT vs the prior snapshot."""
    today = _as_float(today_metrics.get("market_cap"))
    prior = _as_float(prior_metrics.get("market_cap"))
    if today is None or prior is None or prior == 0:
        return None
    drift = abs(today - prior) / prior * 100.0
    if drift > MARKET_CAP_DRIFT_PCT:
        return f"Market cap shifted {drift:.0f}% day-over-day — verify share count"
    return None


def detect_market_cap_price_mismatch(
    today_metrics: dict[str, Any], prior_metrics: dict[str, Any] | None = None
) -> str | None:
    """Flag a market-cap jump that is not confirmed by price movement."""
    prior_metrics = prior_metrics or {}
    today_mc = _as_float(today_metrics.get("market_cap"))
    prior_mc = _as_float(
        prior_metrics.get("market_cap")
        or today_metrics.get("previous_market_cap")
        or today_metrics.get("market_cap_previous")
    )
    if today_mc is None or prior_mc is None or prior_mc == 0:
        return None
    mc_drift = abs(today_mc - prior_mc) / prior_mc * 100.0
    if mc_drift <= MARKET_CAP_DRIFT_PCT:
        return None

    last = _as_float(today_metrics.get("last_close"))
    prior_price = _as_float(
        prior_metrics.get("last_close")
        or today_metrics.get("previous_close")
        or today_metrics.get("previous_last_close")
    )
    if last is None or prior_price is None or prior_price == 0:
        return None
    price_move = abs(last - prior_price) / prior_price * 100.0
    if price_move <= MARKET_CAP_PRICE_SYNC_PCT:
        return (
            f"Market cap shifted {mc_drift:.0f}% while price moved {price_move:.1f}% — "
            "verify share count/feed"
        )
    return None


def detect_pe_anomaly(item: TickerReport) -> str | None:
    """Flag a forward P/E that is negative or implausibly large."""
    if not item.valuation:
        return None
    pe = _as_float(item.valuation.metrics.get("forward_pe"))
    if pe is None:
        return None
    if pe < 0:
        return f"Forward P/E {pe:.1f} is negative — earnings estimate suspect"
    if pe > PE_CEILING:
        return f"Forward P/E {pe:.0f} above {PE_CEILING:.0f} — feed likely stale"
    return None


def detect_stale_data(
    snapshot: ValuationSnapshot | None, anchor_date: date
) -> str | None:
    """Flag a valuation snapshot retrieved more than STALE_HOURS before anchor."""
    if snapshot is None:
        return None
    retrieved = snapshot.retrieved_at
    if retrieved is None:
        return None
    if retrieved.tzinfo is None:
        retrieved = retrieved.replace(tzinfo=timezone.utc)
    anchor_dt = datetime(
        anchor_date.year, anchor_date.month, anchor_date.day, tzinfo=timezone.utc
    )
    age_hours = (anchor_dt - retrieved).total_seconds() / 3600.0
    if age_hours > STALE_HOURS:
        return f"Valuation {age_hours:.0f}h old (> {STALE_HOURS}h) — data may be stale"
    return None


def detect_news_overflow(item: TickerReport) -> str | None:
    """Flag an unusually large article count that may signal failed dedupe."""
    count = len(item.articles)
    if count > NEWS_OVERFLOW_COUNT:
        return f"{count} articles (> {NEWS_OVERFLOW_COUNT}) — check for duplicates"
    return None


def detect_earnings_source_risk(item: TickerReport) -> str | None:
    """Flag earnings dates that only come from yfinance-style feeds."""
    if not item.earnings:
        return None
    source = (item.earnings.source or "").lower()
    if "yfinance" in source or "yahoo" in source:
        return "Earnings date from yfinance only — verify with company IR or Nasdaq"
    return None


def detect_premarket_label_inconsistency(move: PremarketMove | None) -> str | None:
    """Flag premarket rows whose source/note looks like after-hours data."""
    if move is None:
        return None
    text = f"{move.source} {move.note}".lower()
    if any(term in text for term in ("post-market", "post market", "after-hours", "after hours", "after_market")):
        return "Premarket row carries post-market/after-hours label — verify session tag"
    return None


def detect_google_redirect_source(item: TickerReport) -> str | None:
    """Flag unresolved Google News redirect URLs instead of original sources."""
    for article in item.articles:
        domain = (article.domain or "").lower()
        url = (article.url or "").lower()
        if "google." in domain or "news.google." in url:
            return "Google News RSS redirect unresolved — verify original source"
    return None


def detect_duplicate_event_articles(item: TickerReport) -> str | None:
    """Flag repeated same-event headlines inside one ticker."""
    seen: set[str] = set()
    duplicates = 0
    for article in item.articles:
        key = " ".join((article.title or "").lower().split())
        if not key:
            continue
        if key in seen:
            duplicates += 1
        seen.add(key)
    if duplicates:
        return f"{duplicates} duplicate headline(s) — check event clustering"
    return None


def _is_fallback_valuation(item: TickerReport) -> bool:
    return any("fallback" in (w or "").lower() for w in item.warnings)


def confidence(
    item: TickerReport,
    anchor_date: date,
    *,
    prior_metrics: dict[str, Any] | None = None,
    premarket_move: PremarketMove | None = None,
) -> dict[str, Any]:
    """Aggregate anomaly flags into a 0-100 confidence score + high/med/low tag.

    Start at 100, deduct for fallback valuation, each anomaly flag, missing
    core fields, and stale data; clamp to [0, 100].
    """
    flags: list[str] = []
    penalties: list[int] = []

    def add(flag: str | None, penalty: int) -> None:
        if flag:
            flags.append(flag)
            penalties.append(penalty)

    add(detect_price_anomaly(item), 20)
    add(detect_price_regime_change(item), 25)
    add(detect_pe_anomaly(item), 10)
    add(detect_news_overflow(item), 20)
    add(detect_earnings_source_risk(item), 10)
    add(detect_premarket_label_inconsistency(premarket_move), 10)
    add(detect_google_redirect_source(item), 5)
    add(detect_duplicate_event_articles(item), 5)

    if item.valuation is not None:
        mismatch = detect_market_cap_price_mismatch(item.valuation.metrics, prior_metrics)
        if mismatch:
            add(mismatch, 10)
        elif prior_metrics is not None:
            add(detect_market_cap_drift(item.valuation.metrics, prior_metrics), 20)

    stale = detect_stale_data(item.valuation, anchor_date)
    add(stale, 20)

    score = 100
    if _is_fallback_valuation(item):
        score -= 20
    score -= sum(penalties)

    metrics = item.valuation.metrics if item.valuation else {}
    core_fields = ("last_close", "market_cap", "forward_pe")
    if not item.ticker.has_earnings:
        core_fields = ("last_close", "market_cap")
    missing = [key for key in core_fields if _as_float(metrics.get(key)) is None]
    if missing:
        score -= 10

    if stale:
        score -= 10

    score = max(0, min(100, score))
    if score >= 80:
        tag = "high"
    elif score >= 50:
        tag = "medium"
    else:
        tag = "low"

    return {
        "score": score,
        "tag": tag,
        "flags": flags,
        "missing_fields": missing,
        "fallback": _is_fallback_valuation(item),
    }
