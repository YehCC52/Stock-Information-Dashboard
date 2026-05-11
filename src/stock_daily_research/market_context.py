"""Macro overlay: rates direction, ETF-pair breadth, and benchmark returns.

Single global fetch per run; not per-ticker. Powers the "is the tide going
up or down" framing on the dashboard, complementing MarketSentiment.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import yfinance as yf

from .models import BreadthRow, MarketContext, RateLevel


# (display_name, yfinance_symbol, unit, multiplier_for_change)
# Yields are in percent in yfinance; we convert change to basis points.
RATE_SYMBOLS: tuple[tuple[str, str, str, str], ...] = (
    ("5Y", "^FVX", "bp", "yield"),
    ("10Y", "^TNX", "bp", "yield"),
    ("30Y", "^TYX", "bp", "yield"),
    ("DXY", "DX-Y.NYB", "%", "fx"),
)

# (display_label, A symbol, B symbol)
BREADTH_PAIRS: tuple[tuple[str, str, str], ...] = (
    ("QQQ vs QQQE", "QQQ", "QQQE"),
    ("SPY vs RSP", "SPY", "RSP"),
    ("SOXX vs SPY", "SOXX", "SPY"),
)


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
    for symbol in ("SPY", "QQQ"):
        ret = _n_day_return(symbol, 20)
        if ret is not None:
            benchmark_returns[f"{symbol.lower()}_20d"] = round(ret, 2)

    return MarketContext(
        rates=rates,
        breadth=breadth,
        benchmark_returns=benchmark_returns,
        retrieved_at=retrieved_at,
        warnings=warnings,
    )


def _close_history(symbol: str, *, period: str = "1mo") -> list[float] | None:
    try:
        hist = yf.Ticker(symbol).history(period=period, auto_adjust=True)
    except Exception:
        return None
    if hist is None or hist.empty or "Close" not in hist.columns:
        return None
    return [float(v) for v in hist["Close"].dropna().tolist()]


def _n_day_return(symbol: str, n: int) -> float | None:
    closes = _close_history(symbol, period="3mo")
    if not closes or len(closes) <= n:
        return None
    last = closes[-1]
    base = closes[-(n + 1)]
    if not base:
        return None
    return (last - base) / base * 100


def rates_interpretation(rates: list[RateLevel]) -> str:
    """One-line takeaway from current rates direction. Conservative wording."""
    if not rates:
        return ""
    yields = [r for r in rates if r.unit == "bp"]
    dxy = next((r for r in rates if r.unit == "%" and r.name == "DXY"), None)
    if yields and all(r.change > 2 for r in yields):
        msg = "Yields rising — headwind for high-multiple growth"
    elif yields and all(r.change < -2 for r in yields):
        msg = "Yields falling — tailwind for long-duration assets"
    else:
        msg = "Rates mixed"
    if dxy and abs(dxy.change) >= 0.3:
        msg += f"; DXY {'+' if dxy.change > 0 else ''}{dxy.change:.2f}% ({'risk-off' if dxy.change > 0 else 'risk-on'} fx)"
    return msg
