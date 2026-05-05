from __future__ import annotations

import argparse
import shutil
from datetime import date
from pathlib import Path

from .runner import run_daily


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate a personal daily stock research report.")
    parser.add_argument("--config", default="watchlist.yaml", help="Path to watchlist YAML config.")
    parser.add_argument("--date", default=None, help="Report date in YYYY-MM-DD format. Defaults to today.")
    parser.add_argument("--output-dir", default="reports", help="Directory for Markdown reports.")
    parser.add_argument("--db", default="data/stock_daily.sqlite3", help="SQLite database path.")
    parser.add_argument("--init-config", action="store_true", help="Copy watchlist.example.yaml to watchlist.yaml if missing.")
    parser.add_argument("--no-news", action="store_true", help="Skip online news fetching.")
    parser.add_argument("--no-valuation", action="store_true", help="Skip yfinance valuation and earnings fetching.")
    parser.add_argument("--no-macro", action="store_true", help="Skip official macro calendar fetching.")
    parser.add_argument("--notify-telegram", action="store_true", help="Send a Telegram summary after generating the report.")
    args = parser.parse_args()

    if args.init_config:
        init_config(Path(args.config))
        return

    report_date = date.fromisoformat(args.date) if args.date else None
    report = run_daily(
        config_path=args.config,
        report_date=report_date,
        output_dir=args.output_dir,
        db_path=args.db,
        fetch_news=not args.no_news,
        fetch_valuation=not args.no_valuation,
        fetch_macro=not args.no_macro,
        notify_telegram=args.notify_telegram,
    )
    print(f"Generated report for {report.report_date.isoformat()} in {args.output_dir}")


def init_config(config_path: Path) -> None:
    if config_path.exists():
        print(f"{config_path} already exists")
        return
    example = Path("watchlist.example.yaml")
    if not example.exists():
        raise SystemExit(
            f"Could not find {example}. Run --init-config from the project root, "
            f"or copy watchlist.example.yaml to {config_path} manually."
        )
    shutil.copyfile(example, config_path)
    print(f"Created {config_path} from {example}")
