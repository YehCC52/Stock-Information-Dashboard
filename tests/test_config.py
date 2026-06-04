from pathlib import Path

import pytest

from stock_daily_research.config import load_config


def _write(path: Path, body: str) -> Path:
    path.write_text(body, encoding="utf-8")
    return path


def test_load_config_rejects_unknown_x_signals_mode(tmp_path: Path) -> None:
    config_path = _write(
        tmp_path / "watchlist.yaml",
        """
settings:
  x_signals:
    mode: scrape
tickers:
  - symbol: NVDA
    company_name: NVIDIA Corporation
""",
    )

    with pytest.raises(ValueError, match="x_signals.mode"):
        load_config(config_path)


def test_load_config_requires_tickers(tmp_path: Path) -> None:
    config_path = _write(tmp_path / "watchlist.yaml", "settings: {}\ntickers: []\n")

    with pytest.raises(ValueError, match="No tickers"):
        load_config(config_path)


def test_load_config_normalizes_ticker_symbol(tmp_path: Path) -> None:
    config_path = _write(
        tmp_path / "watchlist.yaml",
        """
tickers:
  - symbol: nvda
    company_name: NVIDIA Corporation
""",
    )

    config = load_config(config_path)

    assert config.tickers[0].symbol == "NVDA"
    assert config.settings.x_signals.mode == "manual"


def test_load_config_reads_position_and_manual_macro_events(tmp_path: Path) -> None:
    config_path = _write(
        tmp_path / "watchlist.yaml",
        """
settings:
  macro:
    manual_events:
      - name: CPI Release
        category: inflation
        event_datetime: "2026-05-12T20:30:00+08:00"
tickers:
  - symbol: nvda
    company_name: NVIDIA Corporation
    position:
      status: holding
      shares: 10
      avg_cost: 120
      portfolio_weight: 6.5
""",
    )

    config = load_config(config_path)

    assert config.tickers[0].position.status == "holding"
    assert config.tickers[0].position.shares == 10
    assert config.settings.macro.manual_events[0].name == "CPI Release"
    assert config.settings.macro.manual_events[0].event_datetime.isoformat() == "2026-05-12T20:30:00+08:00"


def test_load_config_reads_research_defaults(tmp_path: Path) -> None:
    config_path = _write(
        tmp_path / "watchlist.yaml",
        """
tickers:
  - symbol: nvda
    company_name: NVIDIA Corporation
    research:
      thesis_state: active
      thesis_trigger: execution
      thesis_text: AI demand remains the core thesis.
      revisit_date: "2026-06-04"
""",
    )

    config = load_config(config_path)

    assert config.tickers[0].research.thesis_state == "active"
    assert config.tickers[0].research.thesis_trigger == "execution"
    assert config.tickers[0].research.thesis_text == "AI demand remains the core thesis."
    assert config.tickers[0].research.revisit_date.isoformat() == "2026-06-04"


def test_load_config_rejects_invalid_timezone(tmp_path: Path) -> None:
    config_path = _write(
        tmp_path / "watchlist.yaml",
        """
settings:
  report_timezone: Mars/Olympus_Mons
tickers:
  - symbol: NVDA
    company_name: NVIDIA Corporation
""",
    )

    with pytest.raises(ValueError, match="report_timezone"):
        load_config(config_path)


def test_load_config_rejects_non_positive_lookback(tmp_path: Path) -> None:
    config_path = _write(
        tmp_path / "watchlist.yaml",
        """
settings:
  news:
    lookback_days: 0
tickers:
  - symbol: NVDA
    company_name: NVIDIA Corporation
""",
    )

    with pytest.raises(ValueError, match="lookback_days"):
        load_config(config_path)


def test_load_config_rejects_non_positive_macro_days_ahead(tmp_path: Path) -> None:
    config_path = _write(
        tmp_path / "watchlist.yaml",
        """
settings:
  macro:
    days_ahead: 0
tickers:
  - symbol: NVDA
    company_name: NVIDIA Corporation
""",
    )

    with pytest.raises(ValueError, match="macro.days_ahead"):
        load_config(config_path)


def test_load_config_rejects_non_positive_macro_days_back(tmp_path: Path) -> None:
    config_path = _write(
        tmp_path / "watchlist.yaml",
        """
settings:
  macro:
    days_back: 0
tickers:
  - symbol: NVDA
    company_name: NVIDIA Corporation
""",
    )

    with pytest.raises(ValueError, match="macro.days_back"):
        load_config(config_path)


def test_load_config_requires_ticker_symbol(tmp_path: Path) -> None:
    config_path = _write(
        tmp_path / "watchlist.yaml",
        """
tickers:
  - company_name: NVIDIA Corporation
""",
    )

    with pytest.raises(ValueError, match=r"tickers\[0\].symbol"):
        load_config(config_path)


def test_load_config_requires_x_account_handle(tmp_path: Path) -> None:
    config_path = _write(
        tmp_path / "watchlist.yaml",
        """
tickers:
  - symbol: NVDA
    company_name: NVIDIA Corporation
    trusted_x_accounts:
      - category: industry_expert
""",
    )

    with pytest.raises(ValueError, match="handle is required"):
        load_config(config_path)
