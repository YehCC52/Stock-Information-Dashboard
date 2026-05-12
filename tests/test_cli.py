from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from stock_daily_research.cli import export_research_state_cli, import_research_state_cli, init_config
from stock_daily_research.models import DailyReport, PostEarningsReview, TickerConfig, TickerResearchState, TickerReport
from stock_daily_research.storage import init_db, load_post_earnings_reviews, load_ticker_research_states, save_report


def test_init_config_copies_example(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "watchlist.example.yaml").write_text("tickers: []\n", encoding="utf-8")
    target = tmp_path / "watchlist.yaml"

    init_config(target)

    assert target.exists()
    assert target.read_text(encoding="utf-8") == "tickers: []\n"


def test_init_config_does_not_overwrite_existing(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "watchlist.example.yaml").write_text("from-example\n", encoding="utf-8")
    target = tmp_path / "watchlist.yaml"
    target.write_text("user-edits\n", encoding="utf-8")

    init_config(target)

    assert target.read_text(encoding="utf-8") == "user-edits\n"
    assert "already exists" in capsys.readouterr().out


def test_init_config_errors_when_example_missing(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    target = tmp_path / "watchlist.yaml"

    with pytest.raises(SystemExit, match="watchlist.example.yaml"):
        init_config(target)


def test_research_state_cli_roundtrip(tmp_path: Path) -> None:
    db_path = tmp_path / "stock.sqlite3"
    export_path = tmp_path / "research.json"
    seed_report = DailyReport(
        report_date=date(2026, 4, 28),
        generated_at=datetime(2026, 4, 28, tzinfo=timezone.utc),
        ticker_reports=[
            TickerReport(
                ticker=TickerConfig(symbol="NVDA", company_name="NVIDIA Corporation"),
                articles=[],
                x_signals=[],
                valuation=None,
                earnings=None,
            )
        ],
        research_states={
            "NVDA": TickerResearchState(
                ticker="NVDA",
                thesis_state="building",
                note="Need follow-through after guide raise.",
                checklist=["news"],
            )
        },
        post_earnings_reviews={
            "NVDA": PostEarningsReview(
                ticker="NVDA",
                earnings_date=date(2026, 4, 27),
                conclusion="Still constructive.",
            )
        },
    )

    with init_db(db_path) as conn:
        save_report(conn, seed_report)

    written = export_research_state_cli(db_path, export_path)

    assert written == export_path
    assert export_path.exists()

    imported_db = tmp_path / "imported.sqlite3"
    import_research_state_cli(imported_db, export_path)
    with init_db(imported_db) as conn:
        state = load_ticker_research_states(conn, ["NVDA"])["NVDA"]
        review = load_post_earnings_reviews(conn, ["NVDA"])["NVDA"]

    assert state.thesis_state == "building"
    assert state.note == "Need follow-through after guide raise."
    assert review.conclusion == "Still constructive."
