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
