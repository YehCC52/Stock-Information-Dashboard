from __future__ import annotations

import argparse
import logging
import sys
from datetime import date

from .backtest_runner import run_backtest
from .models import BacktestSettings


def configure_logging() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    logging.basicConfig(
        level=logging.WARNING,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    # Provider failures are normalized into report warnings with ticker context.
    logging.getLogger("yfinance").setLevel(logging.CRITICAL)


def main() -> None:
    configure_logging()
    parser = argparse.ArgumentParser(
        description="Run an auditable right-side trading backtest.",
    )
    parser.add_argument("--config", default="watchlist.yaml")
    parser.add_argument("--start", default=None, help="YYYY-MM-DD; default: three years before end.")
    parser.add_argument("--end", default=None, help="YYYY-MM-DD; default: today.")
    parser.add_argument(
        "--market",
        action="append",
        choices=("all", "us", "taiwan", "twse", "tpex", "crypto"),
        help="Repeat to select markets; default: all.",
    )
    parser.add_argument(
        "--symbols",
        nargs="*",
        default=None,
        help="Optional watchlist symbols, separated by spaces or commas.",
    )
    parser.add_argument("--output-dir", default="reports")
    parser.add_argument("--db", default="data/stock_daily.sqlite3")
    parser.add_argument("--offline", action="store_true", help="Use SQLite price cache only.")
    parser.add_argument("--refresh-data", action="store_true", help="Refresh the requested price range.")
    parser.add_argument("--no-replay-check", action="store_true", help="Skip the second deterministic replay.")
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--risk-per-trade", type=float, default=1.0, help="Percent of current equity.")
    parser.add_argument("--max-positions", type=int, default=8)
    parser.add_argument("--max-position-pct", type=float, default=20.0)
    parser.add_argument("--target-r", type=float, default=2.0)
    parser.add_argument("--max-hold", type=int, default=40, help="Trading sessions.")
    parser.add_argument("--max-signal-risk", type=float, default=8.0)
    parser.add_argument("--max-entry-gap", type=float, default=3.0)
    parser.add_argument("--warmup", type=int, default=260)
    parser.add_argument("--lookback", type=int, default=500)
    parser.add_argument("--out-of-sample", type=float, default=30.0)
    parser.add_argument("--max-volume-participation", type=float, default=5.0)
    parser.add_argument("--walk-forward-folds", type=int, default=5)
    parser.add_argument("--no-sensitivity", action="store_true")
    parser.add_argument("--us-capital", type=float, default=None)
    parser.add_argument("--tw-capital", type=float, default=None)
    parser.add_argument("--crypto-capital", type=float, default=None)
    parser.add_argument("--us-commission-bps", type=float, default=None)
    parser.add_argument("--tw-commission-bps", type=float, default=None)
    parser.add_argument("--crypto-commission-bps", type=float, default=None)
    parser.add_argument("--us-slippage-bps", type=float, default=None)
    parser.add_argument("--tw-slippage-bps", type=float, default=None)
    parser.add_argument("--crypto-slippage-bps", type=float, default=None)
    args = parser.parse_args()

    end_date = date.fromisoformat(args.end) if args.end else date.today()
    start_date = (
        date.fromisoformat(args.start)
        if args.start
        else _years_before(end_date, 3)
    )
    settings = BacktestSettings(
        start_date=start_date,
        end_date=end_date,
        risk_per_trade_pct=args.risk_per_trade,
        max_positions=args.max_positions,
        max_position_pct=args.max_position_pct,
        target_r=args.target_r,
        max_holding_sessions=args.max_hold,
        max_signal_risk_pct=args.max_signal_risk,
        max_entry_gap_pct=args.max_entry_gap,
        warmup_sessions=args.warmup,
        lookback_sessions=args.lookback,
        out_of_sample_pct=args.out_of_sample,
        max_volume_participation_pct=args.max_volume_participation,
        walk_forward_folds=args.walk_forward_folds,
        sensitivity_enabled=not args.no_sensitivity,
    )
    overrides = {
        "us": _overrides(
            args.us_capital,
            args.us_commission_bps,
            args.us_slippage_bps,
        ),
        "taiwan": _overrides(
            args.tw_capital,
            args.tw_commission_bps,
            args.tw_slippage_bps,
        ),
        "crypto": _overrides(
            args.crypto_capital,
            args.crypto_commission_bps,
            args.crypto_slippage_bps,
        ),
    }
    artifacts = run_backtest(
        config_path=args.config,
        settings=settings,
        markets=args.market or ("all",),
        symbols=_symbols(args.symbols),
        output_dir=args.output_dir,
        db_path=args.db,
        offline=args.offline,
        refresh_data=args.refresh_data,
        verify_replay=not args.no_replay_check,
        max_workers=max(1, args.workers),
        assumption_overrides=overrides,
    )
    print("")
    for market in artifacts.result.markets:
        metrics = market.metrics
        strategy_return = metrics.get("total_return_pct")
        benchmark_return = metrics.get("benchmark_return_pct")
        print(
            f"{market.label}: "
            f"{_pct(strategy_return)} vs {market.benchmark_symbol} "
            f"{_pct(benchmark_return)}, "
            f"{metrics.get('trade_count', 0)} trades, "
            f"max drawdown {_pct(metrics.get('max_drawdown_pct'))}"
        )
    print(f"HTML: {artifacts.paths['html']}")
    print(f"Markdown: {artifacts.paths['markdown']}")
    print(f"JSON: {artifacts.paths['json']}")
    if not artifacts.result.deterministic_replay_passed:
        raise SystemExit(2)


def _years_before(anchor: date, years: int) -> date:
    try:
        return anchor.replace(year=anchor.year - years)
    except ValueError:
        return anchor.replace(year=anchor.year - years, day=28)


def _overrides(
    initial_capital: float | None,
    commission_bps: float | None,
    slippage_bps: float | None,
) -> dict[str, float]:
    values = {
        "initial_capital": initial_capital,
        "commission_bps": commission_bps,
        "slippage_bps": slippage_bps,
    }
    return {key: value for key, value in values.items() if value is not None}


def _symbols(values: list[str] | None) -> list[str] | None:
    if not values:
        return None
    return [
        symbol.strip().upper()
        for value in values
        for symbol in value.split(",")
        if symbol.strip()
    ]


def _pct(value: object) -> str:
    if not isinstance(value, (int, float)):
        return "N/A"
    return f"{value:+.2f}%"
