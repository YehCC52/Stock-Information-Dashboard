from __future__ import annotations

import math
from datetime import date, datetime, timezone
from typing import Any

import yfinance as yf

from .models import EarningsDate, TickerConfig, ValuationSnapshot


YFINANCE_FIELD_MAP = {
    "last_close": "regularMarketPrice",
    "previous_close": "regularMarketPreviousClose",
    "fifty_two_week_high": "fiftyTwoWeekHigh",
    "fifty_two_week_low": "fiftyTwoWeekLow",
    "market_cap": "marketCap",
    "enterprise_value": "enterpriseValue",
    "trailing_pe": "trailingPE",
    "forward_pe": "forwardPE",
    "peg_ratio": "trailingPegRatio",
    "price_to_sales": "priceToSalesTrailing12Months",
    "price_to_book": "priceToBook",
    "ev_to_revenue": "enterpriseToRevenue",
    "ev_to_ebitda": "enterpriseToEbitda",
    "sector": "sector",
    "industry": "industry",
}


def fetch_yfinance_valuation(ticker: TickerConfig) -> ValuationSnapshot:
    retrieved_at = datetime.now(timezone.utc)
    yf_ticker = yf.Ticker(ticker.symbol)
    info = _safe_info(yf_ticker)
    metrics = normalize_yfinance_metrics(info)
    metrics.update(fetch_technical_indicators(yf_ticker))
    return ValuationSnapshot(
        ticker=ticker.symbol,
        as_of_date=retrieved_at.date(),
        source="yfinance",
        metrics=metrics,
        retrieved_at=retrieved_at,
    )


def fetch_moving_averages(yf_ticker: Any, period: str = "1y") -> dict[str, float | None]:
    """Compute simple moving averages from recent close history.

    Returns sma_5, sma_20, sma_60, sma_120 — `None` when insufficient history.
    Failures are swallowed: a missing MA degrades the trend display, never the run.
    """
    sma_keys = ("sma_5", "sma_20", "sma_60", "sma_120")
    empty = {k: None for k in sma_keys}
    try:
        hist = yf_ticker.history(period=period, auto_adjust=True)
    except Exception:
        return empty
    if hist is None or hist.empty or "Close" not in hist.columns:
        return empty
    closes = [float(v) for v in hist["Close"].dropna().tolist()]
    return {
        "sma_5": _mean_last_n(closes, 5),
        "sma_20": _mean_last_n(closes, 20),
        "sma_60": _mean_last_n(closes, 60),
        "sma_120": _mean_last_n(closes, 120),
    }


def fetch_technical_indicators(yf_ticker: Any, period: str = "1y") -> dict[str, float | None]:
    keys = ("sma_5", "sma_20", "sma_60", "sma_120", "rsi_14")
    empty = {k: None for k in keys}
    try:
        hist = yf_ticker.history(period=period, auto_adjust=True)
    except Exception:
        return empty
    if hist is None or hist.empty or "Close" not in hist.columns:
        return empty
    closes = [float(v) for v in hist["Close"].dropna().tolist()]
    return {
        "sma_5": _mean_last_n(closes, 5),
        "sma_20": _mean_last_n(closes, 20),
        "sma_60": _mean_last_n(closes, 60),
        "sma_120": _mean_last_n(closes, 120),
        "rsi_14": compute_rsi(closes, 14),
    }


def _mean_last_n(values: list[float], n: int) -> float | None:
    if len(values) < n:
        return None
    return sum(values[-n:]) / n


def compute_rsi(values: list[float], period: int = 14) -> float | None:
    if period <= 0 or len(values) < period + 1:
        return None
    deltas = [values[idx] - values[idx - 1] for idx in range(1, len(values))]
    recent = deltas[-period:]
    gains = [delta for delta in recent if delta > 0]
    losses = [-delta for delta in recent if delta < 0]
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    if avg_loss == 0:
        return 100.0 if avg_gain > 0 else 50.0
    rs = avg_gain / avg_loss
    return round(100.0 - (100.0 / (1.0 + rs)), 2)


def _safe_info(yf_ticker: Any) -> dict[str, Any]:
    try:
        info = yf_ticker.get_info()
    except Exception:
        info = getattr(yf_ticker, "info", {}) or {}
    return info or {}


def get_yfinance_info(symbol: str) -> dict[str, Any]:
    yf_ticker = yf.Ticker(symbol)
    try:
        info = yf_ticker.get_info()
    except Exception:
        info = getattr(yf_ticker, "info", {}) or {}
    return info or {}


def normalize_yfinance_metrics(info: dict[str, Any]) -> dict[str, Any]:
    metrics = {metric: info.get(field) for metric, field in YFINANCE_FIELD_MAP.items()}
    if metrics["peg_ratio"] is None:
        metrics["peg_ratio"] = info.get("pegRatio")
    if metrics.get("last_close") is None:
        # Some symbols (delisted, halted, foreign) don't expose regularMarketPrice;
        # fall back through the chain.
        metrics["last_close"] = info.get("previousClose") or info.get("currentPrice")
    if metrics.get("previous_close") is None:
        metrics["previous_close"] = info.get("previousClose")
    return {key: _clean_metric(value) for key, value in metrics.items()}


def _clean_metric(value: Any) -> Any:
    if isinstance(value, float) and math.isnan(value):
        return None
    return value


def fetch_yfinance_earnings_date(ticker: TickerConfig) -> EarningsDate:
    retrieved_at = datetime.now(timezone.utc)
    yf_ticker = yf.Ticker(ticker.symbol)
    earnings_date = None
    time_of_day = "unknown"

    try:
        calendar = yf_ticker.calendar
    except Exception:
        calendar = None

    earnings_date = extract_earnings_date(calendar)
    return EarningsDate(
        ticker=ticker.symbol,
        company_name=ticker.company_name,
        earnings_date=earnings_date,
        time_of_day=time_of_day,
        fiscal_quarter=None,
        fiscal_year=None,
        eps_estimate=None,
        revenue_estimate=None,
        source="yfinance",
        source_retrieved_at=retrieved_at,
    )


def extract_earnings_date(calendar: Any) -> date | None:
    if calendar is None:
        return None

    if isinstance(calendar, dict):
        value = calendar.get("Earnings Date") or calendar.get("EarningsDate")
        return coerce_date(value)

    try:
        if hasattr(calendar, "loc") and "Earnings Date" in calendar.index:
            return coerce_date(calendar.loc["Earnings Date"].dropna().iloc[0])
    except Exception:
        return None

    return None


def coerce_date(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, (list, tuple)) and value:
        return coerce_date(value[0])
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).date()
    except ValueError:
        return None


def format_metric_value(value: Any) -> str:
    if value is None:
        return "N/A"
    if isinstance(value, float) and math.isnan(value):
        return "N/A"
    if isinstance(value, (int, float)):
        if abs(value) >= 1_000_000_000_000:
            return f"{value / 1_000_000_000_000:.2f}T"
        if abs(value) >= 1_000_000_000:
            return f"{value / 1_000_000_000:.2f}B"
        if abs(value) >= 1_000_000:
            return f"{value / 1_000_000:.2f}M"
        return f"{value:.2f}"
    return str(value)
