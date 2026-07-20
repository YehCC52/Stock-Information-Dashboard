from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from math import isfinite
from typing import Any

import yfinance as yf

from .models import PremarketMove, PremarketSnapshot, TickerConfig
from .valuation import YF_HISTORY_TIMEOUT, _series_floats


BENCHMARK_SYMBOLS: tuple[tuple[str, str], ...] = (
    ("ES=F", "S&P 500 futures"),
    ("NQ=F", "Nasdaq 100 futures"),
    ("SPY", "SPY premarket"),
    ("QQQ", "QQQ premarket"),
)


def fetch_overnight_premarket(
    tickers: list[TickerConfig],
    *,
    max_workers: int = 8,
) -> PremarketSnapshot:
    """Best-effort overnight / premarket snapshot from yfinance.

    yfinance exposes pre/post-market fields inconsistently across symbols and
    time of day. We prefer explicit pre-market prices when present, then fall
    back to the latest regular-market quote so the dashboard still has a
    morning tape read instead of failing the whole report.
    """
    us_tickers = [ticker for ticker in tickers if ticker.market == "us"]
    retrieved_at = datetime.now(timezone.utc)
    warnings: list[str] = []

    benchmarks: list[PremarketMove] = []
    for symbol, name in BENCHMARK_SYMBOLS:
        move = _fetch_move(symbol, name)
        if move is None:
            warnings.append(f"{symbol} premarket snapshot unavailable.")
            continue
        benchmarks.append(move)

    watchlist_moves: list[PremarketMove] = []
    workers = max(1, min(max_workers, len(us_tickers) or 1))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(_fetch_move, ticker.symbol, ticker.company_name): ticker
            for ticker in us_tickers
        }
        for future in as_completed(futures):
            ticker = futures[future]
            try:
                move = future.result()
            except Exception as exc:
                warnings.append(f"{ticker.symbol} premarket snapshot failed: {exc}")
                continue
            if move is None:
                continue
            watchlist_moves.append(move)

    ranked = sorted(
        (m for m in watchlist_moves if m.change_pct is not None),
        key=lambda m: abs(m.change_pct or 0.0),
        reverse=True,
    )
    gaps = [m for m in ranked if abs(m.change_pct or 0.0) >= 2.0]

    return PremarketSnapshot(
        retrieved_at=retrieved_at,
        benchmarks=benchmarks,
        watchlist_movers=ranked[:10],
        gap_movers=gaps,
        warnings=warnings,
    )


def _fetch_move(symbol: str, name: str) -> PremarketMove | None:
    ticker = yf.Ticker(symbol)
    try:
        info = ticker.get_info()
    except Exception:
        info = getattr(ticker, "info", {}) or {}
    info = info or {}

    price, source = _first_number(
        info,
        (
            ("preMarketPrice", "pre-market"),
            ("postMarketPrice", "post-market"),
            ("regularMarketPrice", "regular"),
            ("currentPrice", "current"),
        ),
    )
    previous, _prev_source = _first_number(
        info,
        (
            ("regularMarketPreviousClose", "previous close"),
            ("previousClose", "previous close"),
        ),
    )

    if price is None or previous is None:
        price, previous, source = _history_fallback(ticker, source)

    if price is None or previous is None or previous == 0:
        return None

    change_pct = round((price - previous) / previous * 100.0, 2)
    return PremarketMove(
        symbol=symbol,
        name=name,
        last=round(price, 2),
        previous_close=round(previous, 2),
        change_pct=change_pct,
        source=source or "latest",
        note="gap >=2%" if abs(change_pct) >= 2.0 else "",
    )


def _first_number(info: dict[str, Any], keys: tuple[tuple[str, str], ...]) -> tuple[float | None, str]:
    for key, label in keys:
        value = info.get(key)
        if isinstance(value, (int, float)) and isfinite(float(value)):
            return float(value), label
    return None, ""


def _history_fallback(ticker: Any, source: str) -> tuple[float | None, float | None, str]:
    try:
        hist = ticker.history(period="5d", auto_adjust=True, timeout=YF_HISTORY_TIMEOUT)
    except Exception:
        return None, None, source
    if hist is None or hist.empty or "Close" not in hist.columns:
        return None, None, source
    closes = _series_floats(hist["Close"])
    if len(closes) < 2:
        return None, None, source
    return closes[-1], closes[-2], source or "latest close"
