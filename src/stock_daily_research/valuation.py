from __future__ import annotations

import math
from numbers import Real
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
    "ttm_eps": "trailingEps",
    "forward_eps": "forwardEps",
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
    metrics.update(fetch_yfinance_eps_metrics(yf_ticker, metrics))
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
    keys = (
        "sma_5",
        "sma_20",
        "sma_60",
        "sma_120",
        "rsi_14",
        "return_5d",
        "return_20d",
        "return_60d",
        "volume_vs_20d",
        "atr_20",
        "atr_20_percent",
        "move_vs_atr",
        "gap_percent",
    )
    empty = {k: None for k in keys}
    try:
        hist = yf_ticker.history(period=period, auto_adjust=True)
    except Exception:
        return empty
    if hist is None or hist.empty or "Close" not in hist.columns:
        return empty
    closes = [float(v) for v in hist["Close"].dropna().tolist()]
    quality = compute_move_quality_metrics(hist)
    return {
        "sma_5": _mean_last_n(closes, 5),
        "sma_20": _mean_last_n(closes, 20),
        "sma_60": _mean_last_n(closes, 60),
        "sma_120": _mean_last_n(closes, 120),
        "rsi_14": compute_rsi(closes, 14),
        "return_5d": _n_session_return(closes, 5),
        "return_20d": _n_session_return(closes, 20),
        "return_60d": _n_session_return(closes, 60),
        **quality,
    }


def _n_session_return(closes: list[float], n: int) -> float | None:
    if not closes or len(closes) <= n:
        return None
    last = closes[-1]
    base = closes[-(n + 1)]
    if not base:
        return None
    return round((last - base) / base * 100, 2)


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


def compute_move_quality_metrics(hist: Any) -> dict[str, float | None]:
    keys = ("volume_vs_20d", "atr_20", "atr_20_percent", "move_vs_atr", "gap_percent")
    empty = {k: None for k in keys}
    required = {"Open", "High", "Low", "Close"}
    if hist is None or hist.empty or not required.issubset(set(hist.columns)):
        return empty

    closes = [float(v) for v in hist["Close"].dropna().tolist()]
    highs = [float(v) for v in hist["High"].dropna().tolist()]
    lows = [float(v) for v in hist["Low"].dropna().tolist()]
    opens = [float(v) for v in hist["Open"].dropna().tolist()]
    if len(closes) < 21 or len(highs) < 21 or len(lows) < 21 or len(opens) < 2:
        return empty

    latest_close = closes[-1]
    prev_close = closes[-2]
    latest_open = opens[-1]
    if latest_close == 0 or prev_close == 0:
        return empty

    true_ranges: list[float] = []
    start = max(1, len(closes) - 20)
    for idx in range(start, len(closes)):
        true_ranges.append(max(
            highs[idx] - lows[idx],
            abs(highs[idx] - closes[idx - 1]),
            abs(lows[idx] - closes[idx - 1]),
        ))
    atr_20 = sum(true_ranges) / len(true_ranges) if true_ranges else None

    volume_vs_20d = None
    if "Volume" in hist.columns:
        volumes = [float(v) for v in hist["Volume"].dropna().tolist()]
        if len(volumes) >= 21:
            prior_20 = [v for v in volumes[-21:-1] if v > 0]
            if prior_20:
                volume_vs_20d = volumes[-1] / (sum(prior_20) / len(prior_20))

    move_vs_atr = None
    atr_20_percent = None
    if atr_20 and atr_20 > 0:
        move_vs_atr = abs(latest_close - prev_close) / atr_20
        atr_20_percent = atr_20 / latest_close * 100.0

    gap_percent = (latest_open - prev_close) / prev_close * 100.0

    return {
        "volume_vs_20d": round(volume_vs_20d, 2) if volume_vs_20d is not None else None,
        "atr_20": round(atr_20, 2) if atr_20 is not None else None,
        "atr_20_percent": round(atr_20_percent, 2) if atr_20_percent is not None else None,
        "move_vs_atr": round(move_vs_atr, 2) if move_vs_atr is not None else None,
        "gap_percent": round(gap_percent, 2),
    }


def _safe_info(yf_ticker: Any) -> dict[str, Any]:
    try:
        info = yf_ticker.get_info()
    except Exception:
        info = getattr(yf_ticker, "info", {}) or {}
    return info or {}


def fetch_yfinance_eps_metrics(yf_ticker: Any, base_metrics: dict[str, Any] | None = None) -> dict[str, float | None]:
    """Fetch EPS estimate and revision metrics from yfinance's analysis tables.

    Static EPS fields come from quote info, while next-FY estimate / revisions
    are best-effort from the analysis scraper. Missing analysis data degrades to
    N/A because yfinance can be inconsistent by ticker and region.
    """
    metrics: dict[str, float | None] = {
        "next_fy_eps": None,
        "eps_growth_pct": None,
        "fy1_eps_revision_30d": None,
        "fy1_eps_revision_up_30d": None,
        "fy1_eps_revision_down_30d": None,
    }

    estimate = _safe_dataframe(lambda: yf_ticker.get_earnings_estimate())
    if estimate is None:
        estimate = _safe_dataframe(lambda: getattr(yf_ticker, "earnings_estimate", None))
    if estimate is not None:
        row = _estimate_row(estimate, "+1y")
        if row is None:
            row = _estimate_row(estimate, "0y")
        if row is not None:
            metrics["next_fy_eps"] = _clean_float(_row_get(row, "avg"))
            growth = _clean_float(_row_get(row, "growth"))
            if growth is not None:
                metrics["eps_growth_pct"] = round(growth * 100.0, 2)

    trend = _safe_dataframe(lambda: getattr(yf_ticker._analysis, "eps_trend", None))
    if trend is not None:
        row = _estimate_row(trend, "+1y")
        if row is None:
            row = _estimate_row(trend, "0y")
        if row is not None:
            current = _clean_float(_row_get(row, "current"))
            ago_30 = _clean_float(_row_get(row, "30daysAgo"))
            if current is not None and ago_30 not in (None, 0):
                metrics["fy1_eps_revision_30d"] = round((current - ago_30) / abs(ago_30) * 100.0, 2)
            if metrics["next_fy_eps"] is None and current is not None:
                metrics["next_fy_eps"] = current

    revisions = _safe_dataframe(lambda: getattr(yf_ticker._analysis, "eps_revisions", None))
    if revisions is not None:
        row = _estimate_row(revisions, "+1y")
        if row is None:
            row = _estimate_row(revisions, "0y")
        if row is not None:
            metrics["fy1_eps_revision_up_30d"] = _clean_float(_row_get(row, "upLast30days"))
            metrics["fy1_eps_revision_down_30d"] = _clean_float(_row_get(row, "downLast30days"))

    base = base_metrics or {}
    if metrics["next_fy_eps"] is None:
        metrics["next_fy_eps"] = _clean_float(base.get("forward_eps"))
    if metrics["eps_growth_pct"] is None:
        ttm = _clean_float(base.get("ttm_eps"))
        next_fy = metrics["next_fy_eps"]
        if ttm not in (None, 0) and next_fy is not None:
            metrics["eps_growth_pct"] = round((next_fy - ttm) / abs(ttm) * 100.0, 2)

    return metrics


def _safe_dataframe(fetcher: Any) -> Any | None:
    try:
        df = fetcher()
    except Exception:
        return None
    if df is None:
        return None
    if hasattr(df, "empty") and df.empty:
        return None
    return df


def _estimate_row(df: Any, label: str) -> Any | None:
    try:
        if label in df.index:
            return df.loc[label]
    except Exception:
        return None
    return None


def _row_get(row: Any, key: str) -> Any:
    try:
        return row.get(key)
    except AttributeError:
        return None


def _clean_float(value: Any) -> float | None:
    if isinstance(value, Real):
        if isinstance(value, float) and math.isnan(value):
            return None
        return float(value)
    return None


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
