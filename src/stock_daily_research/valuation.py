from __future__ import annotations

import math
from numbers import Real
from datetime import date, datetime, timezone
from typing import Any

import yfinance as yf

from .models import EarningsDate, TickerConfig, ValuationSnapshot

# Explicit bound on yfinance price-history calls. yfinance defaults to 10s
# internally; pin it here so the timeout is visible and tunable in one place.
YF_HISTORY_TIMEOUT = 10


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
    # Yahoo does not expose quoteSummary fundamentals for many ETFs. Avoid that
    # endpoint for assets configured without fundamentals; technical data remains available.
    info = _safe_info(yf_ticker) if ticker.has_fundamentals else {}
    metrics = normalize_yfinance_metrics(info)
    if ticker.has_earnings:
        metrics.update(fetch_yfinance_eps_metrics(yf_ticker, metrics))
    else:
        # Assets without fundamentals have no analyst estimates; keep the keys so downstream
        # consumers see a consistent metrics shape.
        metrics.update(empty_estimate_metrics())
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
        hist = yf_ticker.history(period=period, auto_adjust=True, timeout=YF_HISTORY_TIMEOUT)
    except Exception:
        return empty
    if hist is None or hist.empty or "Close" not in hist.columns:
        return empty
    closes = _series_floats(hist["Close"])
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
        "return_120d",
        "prior_20d_high",
        "prior_20d_low",
        "sma_20_slope_5d",
        "volume_vs_20d",
        "atr_20",
        "atr_20_percent",
        "move_vs_atr",
        "gap_percent",
        "atr_10_percent",
        "atr_contraction_ratio",
        "bb_width_20_percent",
        "bb_width_20_percentile",
        "volume_5d_vs_20d",
        "breakout_days_ago",
        "breakout_pivot",
        "breakout_hold_pct",
        "breakout_volume_vs_20d",
    )
    empty = {k: None for k in keys}
    try:
        hist = yf_ticker.history(period=period, auto_adjust=True, timeout=YF_HISTORY_TIMEOUT)
    except Exception:
        return empty
    if hist is None or hist.empty or "Close" not in hist.columns:
        return empty
    closes = _series_floats(hist["Close"])
    quality = compute_move_quality_metrics(hist)
    trend_structure = compute_trend_structure_metrics(hist)
    right_side_setup = compute_right_side_setup_metrics(hist)
    return {
        "sma_5": _mean_last_n(closes, 5),
        "sma_20": _mean_last_n(closes, 20),
        "sma_60": _mean_last_n(closes, 60),
        "sma_120": _mean_last_n(closes, 120),
        "rsi_14": compute_rsi(closes, 14),
        "return_5d": _n_session_return(closes, 5),
        "return_20d": _n_session_return(closes, 20),
        "return_60d": _n_session_return(closes, 60),
        "return_120d": _n_session_return(closes, 120),
        **trend_structure,
        **quality,
        **right_side_setup,
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


def _series_floats(series: Any) -> list[float]:
    """Coerce a pandas column to floats, dropping NaN and any non-numeric cells.

    A single malformed value in a yfinance frame must not crash the whole run,
    so unconvertible entries are skipped rather than raising.
    """
    out: list[float] = []
    for value in series.dropna().tolist():
        try:
            out.append(float(value))
        except (TypeError, ValueError):
            continue
    return out


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


def compute_trend_structure_metrics(hist: Any) -> dict[str, float | None]:
    """Compute breakout levels and a short SMA20 slope from daily candles.

    ``prior_20d_high`` and ``prior_20d_low`` exclude the latest session so a
    close can genuinely qualify as a new 20-session breakout or breakdown.
    The slope compares today''s 20D SMA with its value five sessions earlier.
    """
    keys = ("prior_20d_high", "prior_20d_low", "sma_20_slope_5d")
    empty = {key: None for key in keys}
    if hist is None or hist.empty or "Close" not in hist.columns:
        return empty

    closes = _series_floats(hist["Close"])
    if len(closes) < 21:
        return empty

    result = dict(empty)
    if "High" in hist.columns:
        highs = _series_floats(hist["High"])
        if len(highs) >= 21:
            result["prior_20d_high"] = round(max(highs[-21:-1]), 4)
    if "Low" in hist.columns:
        lows = _series_floats(hist["Low"])
        if len(lows) >= 21:
            result["prior_20d_low"] = round(min(lows[-21:-1]), 4)

    if len(closes) >= 25:
        current_sma20 = _mean_last_n(closes, 20)
        prior_sma20 = _mean_last_n(closes[-25:-5], 20)
        if current_sma20 is not None and prior_sma20 not in (None, 0):
            result["sma_20_slope_5d"] = round((current_sma20 - prior_sma20) / prior_sma20 * 100.0, 2)
    return result

def compute_move_quality_metrics(hist: Any) -> dict[str, float | None]:
    keys = ("volume_vs_20d", "atr_20", "atr_20_percent", "move_vs_atr", "gap_percent")
    empty = {k: None for k in keys}
    required = {"Open", "High", "Low", "Close"}
    if hist is None or hist.empty or not required.issubset(set(hist.columns)):
        return empty

    closes = _series_floats(hist["Close"])
    highs = _series_floats(hist["High"])
    lows = _series_floats(hist["Low"])
    opens = _series_floats(hist["Open"])
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
        volumes = _series_floats(hist["Volume"])
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


def compute_right_side_setup_metrics(hist: Any) -> dict[str, float | None]:
    """Measure base contraction and recent breakout retention from daily candles."""
    keys = (
        "atr_10_percent",
        "atr_contraction_ratio",
        "bb_width_20_percent",
        "bb_width_20_percentile",
        "volume_5d_vs_20d",
        "breakout_days_ago",
        "breakout_pivot",
        "breakout_hold_pct",
        "breakout_volume_vs_20d",
    )
    empty = {key: None for key in keys}
    required = {"High", "Low", "Close"}
    if hist is None or hist.empty or not required.issubset(set(hist.columns)):
        return empty

    closes = _series_floats(hist["Close"])
    highs = _series_floats(hist["High"])
    lows = _series_floats(hist["Low"])
    count = min(len(closes), len(highs), len(lows))
    if count < 21:
        return empty
    closes, highs, lows = closes[-count:], highs[-count:], lows[-count:]

    result = dict(empty)
    atr_10 = _average_true_range(highs, lows, closes, 10)
    atr_20 = _average_true_range(highs, lows, closes, 20)
    if atr_10 is not None and closes[-1] > 0:
        result["atr_10_percent"] = round(atr_10 / closes[-1] * 100.0, 2)
    if atr_10 is not None and atr_20 not in (None, 0):
        result["atr_contraction_ratio"] = round(atr_10 / atr_20, 2)

    if len(closes) >= 40:
        widths = [
            width
            for end in range(20, len(closes) + 1)
            if (width := _bollinger_width_percent(closes[end - 20:end])) is not None
        ]
        if widths:
            current_width = widths[-1]
            result["bb_width_20_percent"] = round(current_width, 2)
            result["bb_width_20_percentile"] = round(
                sum(width <= current_width for width in widths) / len(widths) * 100.0,
                1,
            )

    volumes: list[float] = []
    if "Volume" in hist.columns:
        candidate = _series_floats(hist["Volume"])
        if len(candidate) == count:
            volumes = candidate
    if len(volumes) >= 25:
        recent = [value for value in volumes[-5:] if value > 0]
        baseline = [value for value in volumes[-25:-5] if value > 0]
        if recent and baseline:
            result["volume_5d_vs_20d"] = round(
                (sum(recent) / len(recent)) / (sum(baseline) / len(baseline)),
                2,
            )

    for days_ago in range(min(5, count - 20)):
        idx = count - 1 - days_ago
        pivot = max(highs[idx - 20:idx])
        if pivot <= 0 or closes[idx] <= pivot:
            continue
        event_volume = None
        if len(volumes) == count:
            baseline = [value for value in volumes[idx - 20:idx] if value > 0]
            if baseline and volumes[idx] > 0:
                event_volume = volumes[idx] / (sum(baseline) / len(baseline))
        result["breakout_days_ago"] = float(days_ago)
        result["breakout_pivot"] = round(pivot, 4)
        result["breakout_hold_pct"] = round((closes[-1] - pivot) / pivot * 100.0, 2)
        result["breakout_volume_vs_20d"] = round(event_volume, 2) if event_volume is not None else None
        break

    return result


def _average_true_range(highs: list[float], lows: list[float], closes: list[float], period: int) -> float | None:
    if period <= 0 or len(closes) < period + 1:
        return None
    start = max(1, len(closes) - period)
    true_ranges = [
        max(
            highs[idx] - lows[idx],
            abs(highs[idx] - closes[idx - 1]),
            abs(lows[idx] - closes[idx - 1]),
        )
        for idx in range(start, len(closes))
    ]
    return sum(true_ranges) / len(true_ranges) if true_ranges else None


def _bollinger_width_percent(values: list[float]) -> float | None:
    if len(values) < 2:
        return None
    average = sum(values) / len(values)
    if average == 0:
        return None
    variance = sum((value - average) ** 2 for value in values) / len(values)
    return math.sqrt(variance) * 4.0 / average * 100.0

def _safe_info(yf_ticker: Any) -> dict[str, Any]:
    try:
        info = yf_ticker.get_info()
    except Exception:
        info = getattr(yf_ticker, "info", {}) or {}
    return info or {}


def empty_estimate_metrics() -> dict[str, float | None]:
    """All analyst-estimate metric keys set to None."""
    return {
        "next_fy_eps": None,
        "eps_growth_pct": None,
        "fy1_eps_revision_30d": None,
        "fy1_eps_revision_up_30d": None,
        "fy1_eps_revision_down_30d": None,
        "next_q_revenue": None,
        "next_q_revenue_growth_pct": None,
        "next_fy_revenue": None,
        "revenue_growth_pct": None,
        "fy1_revenue_revision_30d": None,
        "next_q_revenue_revision_30d": None,
        "latest_reported_eps": None,
        "latest_eps_estimate": None,
        "latest_eps_surprise_pct": None,
        "latest_reported_revenue": None,
        "latest_revenue_estimate": None,
        "latest_revenue_surprise_pct": None,
    }


def fetch_yfinance_eps_metrics(yf_ticker: Any, base_metrics: dict[str, Any] | None = None) -> dict[str, float | None]:
    """Fetch EPS estimate and revision metrics from yfinance's analysis tables.

    Static EPS fields come from quote info, while next-FY estimate / revisions
    are best-effort from the analysis scraper. Missing analysis data degrades to
    N/A because yfinance can be inconsistent by ticker and region.
    """
    metrics = empty_estimate_metrics()

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

    revenue = _safe_dataframe(lambda: getattr(yf_ticker, "revenue_estimate", None))
    if revenue is None:
        revenue = _safe_dataframe(lambda: yf_ticker.get_revenue_estimate())
    if revenue is not None:
        q_row = _estimate_row(revenue, "+1q")
        if q_row is None:
            q_row = _estimate_row(revenue, "0q")
        if q_row is not None:
            metrics["next_q_revenue"] = _clean_float(_row_get(q_row, "avg"))
            q_growth = _clean_float(_row_get(q_row, "growth"))
            if q_growth is not None:
                metrics["next_q_revenue_growth_pct"] = round(q_growth * 100.0, 2)

        row = _estimate_row(revenue, "+1y")
        if row is None:
            row = _estimate_row(revenue, "0y")
        if row is not None:
            metrics["next_fy_revenue"] = _clean_float(_row_get(row, "avg"))
            growth = _clean_float(_row_get(row, "growth"))
            if growth is not None:
                metrics["revenue_growth_pct"] = round(growth * 100.0, 2)

    base = base_metrics or {}
    if metrics["next_fy_eps"] is None:
        metrics["next_fy_eps"] = _clean_float(base.get("forward_eps"))
    if metrics["eps_growth_pct"] is None:
        ttm = _clean_float(base.get("ttm_eps"))
        next_fy = metrics["next_fy_eps"]
        if ttm not in (None, 0) and next_fy is not None:
            metrics["eps_growth_pct"] = round((next_fy - ttm) / abs(ttm) * 100.0, 2)

    metrics.update(fetch_yfinance_post_earnings_metrics(yf_ticker))

    return metrics


def fetch_yfinance_post_earnings_metrics(yf_ticker: Any) -> dict[str, float | None]:
    metrics: dict[str, float | None] = {
        "latest_reported_eps": None,
        "latest_eps_estimate": None,
        "latest_eps_surprise_pct": None,
        "latest_reported_revenue": None,
        "latest_revenue_estimate": None,
        "latest_revenue_surprise_pct": None,
    }
    history = _safe_dataframe(lambda: yf_ticker.get_earnings_history())
    if history is None:
        history = _safe_dataframe(lambda: getattr(yf_ticker, "earnings_history", None))
    row = _latest_record(history)
    if row:
        metrics["latest_reported_eps"] = _first_float(row, ("epsActual", "reportedEPS", "Reported EPS", "actual"))
        metrics["latest_eps_estimate"] = _first_float(row, ("epsEstimate", "EPS Estimate", "estimate"))
        surprise = _first_float(row, ("surprisePercent", "Surprise(%)", "epsSurprisePercent"))
        if surprise is None:
            actual = metrics["latest_reported_eps"]
            estimate = metrics["latest_eps_estimate"]
            if actual is not None and estimate not in (None, 0):
                surprise = (actual - estimate) / abs(estimate) * 100.0
        metrics["latest_eps_surprise_pct"] = round(surprise, 2) if surprise is not None else None
        metrics["latest_reported_revenue"] = _first_float(row, ("reportedRevenue", "Reported Revenue", "revenueActual"))
        metrics["latest_revenue_estimate"] = _first_float(row, ("revenueEstimate", "Revenue Estimate", "revenueAverage"))
        revenue_surprise = _first_float(row, ("revenueSurprisePercent", "Revenue Surprise(%)", "revenueSurprisePct"))
        if revenue_surprise is None:
            actual_revenue = metrics["latest_reported_revenue"]
            estimate_revenue = metrics["latest_revenue_estimate"]
            if actual_revenue is not None and estimate_revenue not in (None, 0):
                revenue_surprise = (actual_revenue - estimate_revenue) / abs(estimate_revenue) * 100.0
        metrics["latest_revenue_surprise_pct"] = round(revenue_surprise, 2) if revenue_surprise is not None else None

    dates = _safe_dataframe(lambda: yf_ticker.get_earnings_dates(limit=4))
    if dates is None:
        dates = _safe_dataframe(lambda: getattr(yf_ticker, "earnings_dates", None))
    date_row = _latest_record(dates)
    if date_row:
        if metrics["latest_reported_eps"] is None:
            metrics["latest_reported_eps"] = _first_float(date_row, ("Reported EPS", "reportedEPS", "epsActual"))
        if metrics["latest_eps_estimate"] is None:
            metrics["latest_eps_estimate"] = _first_float(date_row, ("EPS Estimate", "epsEstimate"))
        if metrics["latest_eps_surprise_pct"] is None:
            surprise = _first_float(date_row, ("Surprise(%)", "surprisePercent"))
            metrics["latest_eps_surprise_pct"] = round(surprise, 2) if surprise is not None else None

    return metrics


def _latest_record(df: Any | None) -> dict[str, Any] | None:
    if df is None:
        return None
    try:
        records = df.reset_index().to_dict("records")
    except Exception:
        return None
    if not records:
        return None
    today = datetime.now(timezone.utc).date()

    def sort_key(row: dict[str, Any]) -> tuple[int, date]:
        for key in ("quarter", "date", "Earnings Date", "index"):
            parsed = coerce_date(row.get(key))
            if parsed is not None:
                return (0 if parsed <= today else 1, parsed)
        return (2, date.min)

    past = [row for row in records if sort_key(row)[0] == 0]
    if past:
        return sorted(past, key=lambda row: sort_key(row)[1], reverse=True)[0]
    return records[0]


def _first_float(row: dict[str, Any], keys: tuple[str, ...]) -> float | None:
    for key in keys:
        value = _clean_float(row.get(key))
        if value is not None:
            return value
    return None


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
