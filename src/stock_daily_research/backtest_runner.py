from __future__ import annotations

import hashlib
import json
from contextlib import closing
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Iterable
from zoneinfo import ZoneInfo

from .backtest import (
    BACKTEST_RULE_VERSION,
    benchmark_tickers,
    default_market_assumptions,
    run_market_backtest,
)
from .backtest_data import HistoricalDataBundle, HistoricalPriceProvider
from .backtest_report import (
    backtest_summary_payload,
    write_backtest_report,
)
from .config import load_config
from .models import (
    BacktestMarketAssumptions,
    BacktestMarketResult,
    BacktestResult,
    BacktestSettings,
    BacktestUniverseMember,
    HistoricalPriceBar,
    TickerConfig,
)
from .storage import init_db, save_backtest_result


SUPPORTED_BACKTEST_MARKETS = ("us", "taiwan", "crypto")


@dataclass(frozen=True)
class BacktestRunArtifacts:
    result: BacktestResult
    paths: dict[str, Path]
    data: HistoricalDataBundle


def run_backtest(
    *,
    config_path: str | Path = "watchlist.yaml",
    settings: BacktestSettings,
    markets: Iterable[str] = SUPPORTED_BACKTEST_MARKETS,
    symbols: Iterable[str] | None = None,
    output_dir: str | Path = "reports",
    db_path: str | Path = "data/stock_daily.sqlite3",
    offline: bool = False,
    refresh_data: bool = False,
    verify_replay: bool = True,
    max_workers: int = 6,
    assumption_overrides: dict[str, dict[str, float]] | None = None,
    provider: HistoricalPriceProvider | None = None,
    generated_at: datetime | None = None,
    progress: bool = True,
) -> BacktestRunArtifacts:
    """Fetch, replay, verify, render, and persist an auditable backtest."""
    config = load_config(config_path)
    zone = ZoneInfo(config.settings.report_timezone)
    generated = generated_at or datetime.now(zone)
    selected_markets = _normalize_markets(markets)
    selected_tickers = _select_tickers(
        config.tickers,
        selected_markets,
        symbols,
    )
    assumptions = [
        _assumptions_for(
            market,
            (assumption_overrides or {}).get(market, {}),
        )
        for market in selected_markets
    ]
    history_tickers = _unique_tickers(
        [*selected_tickers, *benchmark_tickers(selected_markets)]
    )
    history_start = _history_start(settings)
    price_provider = provider or HistoricalPriceProvider()

    if progress:
        print(
            "Backtest data: "
            f"{len(history_tickers)} symbols, "
            f"{history_start} to {settings.end_date}"
        )
    with closing(init_db(db_path)) as conn:
        data = price_provider.load(
            conn,
            history_tickers,
            start_date=history_start,
            end_date=settings.end_date,
            offline=offline,
            refresh=refresh_data,
            max_workers=max_workers,
        )
        if progress:
            print(
                "Backtest replay: "
                f"{len(data.fetched_symbols)} fetched, "
                f"{len(data.cache_hits)} cached, "
                f"{len(data.unavailable_symbols)} unavailable"
            )

        market_results = _replay_markets(
            selected_tickers,
            data.bars_by_symbol,
            settings,
            assumptions,
            data_quality_by_symbol=data.quality_by_symbol,
            progress=progress,
        )
        first_fingerprint = _fingerprint(
            [asdict(item) for item in market_results]
        )
        deterministic = True
        if verify_replay:
            replay = _replay_markets(
                selected_tickers,
                data.bars_by_symbol,
                settings,
                assumptions,
                data_quality_by_symbol=data.quality_by_symbol,
                progress=False,
            )
            deterministic = first_fingerprint == _fingerprint(
                [asdict(item) for item in replay]
            )

        config_hash = _fingerprint(
            {
                "rule_version": BACKTEST_RULE_VERSION,
                "tickers": [
                    {
                        "symbol": ticker.symbol,
                        "company_name": ticker.company_name,
                        "market": ticker.market,
                        "currency": ticker.currency,
                        "has_fundamentals": ticker.has_fundamentals,
                    }
                    for ticker in selected_tickers
                ],
                "settings": asdict(settings),
                "assumptions": [asdict(item) for item in assumptions],
            }
        )
        data_fingerprint = _price_data_fingerprint(
            data.bars_by_symbol,
            history_tickers,
        )
        result_fingerprint = _fingerprint(
            {
                "rule_version": BACKTEST_RULE_VERSION,
                "markets": [asdict(item) for item in market_results],
            }
        )
        run_id = "bt-" + _fingerprint(
            {
                "config": config_hash,
                "data": data_fingerprint,
                "result": result_fingerprint,
            }
        )[:20]
        universe = [
            BacktestUniverseMember(
                ticker=ticker.symbol,
                company_name=ticker.company_name,
                market=ticker.market,
                currency=ticker.currency,
                has_fundamentals=ticker.has_fundamentals,
            )
            for ticker in selected_tickers
        ]
        warnings = [
            "yfinance 為非官方個人用途資料來源；歷史價格已使用 SQLite "
            "快取、價格修復與最近一次有效資料備援。",
            "各市場採獨立資金與幣別計算，不會合併 USD 與 TWD 績效。",
            "本次使用執行當下的觀察名單，未包含歷史已移除或下市標的，"
            "仍有選樣與存續者偏誤。",
            *data.warnings,
        ]
        if not deterministic:
            warnings.append(
                "相同輸入重播結果不一致，請勿用於策略判斷。"
            )
        result = BacktestResult(
            run_id=run_id,
            generated_at=generated,
            strategy="右側交易技術面回測",
            rule_version=BACKTEST_RULE_VERSION,
            requested_start=settings.start_date,
            requested_end=settings.end_date,
            data_source="yfinance repaired history + SQLite last-known-good cache",
            price_basis="repaired adjusted daily OHLCV",
            config_hash=config_hash,
            data_fingerprint=data_fingerprint,
            result_fingerprint=result_fingerprint,
            deterministic_replay_passed=deterministic,
            settings=settings,
            markets=market_results,
            universe_source="current_watchlist",
            universe=universe,
            warnings=warnings,
        )
        paths = write_backtest_report(result, output_dir)
        save_backtest_result(
            conn,
            result,
            summary_payload=backtest_summary_payload(result),
            html_path=paths["html"],
            markdown_path=paths["markdown"],
            json_path=paths["json"],
        )
        conn.commit()

    if progress:
        print(
            "Backtest verification: "
            + ("deterministic replay passed" if deterministic else "FAILED")
        )
    return BacktestRunArtifacts(result=result, paths=paths, data=data)


def _replay_markets(
    tickers: list[TickerConfig],
    bars_by_symbol: dict[str, list[HistoricalPriceBar]],
    settings: BacktestSettings,
    assumptions: list[BacktestMarketAssumptions],
    *,
    data_quality_by_symbol: dict[str, dict[str, Any]],
    progress: bool,
) -> list[BacktestMarketResult]:
    results: list[BacktestMarketResult] = []
    for item in assumptions:
        if progress:
            print(f"  Replaying {item.label} ({item.currency})")
        results.append(
            run_market_backtest(
                tickers,
                bars_by_symbol,
                settings,
                item,
                data_quality_by_symbol=data_quality_by_symbol,
            )
        )
    return results


def _normalize_markets(markets: Iterable[str]) -> tuple[str, ...]:
    aliases = {
        "twse": "taiwan",
        "tpex": "taiwan",
        "tw": "taiwan",
        "all": "all",
    }
    requested: list[str] = []
    for value in markets:
        key = aliases.get(str(value).lower(), str(value).lower())
        if key == "all":
            return SUPPORTED_BACKTEST_MARKETS
        if key not in SUPPORTED_BACKTEST_MARKETS:
            raise ValueError(f"unsupported backtest market: {value}")
        if key not in requested:
            requested.append(key)
    if not requested:
        raise ValueError("at least one backtest market is required")
    return tuple(
        market for market in SUPPORTED_BACKTEST_MARKETS if market in requested
    )


def _select_tickers(
    tickers: list[TickerConfig],
    markets: tuple[str, ...],
    symbols: Iterable[str] | None,
) -> list[TickerConfig]:
    requested = {
        str(symbol).strip().upper()
        for symbol in (symbols or [])
        if str(symbol).strip()
    }
    known = {ticker.symbol for ticker in tickers}
    unknown = sorted(requested - known)
    if unknown:
        raise ValueError(
            "symbols are not present in watchlist.yaml: " + ", ".join(unknown)
        )
    selected = [
        ticker
        for ticker in tickers
        if _market_bucket(ticker.market) in markets
        and (not requested or ticker.symbol in requested)
    ]
    if not selected:
        raise ValueError("no watchlist symbols match the backtest selection")
    return selected


def _assumptions_for(
    market: str,
    overrides: dict[str, float],
) -> BacktestMarketAssumptions:
    allowed = {"initial_capital", "commission_bps", "slippage_bps"}
    unknown = sorted(set(overrides) - allowed)
    if unknown:
        raise ValueError(
            f"unsupported {market} assumption overrides: {', '.join(unknown)}"
        )
    for key, value in overrides.items():
        if float(value) < 0:
            raise ValueError(f"{market}.{key} must not be negative")
    if "initial_capital" in overrides and overrides["initial_capital"] <= 0:
        raise ValueError(f"{market}.initial_capital must be positive")
    return default_market_assumptions(
        market,
        initial_capital=overrides.get("initial_capital"),
        commission_bps=overrides.get("commission_bps"),
        slippage_bps=overrides.get("slippage_bps"),
    )


def _history_start(settings: BacktestSettings) -> date:
    calendar_days = max(365, settings.lookback_sessions * 2 + 30)
    earliest = date(1970, 1, 1)
    try:
        return max(earliest, settings.start_date - timedelta(days=calendar_days))
    except OverflowError:
        return earliest


def _price_data_fingerprint(
    bars_by_symbol: dict[str, list[HistoricalPriceBar]],
    tickers: list[TickerConfig],
) -> str:
    symbols = {ticker.symbol for ticker in tickers}
    rows = [
        (
            bar.ticker,
            bar.market,
            bar.session_date.isoformat(),
            round(bar.open, 8),
            round(bar.high, 8),
            round(bar.low, 8),
            round(bar.close, 8),
            round(bar.volume, 4),
            bar.source,
        )
        for symbol in sorted(bars_by_symbol)
        if symbol in symbols
        for bar in bars_by_symbol[symbol]
    ]
    return _fingerprint(rows)


def _fingerprint(payload: object) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        default=_json_default,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _json_default(value: object) -> str:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    raise TypeError(f"Unsupported fingerprint value: {type(value).__name__}")


def _unique_tickers(tickers: Iterable[TickerConfig]) -> list[TickerConfig]:
    result: list[TickerConfig] = []
    seen: set[str] = set()
    for ticker in tickers:
        if ticker.symbol in seen:
            continue
        seen.add(ticker.symbol)
        result.append(ticker)
    return result


def _market_bucket(market: str) -> str:
    if market in {"twse", "tpex", "taiwan"}:
        return "taiwan"
    if market == "crypto":
        return "crypto"
    return "us" if market == "us" else "other"
