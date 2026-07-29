from __future__ import annotations

import argparse
import logging
import shutil
from contextlib import closing
from datetime import date
from pathlib import Path

from .report import report_output_dir
from .runner import run_daily
from .storage import export_research_state_file, import_research_state_file, init_db


class ExpectedYFinanceGapFilter(logging.Filter):
    """Hide Yahoo's false delisting wording for an unavailable earnings calendar."""

    def filter(self, record: logging.LogRecord) -> bool:
        return not (
            record.name.startswith("yfinance")
            and "No earnings dates found" in record.getMessage()
        )


def configure_logging() -> None:
    logging.basicConfig(
        level=logging.WARNING,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    logger = logging.getLogger("yfinance")
    if not any(isinstance(item, ExpectedYFinanceGapFilter) for item in logger.filters):
        logger.addFilter(ExpectedYFinanceGapFilter())


def main() -> None:
    configure_logging()
    parser = argparse.ArgumentParser(description="Generate a personal daily stock research report.")
    parser.add_argument("--config", default="watchlist.yaml", help="Path to watchlist YAML config.")
    parser.add_argument("--date", default=None, help="Report date in YYYY-MM-DD format. Defaults to today.")
    parser.add_argument("--output-dir", default="reports", help="Base directory for reports (organized as YYYY/MM).")
    parser.add_argument("--db", default="data/stock_daily.sqlite3", help="SQLite database path.")
    parser.add_argument("--init-config", action="store_true", help="Copy watchlist.example.yaml to watchlist.yaml if missing.")
    parser.add_argument("--no-news", action="store_true", help="Skip online news fetching.")
    parser.add_argument("--no-valuation", action="store_true", help="Skip yfinance valuation and earnings fetching.")
    parser.add_argument("--no-macro", action="store_true", help="Skip official macro calendar fetching.")
    parser.add_argument("--no-taiwan-data", action="store_true", help="Skip official Taiwan revenue, institutional-flow, and market-margin data fetching.")
    parser.add_argument("--notify-telegram", action="store_true", help="Send a Telegram summary after generating the report.")
    parser.add_argument("--import-research-state", default=None, help="Import research state JSON into SQLite before generating the report.")
    parser.add_argument("--export-research-state", default=None, help="Export research state JSON from SQLite and exit.")
    parser.add_argument("--history-days", type=int, default=30, help="Days of report history to render in research sections.")
    args = parser.parse_args()

    if args.init_config:
        init_config(Path(args.config))
        return

    if args.export_research_state:
        export_path = export_research_state_cli(args.db, args.export_research_state)
        print(f"Exported research state to {export_path}")
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
        fetch_taiwan_data=not args.no_taiwan_data,
        notify_telegram=args.notify_telegram,
        import_research_state_path=args.import_research_state,
        history_days=max(7, int(args.history_days)),
    )
    print(f"Generated report for {report.report_date.isoformat()} in {report_output_dir(args.output_dir, report.report_date)}")


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


def export_research_state_cli(db_path: str | Path, output_path: str | Path) -> Path:
    with closing(init_db(db_path)) as conn:
        return export_research_state_file(conn, output_path)


def import_research_state_cli(db_path: str | Path, input_path: str | Path) -> None:
    with closing(init_db(db_path)) as conn:
        import_research_state_file(conn, input_path)
