from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import yfinance as yf

from .models import MarketSentiment, MarketSentimentComponent
from .valuation import YF_HISTORY_TIMEOUT, _series_floats


def fetch_market_sentiment() -> MarketSentiment:
    """Build a free, yfinance-based Fear & Greed style market proxy.

    This is not CNN's proprietary index. It is a transparent proxy from liquid
    public tickers so the dashboard has a stable market-regime layer without a
    paid API: SPY/QQQ momentum, VIX level, and HYG/LQD credit appetite.
    """
    retrieved_at = datetime.now(timezone.utc)
    components: list[MarketSentimentComponent] = []
    warnings: list[str] = []

    for symbol, name, weight in (
        ("SPY", "SPY 20D momentum", 4.0),
        ("QQQ", "QQQ 20D momentum", 4.0),
    ):
        closes = _close_history(symbol, period="3mo")
        pct = _change_pct(closes, 20)
        if pct is None:
            warnings.append(f"{symbol} momentum unavailable.")
            continue
        score = _clamp(50.0 + pct * weight)
        components.append(MarketSentimentComponent(
            name=name,
            score=round(score, 1),
            label=_component_label(score),
            detail=f"{pct:+.1f}% over 20 sessions",
        ))

    vix = _last_close("^VIX", period="1mo")
    if vix is None:
        warnings.append("VIX level unavailable.")
    else:
        score = _score_vix(vix)
        components.append(MarketSentimentComponent(
            name="VIX level",
            score=round(score, 1),
            label=_component_label(score),
            detail=f"{vix:.1f}",
        ))

    hyg = _close_history("HYG", period="3mo")
    lqd = _close_history("LQD", period="3mo")
    ratio_pct = _ratio_change_pct(hyg, lqd, 20)
    if ratio_pct is None:
        warnings.append("HYG/LQD credit appetite unavailable.")
    else:
        score = _clamp(50.0 + ratio_pct * 8.0)
        components.append(MarketSentimentComponent(
            name="Credit appetite",
            score=round(score, 1),
            label=_component_label(score),
            detail=f"HYG/LQD {ratio_pct:+.1f}% over 20 sessions",
        ))

    if components:
        score = round(sum(component.score for component in components) / len(components))
    else:
        score = 50
        warnings.append("Market sentiment proxy fell back to neutral; no components were available.")

    return MarketSentiment(
        score=int(_clamp(score)),
        label=sentiment_label(score),
        source="yfinance proxy",
        retrieved_at=retrieved_at,
        components=components,
        warnings=warnings,
    )


def sentiment_label(score: float) -> str:
    if score <= 24:
        return "Extreme Fear"
    if score <= 44:
        return "Fear"
    if score < 56:
        return "Neutral"
    if score < 76:
        return "Greed"
    return "Extreme Greed"


def _component_label(score: float) -> str:
    if score <= 35:
        return "risk-off"
    if score >= 65:
        return "risk-on"
    return "neutral"


def _score_vix(value: float) -> float:
    if value <= 12:
        return 90.0
    if value >= 35:
        return 10.0
    return _clamp(90.0 - ((value - 12.0) / 23.0 * 80.0))


def _close_history(symbol: str, *, period: str) -> list[float]:
    try:
        hist = yf.Ticker(symbol).history(period=period, auto_adjust=True, timeout=YF_HISTORY_TIMEOUT)
    except Exception:
        return []
    if hist is None or getattr(hist, "empty", True) or "Close" not in hist.columns:
        return []
    return _series_floats(hist["Close"])


def _last_close(symbol: str, *, period: str) -> float | None:
    closes = _close_history(symbol, period=period)
    return closes[-1] if closes else None


def _change_pct(values: list[float], sessions: int) -> float | None:
    if len(values) < sessions + 1:
        return None
    base = values[-sessions - 1]
    if base == 0:
        return None
    return (values[-1] - base) / base * 100.0


def _ratio_change_pct(left: list[float], right: list[float], sessions: int) -> float | None:
    if len(left) < sessions + 1 or len(right) < sessions + 1:
        return None
    start_right = right[-sessions - 1]
    end_right = right[-1]
    if start_right == 0 or end_right == 0:
        return None
    start = left[-sessions - 1] / start_right
    end = left[-1] / end_right
    if start == 0:
        return None
    return (end - start) / start * 100.0


def _clamp(value: Any, low: float = 0.0, high: float = 100.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return low
    if number != number:
        return low
    return min(high, max(low, number))
