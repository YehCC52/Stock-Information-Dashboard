from __future__ import annotations

import logging
import math
import sqlite3
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable, Iterable

import pandas as pd

from .models import HistoricalPriceBar, TickerConfig
from .storage import (
    load_backtest_price_bars,
    load_backtest_price_coverage,
    save_backtest_price_bars,
    save_backtest_price_coverage,
)


logger = logging.getLogger(__name__)

HistoryLoader = Callable[[str, date, date], Any]
BACKTEST_DATA_SOURCE = "yfinance"


@dataclass(frozen=True)
class HistoricalDataBundle:
    bars_by_symbol: dict[str, list[HistoricalPriceBar]]
    quality_by_symbol: dict[str, dict[str, Any]] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    cache_hits: tuple[str, ...] = ()
    fetched_symbols: tuple[str, ...] = ()
    unavailable_symbols: tuple[str, ...] = ()


class HistoricalPriceProvider:
    """Fetch validated adjusted daily OHLCV with durable SQLite fallback."""

    def __init__(
        self,
        history_loader: HistoryLoader | None = None,
        *,
        source: str = BACKTEST_DATA_SOURCE,
    ) -> None:
        self.history_loader = history_loader or _load_yfinance_history
        self.source = source

    def load(
        self,
        conn: sqlite3.Connection,
        tickers: Iterable[TickerConfig],
        *,
        start_date: date,
        end_date: date,
        offline: bool = False,
        refresh: bool = False,
        max_workers: int = 6,
    ) -> HistoricalDataBundle:
        if start_date >= end_date:
            raise ValueError("historical data start_date must be before end_date")

        ordered = _unique_tickers(tickers)
        bars_by_symbol: dict[str, list[HistoricalPriceBar]] = {}
        warnings: list[str] = []
        cache_hits: list[str] = []
        fetched: list[str] = []
        unavailable: list[str] = []
        requests: list[tuple[TickerConfig, date, date]] = []

        for ticker in ordered:
            coverage = load_backtest_price_coverage(
                conn,
                ticker.symbol,
                source=self.source,
            )
            covered = bool(
                coverage
                and coverage["status"] == "success"
                and coverage["coverage_start"] <= start_date
                and coverage["coverage_end"] >= end_date
            )
            if covered and not refresh:
                cached = load_backtest_price_bars(
                    conn,
                    ticker.symbol,
                    start_date=start_date,
                    end_date=end_date,
                    source=self.source,
                )
                if cached:
                    bars_by_symbol[ticker.symbol] = cached
                    cache_hits.append(ticker.symbol)
                    continue

            if offline:
                cached = load_backtest_price_bars(
                    conn,
                    ticker.symbol,
                    start_date=start_date,
                    end_date=end_date,
                    source=self.source,
                )
                bars_by_symbol[ticker.symbol] = cached
                if cached:
                    cache_hits.append(ticker.symbol)
                    warnings.append(
                        f"{ticker.symbol}: 離線模式使用部分快取資料（"
                        f"{cached[0].session_date} 至 {cached[-1].session_date}）。"
                    )
                else:
                    unavailable.append(ticker.symbol)
                    warnings.append(f"{ticker.symbol}: 離線模式找不到可用快取資料。")
                continue

            fetch_start = start_date
            fetch_end = end_date
            if coverage and coverage["status"] == "success":
                fetch_start = min(fetch_start, coverage["coverage_start"])
                fetch_end = max(fetch_end, coverage["coverage_end"])
            requests.append((ticker, fetch_start, fetch_end))

        if requests:
            workers = max(1, min(int(max_workers), len(requests)))
            with ThreadPoolExecutor(max_workers=workers) as executor:
                future_map = {
                    executor.submit(
                        self._fetch_one,
                        ticker,
                        fetch_start,
                        fetch_end,
                    ): (ticker, fetch_start, fetch_end)
                    for ticker, fetch_start, fetch_end in requests
                }
                for future in as_completed(future_map):
                    ticker, fetch_start, fetch_end = future_map[future]
                    retrieved_at = datetime.now(timezone.utc)
                    try:
                        fetched_bars = future.result()
                    except Exception as exc:
                        fetched_bars = []
                        error = _compact_error(exc)
                        cached = load_backtest_price_bars(
                            conn,
                            ticker.symbol,
                            start_date=start_date,
                            end_date=end_date,
                            source=self.source,
                        )
                        bars_by_symbol[ticker.symbol] = cached
                        if cached:
                            cache_hits.append(ticker.symbol)
                            warnings.append(
                                f"{ticker.symbol}: 下載失敗，改用最近一次快取資料"
                                f"（{error}）。"
                            )
                        else:
                            unavailable.append(ticker.symbol)
                            warnings.append(
                                f"{ticker.symbol}: 下載失敗且沒有可用快取資料"
                                f"（{error}）。"
                            )
                            save_backtest_price_coverage(
                                conn,
                                ticker=ticker.symbol,
                                market=ticker.market,
                                source=self.source,
                                coverage_start=fetch_start,
                                coverage_end=fetch_end,
                                first_bar_date=None,
                                last_bar_date=None,
                                retrieved_at=retrieved_at,
                                status="error",
                                error=error,
                            )
                        continue

                    if not fetched_bars:
                        cached = load_backtest_price_bars(
                            conn,
                            ticker.symbol,
                            start_date=start_date,
                            end_date=end_date,
                            source=self.source,
                        )
                        bars_by_symbol[ticker.symbol] = cached
                        if cached:
                            cache_hits.append(ticker.symbol)
                            warnings.append(
                                f"{ticker.symbol}: 資料來源回傳空資料，改用最近一次快取。"
                            )
                        else:
                            unavailable.append(ticker.symbol)
                            warnings.append(
                                f"{ticker.symbol}: 資料來源沒有回傳有效的 OHLCV 資料。"
                            )
                            save_backtest_price_coverage(
                                conn,
                                ticker=ticker.symbol,
                                market=ticker.market,
                                source=self.source,
                                coverage_start=fetch_start,
                                coverage_end=fetch_end,
                                first_bar_date=None,
                                last_bar_date=None,
                                retrieved_at=retrieved_at,
                                status="empty",
                                error="provider returned no valid OHLCV rows",
                            )
                        continue

                    save_backtest_price_bars(conn, fetched_bars)
                    save_backtest_price_coverage(
                        conn,
                        ticker=ticker.symbol,
                        market=ticker.market,
                        source=self.source,
                        coverage_start=fetch_start,
                        coverage_end=fetch_end,
                        first_bar_date=fetched_bars[0].session_date,
                        last_bar_date=fetched_bars[-1].session_date,
                        retrieved_at=retrieved_at,
                        status="success",
                    )
                    fetched.append(ticker.symbol)
                    bars_by_symbol[ticker.symbol] = [
                        bar
                        for bar in fetched_bars
                        if start_date <= bar.session_date <= end_date
                    ]

        conn.commit()
        for ticker in ordered:
            bars_by_symbol.setdefault(ticker.symbol, [])
        quality_by_symbol = {
            ticker.symbol: price_history_quality(
                ticker,
                bars_by_symbol[ticker.symbol],
                requested_end=end_date,
            )
            for ticker in ordered
        }
        warnings.extend(_quality_warnings(quality_by_symbol))

        return HistoricalDataBundle(
            bars_by_symbol=bars_by_symbol,
            quality_by_symbol=quality_by_symbol,
            warnings=warnings,
            cache_hits=tuple(sorted(set(cache_hits))),
            fetched_symbols=tuple(sorted(set(fetched))),
            unavailable_symbols=tuple(sorted(set(unavailable))),
        )

    def _fetch_one(
        self,
        ticker: TickerConfig,
        start_date: date,
        end_date: date,
    ) -> list[HistoricalPriceBar]:
        frame = self.history_loader(
            ticker.symbol,
            start_date,
            end_date + timedelta(days=1),
        )
        return normalize_history_frame(
            ticker,
            frame,
            source=self.source,
            retrieved_at=datetime.now(timezone.utc),
        )


def normalize_history_frame(
    ticker: TickerConfig,
    frame: Any,
    *,
    source: str = BACKTEST_DATA_SOURCE,
    retrieved_at: datetime | None = None,
) -> list[HistoricalPriceBar]:
    """Normalize provider rows and reject malformed or impossible candles."""
    if frame is None or not hasattr(frame, "empty") or frame.empty:
        return []
    required = {"Open", "High", "Low", "Close"}
    if not required.issubset(set(frame.columns)):
        return []

    timestamp = retrieved_at or datetime.now(timezone.utc)
    normalized: dict[date, HistoricalPriceBar] = {}
    for index, row in frame.iterrows():
        session_date = _coerce_session_date(index)
        open_price = _finite(row.get("Open"))
        high = _finite(row.get("High"))
        low = _finite(row.get("Low"))
        close = _finite(row.get("Close"))
        volume = _finite(row.get("Volume")) or 0.0
        if session_date is None or None in (open_price, high, low, close):
            continue
        assert open_price is not None and high is not None
        assert low is not None and close is not None
        if min(open_price, high, low, close) <= 0 or volume < 0:
            continue
        if high < max(open_price, close) or low > min(open_price, close):
            continue
        if high < low:
            continue
        normalized[session_date] = HistoricalPriceBar(
            ticker=ticker.symbol,
            market=ticker.market,
            session_date=session_date,
            open=open_price,
            high=high,
            low=low,
            close=close,
            volume=volume,
            source=source,
            retrieved_at=timestamp,
        )
    return [normalized[key] for key in sorted(normalized)]


def bars_to_frame(bars: Iterable[HistoricalPriceBar]) -> pd.DataFrame:
    ordered = sorted(bars, key=lambda bar: bar.session_date)
    if not ordered:
        return pd.DataFrame(columns=["Open", "High", "Low", "Close", "Volume"])
    return pd.DataFrame(
        {
            "Open": [bar.open for bar in ordered],
            "High": [bar.high for bar in ordered],
            "Low": [bar.low for bar in ordered],
            "Close": [bar.close for bar in ordered],
            "Volume": [bar.volume for bar in ordered],
        },
        index=pd.to_datetime([bar.session_date for bar in ordered]),
    )


def price_history_quality(
    ticker: TickerConfig,
    bars: list[HistoricalPriceBar],
    *,
    requested_end: date,
) -> dict[str, Any]:
    """Summarize coverage and suspicious history without changing price rows."""
    ordered = sorted(bars, key=lambda bar: bar.session_date)
    if not ordered:
        return {
            "ticker": ticker.symbol,
            "status": "unavailable",
            "score": 0,
            "sessions": 0,
            "first_date": None,
            "last_date": None,
            "coverage_pct": 0.0,
            "stale_days": None,
            "zero_volume_pct": None,
            "extreme_return_count": 0,
            "reasons": ["unavailable"],
        }

    first_date = ordered[0].session_date
    last_date = ordered[-1].session_date
    frequency = "D" if ticker.market == "crypto" else "B"
    expected_sessions = max(
        1,
        len(pd.date_range(first_date, last_date, freq=frequency)),
    )
    coverage_pct = min(100.0, len(ordered) / expected_sessions * 100.0)
    stale_days = max(0, (requested_end - last_date).days)
    zero_volume_pct = (
        sum(1 for bar in ordered if bar.volume <= 0) / len(ordered) * 100.0
    )
    extreme_return_count = sum(
        1
        for previous, current in zip(ordered, ordered[1:])
        if previous.close > 0
        and abs(current.close / previous.close - 1.0) >= 0.50
    )

    reasons: list[str] = []
    stale_limit = 3 if ticker.market == "crypto" else 7
    if stale_days > stale_limit:
        reasons.append("stale")
    if coverage_pct < 85.0:
        reasons.append("sparse")
    if extreme_return_count:
        reasons.append("extreme_returns")
    if (
        not ticker.symbol.startswith("^")
        and zero_volume_pct > 20.0
    ):
        reasons.append("zero_volume")

    score = 100.0
    if "stale" in reasons:
        score -= 35.0
    if "sparse" in reasons:
        score -= 25.0
    score -= min(25.0, extreme_return_count * 10.0)
    if "zero_volume" in reasons:
        score -= 15.0
    return {
        "ticker": ticker.symbol,
        "status": "warning" if reasons else "ok",
        "score": round(max(0.0, score), 1),
        "sessions": len(ordered),
        "first_date": first_date.isoformat(),
        "last_date": last_date.isoformat(),
        "coverage_pct": round(coverage_pct, 1),
        "stale_days": stale_days,
        "zero_volume_pct": round(zero_volume_pct, 1),
        "extreme_return_count": extreme_return_count,
        "reasons": reasons,
    }


def _quality_warnings(
    quality_by_symbol: dict[str, dict[str, Any]],
) -> list[str]:
    reason_labels = {
        "stale": "最後資料日過舊",
        "sparse": "交易日涵蓋率偏低",
        "extreme_returns": "仍有超過 50% 的單日跳動",
        "zero_volume": "零成交量比例偏高",
    }
    warnings: list[str] = []
    for symbol, quality in sorted(quality_by_symbol.items()):
        reasons = [
            reason_labels[reason]
            for reason in quality.get("reasons", [])
            if reason in reason_labels
        ]
        if reasons:
            warnings.append(
                f"{symbol}: 歷史行情品質需留意（{'、'.join(reasons)}）。"
            )
    return warnings


def _load_yfinance_history(symbol: str, start_date: date, end_date: date) -> Any:
    import yfinance as yf

    return yf.Ticker(symbol).history(
        start=start_date.isoformat(),
        end=end_date.isoformat(),
        interval="1d",
        auto_adjust=True,
        actions=False,
        timeout=20,
        repair=True,
        raise_errors=True,
    )


def _unique_tickers(tickers: Iterable[TickerConfig]) -> list[TickerConfig]:
    result: list[TickerConfig] = []
    seen: set[str] = set()
    for ticker in tickers:
        if ticker.symbol in seen:
            continue
        seen.add(ticker.symbol)
        result.append(ticker)
    return result


def _coerce_session_date(value: object) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return pd.Timestamp(value).date()
    except (TypeError, ValueError, OverflowError):
        return None


def _finite(value: object) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _compact_error(exc: Exception) -> str:
    message = " ".join(str(exc).split())
    return message[:240] or exc.__class__.__name__

