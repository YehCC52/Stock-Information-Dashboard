from __future__ import annotations

import hashlib
import math
from collections import Counter
from bisect import bisect_right
from dataclasses import dataclass, replace
from datetime import date, datetime, timezone
from statistics import fmean, median, pstdev
from typing import Any, Iterable

import pandas as pd

from .backtest_data import bars_to_frame
from .models import (
    BacktestEquityPoint,
    BacktestMarketAssumptions,
    BacktestMarketResult,
    BacktestSettings,
    BacktestSignal,
    BacktestTrade,
    HistoricalPriceBar,
    TickerConfig,
    TickerReport,
    ValuationSnapshot,
)
from .report import (
    RIGHT_SIDE_SCORE_RULE_VERSION,
    relative_strength_profile,
    right_side_check,
    right_side_score,
)
from .valuation import technical_indicators_from_history


BACKTEST_RULE_VERSION = "right-side-backtest-v2"


def default_market_assumptions(
    market: str,
    *,
    initial_capital: float | None = None,
    commission_bps: float | None = None,
    slippage_bps: float | None = None,
) -> BacktestMarketAssumptions:
    """Return explicit, market-separated execution assumptions."""
    if market == "us":
        return BacktestMarketAssumptions(
            key="us",
            label="美股",
            currency="USD",
            initial_capital=100_000.0 if initial_capital is None else initial_capital,
            commission_bps=0.0 if commission_bps is None else commission_bps,
            slippage_bps=5.0 if slippage_bps is None else slippage_bps,
            sell_tax_bps=0.0,
            etf_sell_tax_bps=0.0,
            sessions_per_year=252,
            benchmark_symbol="SPY",
            rs_benchmark_symbols=("SPY", "QQQ"),
        )
    if market == "taiwan":
        return BacktestMarketAssumptions(
            key="taiwan",
            label="台股",
            currency="TWD",
            initial_capital=3_000_000.0 if initial_capital is None else initial_capital,
            commission_bps=14.25 if commission_bps is None else commission_bps,
            slippage_bps=5.0 if slippage_bps is None else slippage_bps,
            sell_tax_bps=30.0,
            etf_sell_tax_bps=10.0,
            sessions_per_year=252,
            benchmark_symbol="0050.TW",
            rs_benchmark_symbols=("^TWII",),
        )
    if market == "crypto":
        return BacktestMarketAssumptions(
            key="crypto",
            label="加密貨幣",
            currency="USD",
            initial_capital=100_000.0 if initial_capital is None else initial_capital,
            commission_bps=10.0 if commission_bps is None else commission_bps,
            slippage_bps=10.0 if slippage_bps is None else slippage_bps,
            sell_tax_bps=0.0,
            etf_sell_tax_bps=0.0,
            sessions_per_year=365,
            benchmark_symbol="BTC-USD",
            rs_benchmark_symbols=("BTC-USD",),
        )
    raise ValueError(f"unsupported backtest market: {market}")


def benchmark_tickers(markets: Iterable[str]) -> list[TickerConfig]:
    result: list[TickerConfig] = []
    seen: set[str] = set()
    for market in markets:
        assumptions = default_market_assumptions(market)
        for symbol in (
            assumptions.benchmark_symbol,
            *assumptions.rs_benchmark_symbols,
        ):
            if symbol in seen:
                continue
            seen.add(symbol)
            source_market = (
                "crypto"
                if symbol.endswith("-USD")
                else (
                    "twse"
                    if symbol == "^TWII" or symbol.endswith(".TW")
                    else ("tpex" if symbol.endswith(".TWO") else "us")
                )
            )
            result.append(
                TickerConfig(
                    symbol=symbol,
                    company_name=f"{symbol} 回測基準",
                    market=source_market,
                    currency="TWD" if source_market in {"twse", "tpex"} else "USD",
                    has_fundamentals=False,
                )
            )
    return result


@dataclass
class _OpenPosition:
    ticker: TickerConfig
    signal: BacktestSignal
    units: float
    entry_date: date
    entry_reference: float
    entry_price: float
    initial_stop: float
    target_price: float
    entry_commission: float
    entry_slippage: float
    holding_sessions: int = 0


@dataclass(frozen=True)
class _SignalGeneration:
    signals: list[BacktestSignal]
    diagnostics: dict[str, Any]

@dataclass(frozen=True)
class _BenchmarkSeries:
    dates: tuple[date, ...]
    values: tuple[dict[str, float], ...]



def run_market_backtest(
    tickers: Iterable[TickerConfig],
    bars_by_symbol: dict[str, list[HistoricalPriceBar]],
    settings: BacktestSettings,
    assumptions: BacktestMarketAssumptions,
    *,
    data_quality_by_symbol: dict[str, dict[str, Any]] | None = None,
) -> BacktestMarketResult:
    """Replay one independent market portfolio without future-data access."""
    market_tickers = sorted(
        (
            ticker
            for ticker in tickers
            if _market_bucket(ticker.market) == assumptions.key
        ),
        key=lambda ticker: ticker.symbol,
    )
    frames = {
        symbol: bars_to_frame(bars)
        for symbol, bars in bars_by_symbol.items()
        if bars
    }
    benchmark_frames = {
        symbol: frames[symbol]
        for symbol in {
            assumptions.benchmark_symbol,
            *assumptions.rs_benchmark_symbols,
        }
        if symbol in frames
    }

    generation = generate_signals(
        market_tickers,
        frames,
        benchmark_frames,
        settings,
    )
    equity_curve, trades, simulation_diagnostics = _simulate_portfolio(
        market_tickers,
        frames,
        generation.signals,
        settings,
        assumptions,
    )
    split_date = (
        _split_date(equity_curve, settings.out_of_sample_pct)
        if equity_curve
        else settings.start_date
    )
    metrics = _performance_metrics(
        equity_curve,
        trades,
        assumptions,
        initial_equity=assumptions.initial_capital,
    )
    in_points = [
        point for point in equity_curve if point.session_date < split_date
    ]
    in_trades = [trade for trade in trades if trade.entry_date < split_date]
    in_metrics = _performance_metrics(
        in_points,
        in_trades,
        assumptions,
        initial_equity=assumptions.initial_capital,
    )
    prior_points = [
        point for point in equity_curve if point.session_date < split_date
    ]
    out_points = [
        point for point in equity_curve if point.session_date >= split_date
    ]
    if prior_points and out_points:
        out_points = [prior_points[-1], *out_points]
    out_trades = [trade for trade in trades if trade.entry_date >= split_date]
    out_initial = (
        prior_points[-1].equity
        if prior_points
        else assumptions.initial_capital
    )
    out_metrics = _performance_metrics(
        out_points,
        out_trades,
        assumptions,
        initial_equity=out_initial,
    )
    data_quality = _market_data_quality(
        market_tickers, data_quality_by_symbol or {}
    )
    robustness = _robustness_analysis(
        market_tickers,
        frames,
        generation.signals,
        equity_curve,
        trades,
        settings,
        assumptions,
    )
    _apply_data_quality_status(robustness, data_quality)
    diagnostics = {
        **generation.diagnostics,
        **simulation_diagnostics,
        "configured_symbols": len(market_tickers),
        "symbols_with_data": sum(
            1 for ticker in market_tickers if ticker.symbol in frames
        ),
        "benchmark_available": assumptions.benchmark_symbol in benchmark_frames,
        "actual_sessions": len(equity_curve),
        "data_quality": data_quality,
    }
    return BacktestMarketResult(
        market=assumptions.key,
        label=assumptions.label,
        currency=assumptions.currency,
        start_date=settings.start_date,
        end_date=settings.end_date,
        split_date=split_date,
        benchmark_symbol=assumptions.benchmark_symbol,
        assumptions=assumptions,
        metrics=metrics,
        in_sample_metrics=in_metrics,
        out_of_sample_metrics=out_metrics,
        diagnostics=diagnostics,
        trades=trades,
        equity_curve=equity_curve,
        robustness=robustness,
        warnings=_market_warnings(assumptions, diagnostics, metrics, robustness),
    )


def generate_signals(
    tickers: Iterable[TickerConfig],
    frames: dict[str, pd.DataFrame],
    benchmark_frames: dict[str, pd.DataFrame],
    settings: BacktestSettings,
) -> _SignalGeneration:
    signals: list[BacktestSignal] = []
    rejection_counts: Counter[str] = Counter()
    setup_counts: Counter[str] = Counter()
    sufficient_symbols = 0
    benchmark_history = _build_benchmark_history(benchmark_frames)

    for ticker in tickers:
        frame = frames.get(ticker.symbol)
        if frame is None or frame.empty or len(frame) < settings.warmup_sessions:
            rejection_counts["insufficient_history"] += 1
            continue
        sufficient_symbols += 1
        previous_qualified = False
        session_dates = [_index_date(value) for value in frame.index]
        for index in range(settings.warmup_sessions - 1, len(frame) - 1):
            signal_date = session_dates[index]
            entry_date = session_dates[index + 1]
            if signal_date is None or entry_date is None:
                previous_qualified = False
                continue
            if signal_date < settings.start_date:
                previous_qualified = False
                continue
            if signal_date > settings.end_date or entry_date > settings.end_date:
                break
            start = max(0, index - settings.lookback_sessions + 1)
            snapshot = frame.iloc[start : index + 1]
            metrics = technical_indicators_from_history(
                snapshot,
                chart_history_limit=60,
            )
            metrics.update(_snapshot_price_metrics(snapshot))
            report_item = _historical_ticker_report(ticker, signal_date, metrics)
            benchmarks = _benchmark_returns_at(benchmark_history, signal_date)
            checklist = right_side_check(report_item, benchmarks=benchmarks)
            if not checklist or not checklist.get("actionable"):
                previous_qualified = False
                rejection_counts["no_actionable_structure"] += 1
                continue

            setup = str(checklist.get("active_pathway", "none"))
            setup_counts[setup] += 1
            levels = _signal_levels(metrics, setup)
            if levels is None:
                previous_qualified = False
                rejection_counts["missing_risk_level"] += 1
                continue
            trigger, entry_reference, stop, risk_pct = levels
            if risk_pct > settings.max_signal_risk_pct:
                previous_qualified = False
                rejection_counts["signal_risk_too_wide"] += 1
                continue

            profile = relative_strength_profile(report_item, benchmarks)
            rs_available = int(profile.get("available_horizons", 0) or 0) > 0
            rs_passed = (
                not rs_available
                or (
                    float(profile.get("average_spread", 0.0)) > 0
                    and int(profile.get("positive_horizons", 0) or 0)
                    >= min(2, int(profile.get("available_horizons", 0) or 0))
                )
            )
            if not rs_passed:
                previous_qualified = False
                rejection_counts["relative_strength"] += 1
                continue

            score_info = right_side_score(report_item, benchmarks) or {}
            score_value = _finite(score_info.get("score"))
            rs_average = (
                _finite(profile.get("average_spread"))
                if rs_available
                else None
            )
            if previous_qualified:
                rejection_counts["duplicate_signal_streak"] += 1
                continue
            previous_qualified = True
            signal_id = _stable_id(
                ticker.symbol,
                signal_date.isoformat(),
                setup,
                f"{trigger:.6f}",
                prefix="sig",
            )
            signals.append(
                BacktestSignal(
                    signal_id=signal_id,
                    ticker=ticker.symbol,
                    company_name=ticker.company_name,
                    market=ticker.market,
                    currency=ticker.currency,
                    signal_date=signal_date,
                    entry_session=entry_date,
                    setup=setup,
                    trigger_price=trigger,
                    entry_reference=entry_reference,
                    stop_price=stop,
                    risk_pct=risk_pct,
                    score=score_value,
                    rs_average=rs_average,
                    rule_version=(
                        f"{BACKTEST_RULE_VERSION}+{RIGHT_SIDE_SCORE_RULE_VERSION}"
                    ),
                )
            )

    signals.sort(
        key=lambda signal: (
            signal.entry_session,
            -(signal.score if signal.score is not None else -1.0),
            -(signal.rs_average if signal.rs_average is not None else -999.0),
            signal.ticker,
        )
    )
    return _SignalGeneration(
        signals=signals,
        diagnostics={
            "qualified_signals": len(signals),
            "sufficient_history_symbols": sufficient_symbols,
            "signal_rejections": dict(sorted(rejection_counts.items())),
            "setup_counts": dict(sorted(setup_counts.items())),
        },
    )

def _simulate_portfolio(
    tickers: list[TickerConfig],
    frames: dict[str, pd.DataFrame],
    signals: list[BacktestSignal],
    settings: BacktestSettings,
    assumptions: BacktestMarketAssumptions,
) -> tuple[list[BacktestEquityPoint], list[BacktestTrade], dict[str, Any]]:
    ticker_map = {ticker.symbol: ticker for ticker in tickers}
    bars_by_date = {
        ticker.symbol: _frame_rows_by_date(frames[ticker.symbol])
        for ticker in tickers
        if ticker.symbol in frames
    }
    master_dates = sorted({
        session_date
        for rows in bars_by_date.values()
        for session_date in rows
        if settings.start_date <= session_date <= settings.end_date
    })
    benchmark_rows = _frame_rows_by_date(
        frames.get(assumptions.benchmark_symbol, pd.DataFrame())
    )
    signals_by_entry: dict[date, list[BacktestSignal]] = {}
    for signal in signals:
        signals_by_entry.setdefault(signal.entry_session, []).append(signal)

    cash = assumptions.initial_capital
    positions: dict[str, _OpenPosition] = {}
    trades: list[BacktestTrade] = []
    equity_curve: list[BacktestEquityPoint] = []
    latest_closes: dict[str, float] = {}
    peak_equity = assumptions.initial_capital
    benchmark_base: float | None = None
    simulation_rejections: Counter[str] = Counter()
    execution_adjustments: Counter[str] = Counter()
    max_concurrent = 0

    for session_date in master_dates:
        prior_closes = dict(latest_closes)
        for symbol, rows in bars_by_date.items():
            row = rows.get(session_date)
            if row is not None:
                latest_closes[symbol] = float(row["Close"])

        # Resolve existing risk before allocating capital to new entries.
        for symbol in sorted(list(positions)):
            position = positions.get(symbol)
            row = bars_by_date.get(symbol, {}).get(session_date)
            if position is None or row is None:
                continue
            position.holding_sessions += 1
            exit_plan = _exit_for_bar(position, row, settings)
            if exit_plan is not None and _is_taiwan_locked_limit_down(
                position.ticker,
                row,
                prior_closes.get(symbol),
            ):
                execution_adjustments["locked_limit_exit_deferred"] += 1
                continue

            if exit_plan is None:
                continue
            exit_reference, exit_reason = exit_plan
            trade, proceeds = _close_position(
                position,
                session_date,
                exit_reference,
                exit_reason,
                assumptions,
            )
            cash += proceeds
            trades.append(trade)
            positions.pop(symbol, None)

        equity_before_entries = _portfolio_equity(
            cash,
            positions,
            latest_closes,
        )
        for signal in signals_by_entry.get(session_date, []):
            if len(positions) >= settings.max_positions:
                simulation_rejections["position_limit"] += 1
                continue
            if signal.ticker in positions:
                simulation_rejections["already_open"] += 1
                continue
            ticker = ticker_map.get(signal.ticker)
            row = bars_by_date.get(signal.ticker, {}).get(session_date)
            if ticker is None or row is None:
                simulation_rejections["missing_entry_bar"] += 1
                continue
            open_price = float(row["Open"])
            if _is_taiwan_locked_limit_bar(
                ticker,
                row,
                prior_closes.get(signal.ticker),
            ):
                simulation_rejections["locked_limit_entry"] += 1
                continue
            gap_pct = (
                (open_price - signal.entry_reference)
                / signal.entry_reference
                * 100.0
            )
            if gap_pct > settings.max_entry_gap_pct:
                simulation_rejections["entry_gap_too_high"] += 1
                continue
            if open_price <= signal.stop_price:
                simulation_rejections["opened_below_stop"] += 1
                continue

            entry_price = _buy_fill(open_price, assumptions.slippage_bps)
            per_unit_risk = entry_price - signal.stop_price
            risk_pct = per_unit_risk / entry_price * 100.0
            if per_unit_risk <= 0 or risk_pct > settings.max_signal_risk_pct:
                simulation_rejections["fill_risk_too_wide"] += 1
                continue

            risk_budget = equity_before_entries * settings.risk_per_trade_pct / 100.0
            position_cap = equity_before_entries * settings.max_position_pct / 100.0
            by_risk = risk_budget / per_unit_risk
            by_position = position_cap / entry_price
            commission_rate = assumptions.commission_bps / 10_000.0
            by_cash = cash / (entry_price * (1.0 + commission_rate))
            max_units_without_volume = min(by_risk, by_position, by_cash)
            day_volume = max(0.0, float(row["Volume"]))
            by_volume = day_volume * settings.max_volume_participation_pct / 100.0
            if by_volume <= 0:
                simulation_rejections["no_entry_liquidity"] += 1
                continue
            if by_volume < max_units_without_volume:
                execution_adjustments["volume_capped_entries"] += 1
            units = _tradable_units(
                min(max_units_without_volume, by_volume),
                ticker.market,
            )
            if units <= 0:
                simulation_rejections["insufficient_cash_or_risk"] += 1
                continue

            entry_notional = entry_price * units
            entry_commission = entry_notional * commission_rate
            cash -= entry_notional + entry_commission
            target = entry_price + settings.target_r * per_unit_risk
            position = _OpenPosition(
                ticker=ticker,
                signal=signal,
                units=units,
                entry_date=session_date,
                entry_reference=open_price,
                entry_price=entry_price,
                initial_stop=signal.stop_price,
                target_price=target,
                entry_commission=entry_commission,
                entry_slippage=max(0.0, entry_price - open_price) * units,
                holding_sessions=1,
            )
            positions[signal.ticker] = position
            max_concurrent = max(max_concurrent, len(positions))

            # OHLC cannot reveal intraday order, so ambiguous bars stop first.
            exit_plan = _exit_for_bar(
                position,
                row,
                settings,
                allow_time_exit=False,
            )
            if exit_plan is not None:
                exit_reference, exit_reason = exit_plan
                trade, proceeds = _close_position(
                    position,
                    session_date,
                    exit_reference,
                    exit_reason,
                    assumptions,
                )
                cash += proceeds
                trades.append(trade)
                positions.pop(signal.ticker, None)

        equity = _portfolio_equity(cash, positions, latest_closes)
        peak_equity = max(peak_equity, equity)
        drawdown = (
            (equity / peak_equity - 1.0) * 100.0 if peak_equity > 0 else 0.0
        )
        market_value = max(0.0, equity - cash)
        benchmark_close = (
            float(benchmark_rows[session_date]["Close"])
            if session_date in benchmark_rows
            else None
        )
        if benchmark_close is not None and benchmark_base is None:
            benchmark_base = benchmark_close
        benchmark_equity = (
            assumptions.initial_capital * benchmark_close / benchmark_base
            if benchmark_close is not None and benchmark_base
            else (
                equity_curve[-1].benchmark_equity
                if equity_curve
                else None
            )
        )
        equity_curve.append(
            BacktestEquityPoint(
                session_date=session_date,
                cash=round(cash, 6),
                equity=round(equity, 6),
                exposure_pct=round(
                    market_value / equity * 100.0 if equity > 0 else 0.0,
                    4,
                ),
                drawdown_pct=round(drawdown, 4),
                benchmark_equity=(
                    round(benchmark_equity, 6)
                    if benchmark_equity is not None
                    else None
                ),
            )
        )

    if positions and master_dates:
        final_date = master_dates[-1]
        for symbol in sorted(list(positions)):
            position = positions[symbol]
            rows = bars_by_date.get(symbol, {})
            available_dates = [value for value in rows if value <= final_date]
            if not available_dates:
                simulation_rejections["unclosed_missing_bar"] += 1
                continue
            exit_date = max(available_dates)
            exit_reference = float(rows[exit_date]["Close"])
            trade, proceeds = _close_position(
                position,
                exit_date,
                exit_reference,
                "period_end",
                assumptions,
            )
            cash += proceeds
            trades.append(trade)
            positions.pop(symbol, None)
        if equity_curve:
            last = equity_curve[-1]
            final_equity = cash
            peak_equity = max(
                assumptions.initial_capital,
                *(point.equity for point in equity_curve[:-1]),
                final_equity,
            )
            equity_curve[-1] = BacktestEquityPoint(
                session_date=last.session_date,
                cash=round(cash, 6),
                equity=round(final_equity, 6),
                exposure_pct=0.0,
                drawdown_pct=round(
                    (final_equity / peak_equity - 1.0) * 100.0,
                    4,
                ),
                benchmark_equity=last.benchmark_equity,
            )

    trades.sort(key=lambda trade: (trade.entry_date, trade.ticker, trade.trade_id))
    return (
        equity_curve,
        trades,
        {
            "executed_trades": len(trades),
            "simulation_rejections": dict(sorted(simulation_rejections.items())),
            "execution_adjustments": dict(sorted(execution_adjustments.items())),
            "max_concurrent_positions": max_concurrent,
        },
    )


def _exit_for_bar(
    position: _OpenPosition,
    row: pd.Series,
    settings: BacktestSettings,
    *,
    allow_time_exit: bool = True,
) -> tuple[float, str] | None:
    open_price = float(row["Open"])
    high = float(row["High"])
    low = float(row["Low"])
    close = float(row["Close"])
    if open_price <= position.initial_stop:
        return open_price, "gap_stop"
    stop_hit = low <= position.initial_stop
    target_hit = high >= position.target_price
    if stop_hit:
        return position.initial_stop, (
            "stop_first_ambiguous" if target_hit else "stop"
        )
    if target_hit:
        return position.target_price, "target"
    if allow_time_exit and position.holding_sessions >= settings.max_holding_sessions:
        return close, "time_exit"
    return None


def _close_position(
    position: _OpenPosition,
    exit_date: date,
    exit_reference: float,
    exit_reason: str,
    assumptions: BacktestMarketAssumptions,
) -> tuple[BacktestTrade, float]:
    exit_price = _sell_fill(exit_reference, assumptions.slippage_bps)
    exit_notional = exit_price * position.units
    exit_commission = exit_notional * assumptions.commission_bps / 10_000.0
    tax_bps = (
        assumptions.etf_sell_tax_bps
        if _is_taiwan_etf(position.ticker)
        else assumptions.sell_tax_bps
    )
    sell_tax = exit_notional * tax_bps / 10_000.0
    gross_pnl = (exit_price - position.entry_price) * position.units
    net_pnl = (
        gross_pnl
        - position.entry_commission
        - exit_commission
        - sell_tax
    )
    capital = position.entry_price * position.units + position.entry_commission
    initial_risk = (
        (position.entry_price - position.initial_stop) * position.units
    )
    exit_slippage = max(0.0, exit_reference - exit_price) * position.units
    slippage_cost = position.entry_slippage + exit_slippage
    explicit_cost = position.entry_commission + exit_commission + sell_tax
    trade_id = _stable_id(
        position.signal.signal_id,
        position.entry_date.isoformat(),
        exit_date.isoformat(),
        prefix="trade",
    )
    trade = BacktestTrade(
        trade_id=trade_id,
        signal_id=position.signal.signal_id,
        ticker=position.ticker.symbol,
        company_name=position.ticker.company_name,
        market=position.ticker.market,
        currency=position.ticker.currency,
        setup=position.signal.setup,
        signal_date=position.signal.signal_date,
        entry_date=position.entry_date,
        exit_date=exit_date,
        entry_reference=round(position.entry_reference, 6),
        entry_price=round(position.entry_price, 6),
        exit_reference=round(exit_reference, 6),
        exit_price=round(exit_price, 6),
        initial_stop=round(position.initial_stop, 6),
        target_price=round(position.target_price, 6),
        units=round(position.units, 8),
        gross_pnl=round(gross_pnl, 6),
        net_pnl=round(net_pnl, 6),
        return_pct=round(net_pnl / capital * 100.0 if capital else 0.0, 4),
        r_multiple=round(net_pnl / initial_risk if initial_risk else 0.0, 4),
        holding_sessions=position.holding_sessions,
        exit_reason=exit_reason,
        entry_commission=round(position.entry_commission, 6),
        exit_commission=round(exit_commission, 6),
        sell_tax=round(sell_tax, 6),
        slippage_cost=round(slippage_cost, 6),
        total_cost=round(explicit_cost + slippage_cost, 6),
        score=position.signal.score,
        rs_average=position.signal.rs_average,
    )
    proceeds = exit_notional - exit_commission - sell_tax
    return trade, proceeds

def _performance_metrics(
    points: list[BacktestEquityPoint],
    trades: list[BacktestTrade],
    assumptions: BacktestMarketAssumptions,
    *,
    initial_equity: float,
) -> dict[str, Any]:
    ending_equity = points[-1].equity if points else initial_equity
    total_return = (
        (ending_equity / initial_equity - 1.0) * 100.0
        if initial_equity > 0
        else None
    )
    benchmark_values = [
        point.benchmark_equity
        for point in points
        if point.benchmark_equity is not None
    ]
    benchmark_return = (
        (benchmark_values[-1] / benchmark_values[0] - 1.0) * 100.0
        if len(benchmark_values) >= 2 and benchmark_values[0]
        else None
    )
    values = [initial_equity, *(point.equity for point in points)]
    returns = [
        values[index] / values[index - 1] - 1.0
        for index in range(1, len(values))
        if values[index - 1] > 0
    ]
    peak = values[0] if values else initial_equity
    max_drawdown = 0.0
    for value in values:
        peak = max(peak, value)
        if peak > 0:
            max_drawdown = min(max_drawdown, value / peak - 1.0)
    periods = max(0, len(points) - 1)
    cagr = (
        (
            (ending_equity / initial_equity)
            ** (assumptions.sessions_per_year / periods)
            - 1.0
        )
        * 100.0
        if periods > 0 and initial_equity > 0 and ending_equity > 0
        else None
    )
    volatility = (
        pstdev(returns) * math.sqrt(assumptions.sessions_per_year) * 100.0
        if len(returns) >= 2
        else None
    )
    return_std = pstdev(returns) if len(returns) >= 2 else 0.0
    sharpe = (
        fmean(returns) / return_std * math.sqrt(assumptions.sessions_per_year)
        if return_std > 0
        else None
    )
    wins = [trade.net_pnl for trade in trades if trade.net_pnl > 0]
    losses = [trade.net_pnl for trade in trades if trade.net_pnl < 0]
    profit_factor = sum(wins) / abs(sum(losses)) if losses else None
    return {
        "initial_equity": round(initial_equity, 2),
        "ending_equity": round(ending_equity, 2),
        "net_pnl": round(sum(trade.net_pnl for trade in trades), 2),
        "total_return_pct": _round_optional(total_return),
        "benchmark_return_pct": _round_optional(benchmark_return),
        "excess_return_pct": _round_optional(
            total_return - benchmark_return
            if total_return is not None and benchmark_return is not None
            else None
        ),
        "cagr_pct": _round_optional(cagr),
        "max_drawdown_pct": round(max_drawdown * 100.0, 2),
        "annual_volatility_pct": _round_optional(volatility),
        "sharpe": _round_optional(sharpe),
        "trade_count": len(trades),
        "win_rate_pct": round(
            len(wins) / len(trades) * 100.0 if trades else 0.0,
            2,
        ),
        "expectancy_r": round(
            fmean(trade.r_multiple for trade in trades) if trades else 0.0,
            3,
        ),
        "profit_factor": _round_optional(profit_factor),
        "average_holding_sessions": round(
            fmean(trade.holding_sessions for trade in trades)
            if trades
            else 0.0,
            2,
        ),
        "total_cost": round(sum(trade.total_cost for trade in trades), 2),
        "average_exposure_pct": round(
            fmean(point.exposure_pct for point in points) if points else 0.0,
            2,
        ),
    }


def _robustness_analysis(
    tickers: list[TickerConfig],
    frames: dict[str, pd.DataFrame],
    signals: list[BacktestSignal],
    equity_curve: list[BacktestEquityPoint],
    trades: list[BacktestTrade],
    settings: BacktestSettings,
    assumptions: BacktestMarketAssumptions,
) -> dict[str, Any]:
    walk_forward = _walk_forward_validation(
        equity_curve,
        trades,
        assumptions,
        settings.walk_forward_folds,
    )
    sensitivity = (
        _parameter_sensitivity(
            tickers,
            frames,
            signals,
            equity_curve,
            trades,
            settings,
            assumptions,
        )
        if settings.sensitivity_enabled
        else {
            "summary": {
                "status": "disabled",
                "scenario_count": 0,
            },
            "rows": [],
        }
    )
    concentration = _trade_concentration(trades)
    statuses = {
        walk_forward["summary"].get("status"),
        sensitivity["summary"].get("status"),
        concentration.get("status"),
    }
    if "insufficient" in statuses:
        overall_status = "insufficient"
    elif "sensitive" in statuses or "concentrated" in statuses:
        overall_status = "fragile"
    elif statuses <= {"stable", "diversified"}:
        overall_status = "stable"
    else:
        overall_status = "mixed"
    return {
        "status": overall_status,
        "walk_forward": walk_forward,
        "sensitivity": sensitivity,
        "concentration": concentration,
    }


def _walk_forward_validation(
    points: list[BacktestEquityPoint],
    trades: list[BacktestTrade],
    assumptions: BacktestMarketAssumptions,
    requested_folds: int,
) -> dict[str, Any]:
    validation_start_index = max(1, len(points) // 2)
    available_sessions = max(0, len(points) - validation_start_index)
    fold_count = min(requested_folds, available_sessions // 20)
    if fold_count < 2:
        return {
            "summary": {
                "status": "insufficient",
                "requested_folds": requested_folds,
                "completed_folds": 0,
                "trade_count": 0,
            },
            "rows": [],
        }

    rows: list[dict[str, Any]] = []
    for fold_index in range(fold_count):
        start_index = validation_start_index + (
            fold_index * available_sessions // fold_count
        )
        end_index = (
            validation_start_index
            + ((fold_index + 1) * available_sessions // fold_count)
            - 1
        )
        if end_index < start_index:
            continue
        previous = points[start_index - 1]
        validation_points = [
            previous,
            *points[start_index : end_index + 1],
        ]
        validation_start = points[start_index].session_date
        validation_end = points[end_index].session_date
        validation_trades = [
            trade
            for trade in trades
            if validation_start <= trade.entry_date <= validation_end
        ]
        metrics = _performance_metrics(
            validation_points,
            validation_trades,
            assumptions,
            initial_equity=previous.equity,
        )
        rows.append(
            {
                "fold": fold_index + 1,
                "training_end": previous.session_date,
                "validation_start": validation_start,
                "validation_end": validation_end,
                "total_return_pct": metrics["total_return_pct"],
                "benchmark_return_pct": metrics["benchmark_return_pct"],
                "excess_return_pct": metrics["excess_return_pct"],
                "max_drawdown_pct": metrics["max_drawdown_pct"],
                "trade_count": metrics["trade_count"],
                "expectancy_r": metrics["expectancy_r"],
                "sharpe": metrics["sharpe"],
            }
        )

    returns = [
        float(row["total_return_pct"])
        for row in rows
        if row["total_return_pct"] is not None
    ]
    expectancy = [float(row["expectancy_r"]) for row in rows]
    comparable = [
        row
        for row in rows
        if row["excess_return_pct"] is not None
    ]
    trade_count = sum(int(row["trade_count"]) for row in rows)
    positive_fold_pct = (
        sum(value > 0 for value in returns) / len(returns) * 100.0
        if returns
        else 0.0
    )
    benchmark_beaten_pct = (
        sum(float(row["excess_return_pct"]) > 0 for row in comparable)
        / len(comparable)
        * 100.0
        if comparable
        else None
    )
    median_expectancy = median(expectancy) if expectancy else 0.0
    if len(rows) < 3 or trade_count < 30:
        status = "insufficient"
    elif (
        positive_fold_pct >= 60.0
        and (benchmark_beaten_pct is None or benchmark_beaten_pct >= 50.0)
        and median_expectancy > 0
    ):
        status = "stable"
    else:
        status = "mixed"
    return {
        "summary": {
            "status": status,
            "requested_folds": requested_folds,
            "completed_folds": len(rows),
            "trade_count": trade_count,
            "positive_fold_pct": round(positive_fold_pct, 1),
            "benchmark_beaten_pct": _round_optional(benchmark_beaten_pct, 1),
            "median_return_pct": round(median(returns), 2) if returns else None,
            "worst_return_pct": round(min(returns), 2) if returns else None,
            "median_expectancy_r": round(median_expectancy, 3),
        },
        "rows": rows,
    }


def _parameter_sensitivity(
    tickers: list[TickerConfig],
    frames: dict[str, pd.DataFrame],
    signals: list[BacktestSignal],
    baseline_curve: list[BacktestEquityPoint],
    baseline_trades: list[BacktestTrade],
    settings: BacktestSettings,
    assumptions: BacktestMarketAssumptions,
) -> dict[str, Any]:
    target_values = sorted({
        round(max(0.5, settings.target_r - 0.5), 2),
        round(settings.target_r, 2),
        round(settings.target_r + 0.5, 2),
    })
    holding_values = sorted({
        max(5, settings.max_holding_sessions // 2),
        settings.max_holding_sessions,
        max(5, round(settings.max_holding_sessions * 1.5)),
    })
    rows: list[dict[str, Any]] = []
    for target_r in target_values:
        for max_holding_sessions in holding_values:
            is_baseline = (
                math.isclose(target_r, settings.target_r)
                and max_holding_sessions == settings.max_holding_sessions
            )
            if is_baseline:
                curve = baseline_curve
                scenario_trades = baseline_trades
            else:
                scenario_settings = replace(
                    settings,
                    target_r=target_r,
                    max_holding_sessions=max_holding_sessions,
                    sensitivity_enabled=False,
                )
                curve, scenario_trades, _diagnostics = _simulate_portfolio(
                    tickers,
                    frames,
                    signals,
                    scenario_settings,
                    assumptions,
                )
            metrics = _performance_metrics(
                curve,
                scenario_trades,
                assumptions,
                initial_equity=assumptions.initial_capital,
            )
            rows.append(
                {
                    "target_r": target_r,
                    "max_holding_sessions": max_holding_sessions,
                    "is_baseline": is_baseline,
                    "total_return_pct": metrics["total_return_pct"],
                    "max_drawdown_pct": metrics["max_drawdown_pct"],
                    "trade_count": metrics["trade_count"],
                    "expectancy_r": metrics["expectancy_r"],
                    "profit_factor": metrics["profit_factor"],
                    "sharpe": metrics["sharpe"],
                }
            )

    returns = [
        float(row["total_return_pct"])
        for row in rows
        if row["total_return_pct"] is not None
    ]
    expectations = [float(row["expectancy_r"]) for row in rows]
    positive_return_pct = (
        sum(value > 0 for value in returns) / len(returns) * 100.0
        if returns
        else 0.0
    )
    positive_expectancy_pct = (
        sum(value > 0 for value in expectations) / len(expectations) * 100.0
        if expectations
        else 0.0
    )
    baseline_trade_count = len(baseline_trades)
    if baseline_trade_count < 30:
        status = "insufficient"
    elif positive_return_pct >= 66.0 and positive_expectancy_pct >= 66.0:
        status = "stable"
    elif positive_return_pct <= 33.0 or positive_expectancy_pct <= 33.0:
        status = "sensitive"
    else:
        status = "mixed"
    return {
        "summary": {
            "status": status,
            "scenario_count": len(rows),
            "positive_return_pct": round(positive_return_pct, 1),
            "positive_expectancy_pct": round(positive_expectancy_pct, 1),
            "median_return_pct": round(median(returns), 2) if returns else None,
            "worst_return_pct": round(min(returns), 2) if returns else None,
            "best_return_pct": round(max(returns), 2) if returns else None,
            "baseline_trade_count": baseline_trade_count,
        },
        "rows": rows,
    }


def _trade_concentration(
    trades: list[BacktestTrade],
) -> dict[str, Any]:
    winning_pnl = sorted(
        (trade.net_pnl for trade in trades if trade.net_pnl > 0),
        reverse=True,
    )
    gross_profit = sum(winning_pnl)
    top_five_share = (
        sum(winning_pnl[:5]) / gross_profit * 100.0
        if gross_profit > 0
        else None
    )
    profit_by_ticker: dict[str, float] = {}
    for trade in trades:
        if trade.net_pnl > 0:
            profit_by_ticker[trade.ticker] = (
                profit_by_ticker.get(trade.ticker, 0.0) + trade.net_pnl
            )
    largest_ticker_share = (
        max(profit_by_ticker.values()) / gross_profit * 100.0
        if profit_by_ticker and gross_profit > 0
        else None
    )
    if len(trades) < 30:
        status = "insufficient"
    elif (
        (top_five_share is not None and top_five_share > 70.0)
        or (
            largest_ticker_share is not None
            and largest_ticker_share > 40.0
        )
    ):
        status = "concentrated"
    else:
        status = "diversified"
    return {
        "status": status,
        "trade_count": len(trades),
        "top_five_profit_share_pct": _round_optional(top_five_share, 1),
        "largest_ticker_profit_share_pct": _round_optional(
            largest_ticker_share,
            1,
        ),
    }


def _market_data_quality(
    tickers: list[TickerConfig],
    quality_by_symbol: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    rows = [
        quality_by_symbol[ticker.symbol]
        for ticker in tickers
        if ticker.symbol in quality_by_symbol
    ]
    scores = [
        float(row["score"])
        for row in rows
        if row.get("status") != "unavailable"
    ]
    coverage = [
        float(row["coverage_pct"])
        for row in rows
        if row.get("status") != "unavailable"
    ]
    return {
        "rows": rows,
        "symbol_count": len(rows),
        "warning_count": sum(
            row.get("status") == "warning" for row in rows
        ),
        "unavailable_count": sum(
            row.get("status") == "unavailable" for row in rows
        ),
        "median_score": round(median(scores), 1) if scores else None,
        "minimum_coverage_pct": round(min(coverage), 1) if coverage else None,
    }

def _apply_data_quality_status(
    robustness: dict[str, Any],
    data_quality: dict[str, Any],
) -> None:
    unavailable = int(data_quality.get("unavailable_count", 0))
    warnings = int(data_quality.get("warning_count", 0))
    median_score = data_quality.get("median_score")
    if unavailable:
        robustness["status"] = "insufficient"
        return
    if not warnings:
        return
    if isinstance(median_score, (int, float)) and median_score < 50:
        robustness["status"] = "fragile"
        return
    if robustness.get("status") == "stable":
        robustness["status"] = "mixed"


def _snapshot_price_metrics(frame: pd.DataFrame) -> dict[str, Any]:
    closes = [float(value) for value in frame["Close"].dropna().tolist()]
    highs = [float(value) for value in frame["High"].dropna().tolist()]
    lows = [float(value) for value in frame["Low"].dropna().tolist()]
    return {
        "last_close": closes[-1] if closes else None,
        "previous_close": closes[-2] if len(closes) >= 2 else None,
        "fifty_two_week_high": max(highs[-252:]) if highs else None,
        "fifty_two_week_low": min(lows[-252:]) if lows else None,
    }


def _historical_ticker_report(
    ticker: TickerConfig,
    as_of_date: date,
    metrics: dict[str, Any],
) -> TickerReport:
    snapshot = ValuationSnapshot(
        ticker=ticker.symbol,
        as_of_date=as_of_date,
        source="yfinance-adjusted-history",
        metrics=metrics,
        retrieved_at=datetime.combine(
            as_of_date,
            datetime.min.time(),
            tzinfo=timezone.utc,
        ),
    )
    return TickerReport(ticker, [], [], snapshot, None)


def _signal_levels(
    metrics: dict[str, Any],
    setup: str,
) -> tuple[float, float, float, float] | None:
    last = _finite(metrics.get("last_close"))
    pivot = _finite(metrics.get("breakout_pivot"))
    prior_high = _finite(metrics.get("prior_20d_high"))
    prior_low = _finite(metrics.get("prior_20d_low"))
    sma20 = _finite(metrics.get("sma_20"))
    atr = _finite(metrics.get("atr_20"))
    if last is None or last <= 0:
        return None
    if setup == "pullback":
        trigger = max(last, sma20) if sma20 is not None else last
    elif setup == "breakout":
        trigger = pivot or prior_high
    else:
        return None
    if trigger is None or trigger <= 0:
        return None
    entry_reference = max(last, trigger)
    candidates = [
        prior_low,
        last - 2.0 * atr if atr is not None else None,
    ]
    if setup == "breakout" and pivot is not None:
        candidates.append(
            pivot - 0.5 * atr if atr is not None else pivot * 0.99
        )
    if setup == "pullback" and sma20 is not None:
        candidates.append(
            sma20 - atr if atr is not None else sma20 * 0.97
        )
    stops = [
        value
        for value in candidates
        if value is not None and 0 < value < entry_reference
    ]
    if not stops:
        return None
    stop = max(stops)
    risk_pct = (entry_reference - stop) / entry_reference * 100.0
    if risk_pct <= 0:
        return None
    return trigger, entry_reference, stop, risk_pct


def _benchmark_returns_reference(
    frames: dict[str, pd.DataFrame],
    as_of_date: date,
) -> dict[str, float]:
    """Straightforward reference path retained to verify the cached fast path."""
    result: dict[str, float] = {}
    for symbol, frame in frames.items():
        mask = [
            (_index_date(value) or date.min) <= as_of_date
            for value in frame.index
        ]
        closes = [
            float(value)
            for value in frame.loc[mask, "Close"].dropna().tolist()
        ]
        key = _benchmark_key(symbol)
        for horizon in (20, 60, 120):
            if len(closes) <= horizon or closes[-(horizon + 1)] == 0:
                continue
            result[f"{key}_{horizon}d"] = round(
                (closes[-1] / closes[-(horizon + 1)] - 1.0) * 100.0,
                4,
            )
    return result


def _build_benchmark_history(
    frames: dict[str, pd.DataFrame],
) -> dict[str, _BenchmarkSeries]:
    history: dict[str, _BenchmarkSeries] = {}
    for symbol, frame in frames.items():
        dates: list[date] = []
        closes: list[float] = []
        for index, close_value in frame["Close"].items():
            session_date = _index_date(index)
            close = _finite(close_value)
            if session_date is None or close is None or close <= 0:
                continue
            dates.append(session_date)
            closes.append(close)
        key = _benchmark_key(symbol)
        snapshots: list[dict[str, float]] = []
        for index, close in enumerate(closes):
            values: dict[str, float] = {}
            for horizon in (20, 60, 120):
                if index < horizon or closes[index - horizon] == 0:
                    continue
                values[f"{key}_{horizon}d"] = round(
                    (close / closes[index - horizon] - 1.0) * 100.0,
                    4,
                )
            snapshots.append(values)
        history[symbol] = _BenchmarkSeries(
            dates=tuple(dates),
            values=tuple(snapshots),
        )
    return history


def _benchmark_returns_at(
    history: dict[str, _BenchmarkSeries],
    as_of_date: date,
) -> dict[str, float]:
    result: dict[str, float] = {}
    for series in history.values():
        index = bisect_right(series.dates, as_of_date) - 1
        if index >= 0:
            result.update(series.values[index])
    return result


def _frame_rows_by_date(frame: pd.DataFrame) -> dict[date, pd.Series]:
    if frame is None or frame.empty:
        return {}
    result: dict[date, pd.Series] = {}
    for index, row in frame.iterrows():
        session_date = _index_date(index)
        if session_date is not None:
            result[session_date] = row
    return result


def _portfolio_equity(
    cash: float,
    positions: dict[str, _OpenPosition],
    latest_closes: dict[str, float],
) -> float:
    return cash + sum(
        position.units * latest_closes.get(symbol, position.entry_price)
        for symbol, position in positions.items()
    )


def _buy_fill(reference: float, slippage_bps: float) -> float:
    return reference * (1.0 + slippage_bps / 10_000.0)


def _sell_fill(reference: float, slippage_bps: float) -> float:
    return max(0.0, reference * (1.0 - slippage_bps / 10_000.0))


def _tradable_units(raw_units: float, market: str) -> float:
    if not math.isfinite(raw_units) or raw_units <= 0:
        return 0.0
    if market == "crypto":
        return math.floor(raw_units * 100_000_000) / 100_000_000
    return float(math.floor(raw_units))


def _is_taiwan_etf(ticker: TickerConfig) -> bool:
    return ticker.market in {"twse", "tpex"} and not ticker.has_fundamentals

def _is_taiwan_locked_limit_bar(
    ticker: TickerConfig,
    row: pd.Series,
    previous_close: float | None,
) -> bool:
    if (
        ticker.market not in {"twse", "tpex"}
        or previous_close is None
        or previous_close <= 0
    ):
        return False
    prices = [
        float(row["Open"]),
        float(row["High"]),
        float(row["Low"]),
        float(row["Close"]),
    ]
    if not math.isclose(
        max(prices),
        min(prices),
        rel_tol=1e-8,
        abs_tol=1e-8,
    ):
        return False
    change_pct = (prices[-1] / previous_close - 1.0) * 100.0
    return abs(change_pct) >= 9.4


def _is_taiwan_locked_limit_down(
    ticker: TickerConfig,
    row: pd.Series,
    previous_close: float | None,
) -> bool:
    return (
        _is_taiwan_locked_limit_bar(ticker, row, previous_close)
        and previous_close is not None
        and float(row["Close"]) < previous_close
    )



def _split_date(
    points: list[BacktestEquityPoint],
    out_of_sample_pct: float,
) -> date:
    if not points:
        return date.max
    in_sample_fraction = 1.0 - out_of_sample_pct / 100.0
    index = min(
        len(points) - 1,
        max(1, int(len(points) * in_sample_fraction)),
    )
    return points[index].session_date


def _market_warnings(
    assumptions: BacktestMarketAssumptions,
    diagnostics: dict[str, Any],
    metrics: dict[str, Any],
    robustness: dict[str, Any],
) -> list[str]:
    warnings = [
        "回測只使用截至訊號日可取得的日線 OHLCV，避免未來資料污染。",
        "歷史新聞、分析師預估與基本面未納入訊號，"
        "因免費來源無法保證逐日時間點資料。",
    ]
    if not diagnostics.get("benchmark_available"):
        warnings.append(
            f"{assumptions.benchmark_symbol} 基準資料不足，無法計算完整超額報酬。"
        )
    if int(diagnostics.get("symbols_with_data", 0)) == 0:
        warnings.append("此市場沒有足夠的有效歷史資料。")
    if int(metrics.get("trade_count", 0)) < 30:
        warnings.append("交易樣本少於 30 筆，統計結果僅供初步參考。")
    data_quality = diagnostics.get("data_quality", {})
    warning_count = int(data_quality.get("warning_count", 0))
    unavailable_count = int(data_quality.get("unavailable_count", 0))
    if warning_count or unavailable_count:
        warnings.append(
            f"行情品質檢查：{warning_count} 檔需留意、"
            f"{unavailable_count} 檔無可用資料；請展開穩健度明細確認。"
        )
    walk_forward = robustness.get("walk_forward", {}).get("summary", {})
    if walk_forward.get("status") == "insufficient":
        warnings.append("滾動樣本外交易數不足，尚不能據此確認策略穩定性。")
    elif walk_forward.get("status") == "mixed":
        warnings.append("滾動樣本外結果不一致，策略表現可能受市場階段影響。")
    sensitivity = robustness.get("sensitivity", {}).get("summary", {})
    if sensitivity.get("status") == "sensitive":
        warnings.append("鄰近參數結果敏感，基準績效可能依賴特定參數。")
    concentration = robustness.get("concentration", {})
    if concentration.get("status") == "concentrated":
        warnings.append("獲利集中於少數交易或標的，整體報酬的可重複性較弱。")
    if assumptions.key == "taiwan":
        warnings.append(
            "台股績效基準使用可投資的調整後 0050.TW；"
            "^TWII 僅用於訊號的相對強弱判斷。"
        )
    return warnings


def _market_bucket(market: str) -> str:
    if market in {"twse", "tpex", "taiwan"}:
        return "taiwan"
    if market == "crypto":
        return "crypto"
    return "us" if market == "us" else "other"


def _benchmark_key(symbol: str) -> str:
    return {
        "SPY": "spy",
        "QQQ": "qqq",
        "^TWII": "twii",
        "BTC-USD": "btc",
    }.get(
        symbol.upper(),
        symbol.lower().replace("^", "").replace("-", "_"),
    )


def _index_date(value: object) -> date | None:
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


def _round_optional(value: float | None, digits: int = 2) -> float | None:
    if value is None or not math.isfinite(value):
        return None
    return round(value, digits)


def _stable_id(*parts: str, prefix: str) -> str:
    digest = hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:16]
    return f"{prefix}-{digest}"

