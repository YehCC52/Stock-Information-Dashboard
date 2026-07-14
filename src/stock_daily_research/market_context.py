"""Macro overlay: rates direction, ETF-pair breadth, and benchmark returns.

Single global fetch per run; not per-ticker. Powers the "is the tide going
up or down" framing on the dashboard, complementing MarketSentiment.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import yfinance as yf

from .models import BreadthRow, MarketContext, RateLevel
from .valuation import YF_HISTORY_TIMEOUT, _series_floats


# (display_name, yfinance_symbol, unit, kind).
# Yields are in percent in yfinance; we convert change to basis points.
# DXY and commodities surface as % daily change.
RATE_SYMBOLS: tuple[tuple[str, str, str, str], ...] = (
    ("5Y", "^FVX", "bp", "yield"),
    ("10Y", "^TNX", "bp", "yield"),
    ("30Y", "^TYX", "bp", "yield"),
    ("DXY", "DX-Y.NYB", "%", "fx"),
    ("WTI", "CL=F", "%", "commodity"),
)

# (display_label, A symbol, B symbol)
BREADTH_PAIRS: tuple[tuple[str, str, str], ...] = (
    ("QQQ vs QQQE", "QQQ", "QQQE"),
    ("SPY vs RSP", "SPY", "RSP"),
    ("SOXX vs SPY", "SOXX", "SPY"),
)

# Stable keys let report rules select a benchmark by the ticker's declared market.
BENCHMARK_SYMBOLS: tuple[tuple[str, str], ...] = (
    ("spy", "SPY"),
    ("qqq", "QQQ"),
    ("soxx", "SOXX"),
    ("twii", "^TWII"),
    ("btc", "BTC-USD"),
)
BENCHMARK_HORIZONS: tuple[int, ...] = (20, 60, 120)


def fetch_market_context() -> MarketContext:
    """Pull rates, breadth, and benchmark returns. Failures degrade silently."""
    retrieved_at = datetime.now(timezone.utc)
    warnings: list[str] = []

    rates: list[RateLevel] = []
    for name, symbol, unit, kind in RATE_SYMBOLS:
        closes = _close_history(symbol, period="5d")
        if not closes or len(closes) < 2:
            warnings.append(f"{name} ({symbol}) rate snapshot unavailable.")
            continue
        last, prev = closes[-1], closes[-2]
        if kind == "yield":
            change = round((last - prev) * 100, 1)  # bp
        else:
            change = round((last - prev) / prev * 100, 2) if prev else 0.0
        rates.append(RateLevel(
            name=name,
            last=round(last, 3),
            prev=round(prev, 3),
            change=change,
            unit=unit,
        ))

    breadth: list[BreadthRow] = []
    for label, a_sym, b_sym in BREADTH_PAIRS:
        a_ret = _n_day_return(a_sym, 20)
        b_ret = _n_day_return(b_sym, 20)
        if a_ret is None or b_ret is None:
            warnings.append(f"{label} breadth unavailable.")
            continue
        breadth.append(BreadthRow(
            label=label,
            a_symbol=a_sym,
            b_symbol=b_sym,
            a_return=round(a_ret, 2),
            b_return=round(b_ret, 2),
            spread=round(a_ret - b_ret, 2),
        ))

    benchmark_returns: dict[str, float] = {}
    for key, symbol in BENCHMARK_SYMBOLS:
        closes = _close_history(symbol, period="1y")
        if not closes:
            warnings.append(f"{symbol} benchmark history unavailable.")
            continue
        for horizon in BENCHMARK_HORIZONS:
            ret = _n_day_return_from_closes(closes, horizon)
            if ret is not None:
                benchmark_returns[f"{key}_{horizon}d"] = round(ret, 2)

    return MarketContext(
        rates=rates,
        breadth=breadth,
        benchmark_returns=benchmark_returns,
        retrieved_at=retrieved_at,
        warnings=warnings,
    )


def _close_history(symbol: str, *, period: str = "1mo") -> list[float] | None:
    try:
        hist = yf.Ticker(symbol).history(period=period, auto_adjust=True, timeout=YF_HISTORY_TIMEOUT)
    except Exception:
        return None
    if hist is None or hist.empty or "Close" not in hist.columns:
        return None
    return _series_floats(hist["Close"])


def _n_day_return(symbol: str, n: int) -> float | None:
    closes = _close_history(symbol, period="3mo")
    return _n_day_return_from_closes(closes, n)


def _n_day_return_from_closes(closes: list[float] | None, n: int) -> float | None:
    if not closes or len(closes) <= n:
        return None
    last = closes[-1]
    base = closes[-(n + 1)]
    if not base:
        return None
    return (last - base) / base * 100


def rates_interpretation(rates: list[RateLevel]) -> str:
    """One-line takeaway combining yields, dollar, and oil. Conservative wording.

    Decision matrix (yields × WTI):
      - Yields up + WTI up           → "Inflation pressure"
      - Yields down + WTI down       → "Macro tailwind"
      - Yields up + WTI down         → "Mixed: rates firm, oil soft"
      - Yields down + WTI up         → "Mixed: oil firm despite easing rates"
      - Everything flat              → "Rates mixed"
    """
    if not rates:
        return ""

    yields = [r for r in rates if r.unit == "bp"]
    dxy = next((r for r in rates if r.name == "DXY"), None)
    wti = next((r for r in rates if r.name == "WTI"), None)

    yields_up = bool(yields) and all(r.change > 2 for r in yields)
    yields_dn = bool(yields) and all(r.change < -2 for r in yields)
    wti_up = wti is not None and wti.change > 1.0
    wti_dn = wti is not None and wti.change < -1.0

    if yields_up and wti_up:
        msg = "Inflation pressure (yields + oil up)"
    elif yields_dn and wti_dn:
        msg = "Macro tailwind (yields + oil down)"
    elif yields_up and wti_dn:
        msg = "Mixed: yields rising, oil softening"
    elif yields_dn and wti_up:
        msg = "Mixed: oil firm despite easing rates"
    elif yields_up:
        msg = "Yields rising — headwind for high-multiple growth"
    elif yields_dn:
        msg = "Yields falling — tailwind for long-duration assets"
    elif wti_up:
        msg = "Oil firm — watch energy spillover"
    elif wti_dn:
        msg = "Oil softening — disinflationary nudge"
    else:
        msg = "Rates mixed"

    if dxy and abs(dxy.change) >= 0.3:
        sign = "+" if dxy.change > 0 else ""
        fx_tag = "risk-off" if dxy.change > 0 else "risk-on"
        msg += f"; DXY {sign}{dxy.change:.2f}% ({fx_tag} fx)"
    return msg


def market_regime(context: "MarketContext | None", sentiment_score: int | None) -> str:
    """One-phrase macro regime label for the hero / sentiment area.

    Combines yields direction, oil, dollar, and sentiment score into a short
    framing line. Returns empty string when there isn't enough data.

    Examples:
      - "Risk-on with easing rates"
      - "Oil-led inflation pressure"
      - "Broad rally with softer dollar"
      - "Defensive: yields up, sentiment cautious"
    """
    if context is None or not context.rates:
        return ""

    rates = context.rates
    yields = [r for r in rates if r.unit == "bp"]
    dxy = next((r for r in rates if r.name == "DXY"), None)
    wti = next((r for r in rates if r.name == "WTI"), None)

    yields_up = bool(yields) and all(r.change > 2 for r in yields)
    yields_dn = bool(yields) and all(r.change < -2 for r in yields)
    wti_up = wti is not None and wti.change > 1.0
    wti_dn = wti is not None and wti.change < -1.0
    dxy_up = dxy is not None and dxy.change > 0.3
    dxy_dn = dxy is not None and dxy.change < -0.3
    risk_on = sentiment_score is not None and sentiment_score >= 60
    risk_off = sentiment_score is not None and sentiment_score <= 40

    # Strong combinations — most specific first
    if yields_up and wti_up:
        return "Oil-led inflation pressure"
    if yields_dn and wti_dn and risk_on:
        return "Risk-on with easing rates"
    if yields_dn and dxy_dn and risk_on:
        return "Broad rally with softer dollar"
    if yields_up and risk_off:
        return "Defensive: yields up, sentiment cautious"
    if wti_up and dxy_up:
        return "Oil and dollar firm — global tightening tone"
    if yields_dn and risk_on:
        return "Easing-rates rally"
    if risk_off and dxy_up:
        return "Risk-off, dollar haven bid"

    return ""
