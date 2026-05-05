from pathlib import Path

import pytest

from stock_daily_research.cli import init_config


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
