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

from .models import TickerReport, ValuationSnapshot

PRICE_ANOMALY_PCT = 20.0
MARKET_CAP_DRIFT_PCT = 10.0
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


def _is_fallback_valuation(item: TickerReport) -> bool:
    return any("fallback" in (w or "").lower() for w in item.warnings)


def confidence(
    item: TickerReport,
    anchor_date: date,
    *,
    prior_metrics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Aggregate anomaly flags into a 0-100 confidence score + high/med/low tag.

    Start at 100, deduct for fallback valuation, each anomaly flag, missing
    core fields, and stale data; clamp to [0, 100].
    """
    flags: list[str] = []
    for detector in (
        detect_price_anomaly(item),
        detect_pe_anomaly(item),
        detect_news_overflow(item),
    ):
        if detector:
            flags.append(detector)

    if prior_metrics is not None and item.valuation is not None:
        drift = detect_market_cap_drift(item.valuation.metrics, prior_metrics)
        if drift:
            flags.append(drift)

    stale = detect_stale_data(item.valuation, anchor_date)
    if stale:
        flags.append(stale)

    score = 100
    if _is_fallback_valuation(item):
        score -= 20
    score -= 20 * len(flags)

    metrics = item.valuation.metrics if item.valuation else {}
    missing = [
        key
        for key in ("last_close", "market_cap", "forward_pe")
        if _as_float(metrics.get(key)) is None
    ]
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
