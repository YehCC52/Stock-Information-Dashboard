from __future__ import annotations

from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import yaml

from .models import (
    AppConfig,
    AppSettings,
    EarningsSettings,
    MacroSettings,
    NewsSettings,
    NotificationSettings,
    TickerConfig,
    TelegramSettings,
    TrustedXAccount,
    ValuationSettings,
    XSignalSettings,
)


def load_config(path: str | Path) -> AppConfig:
    config_path = Path(path)
    data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    settings_data = data.get("settings", {})

    timezone_name = str(settings_data.get("report_timezone", "Asia/Taipei"))
    try:
        ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(f"Invalid report_timezone '{timezone_name}': {exc}") from exc

    settings = AppSettings(
        report_timezone=timezone_name,
        news=_load_news_settings(settings_data.get("news", {})),
        x_signals=_load_x_settings(settings_data.get("x_signals", {})),
        valuation=_load_valuation_settings(settings_data.get("valuation", {})),
        earnings=_load_earnings_settings(settings_data.get("earnings", {})),
        macro=_load_macro_settings(settings_data.get("macro", {})),
        notifications=_load_notification_settings(settings_data.get("notifications", {})),
    )

    tickers = [_load_ticker(index, item) for index, item in enumerate(data.get("tickers", []))]
    if not tickers:
        raise ValueError(f"No tickers configured in {config_path}")

    return AppConfig(settings=settings, tickers=tickers)


def _load_news_settings(data: dict[str, Any]) -> NewsSettings:
    lookback_days = _positive_int(data.get("lookback_days", 3), "news.lookback_days")
    max_articles = _positive_int(data.get("max_articles_per_ticker", 8), "news.max_articles_per_ticker")
    return NewsSettings(
        lookback_days=lookback_days,
        max_articles_per_ticker=max_articles,
        provider=str(data.get("provider", "google_news_rss")),
    )


def _positive_int(value: Any, field: str) -> int:
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be an integer, got {value!r}") from exc
    if result <= 0:
        raise ValueError(f"{field} must be > 0, got {result}")
    return result


_ALLOWED_X_MODES = {"manual", "api"}


def _load_x_settings(data: dict[str, Any]) -> XSignalSettings:
    mode = str(data.get("mode", "manual"))
    if mode not in _ALLOWED_X_MODES:
        raise ValueError(
            f"Invalid x_signals.mode '{mode}'. Allowed values: {sorted(_ALLOWED_X_MODES)}"
        )
    return XSignalSettings(
        mode=mode,
        manual_file=str(data.get("manual_file", "data/x_posts.yaml")),
    )


def _load_valuation_settings(data: dict[str, Any]) -> ValuationSettings:
    return ValuationSettings(provider=str(data.get("provider", "yfinance")))


def _load_earnings_settings(data: dict[str, Any]) -> EarningsSettings:
    provider_order = data.get("provider_order") or ["yfinance"]
    return EarningsSettings(provider_order=[str(provider) for provider in provider_order])


def _load_macro_settings(data: dict[str, Any]) -> MacroSettings:
    return MacroSettings(
        enabled=bool(data.get("enabled", True)),
        days_back=_positive_int(data.get("days_back", 1), "macro.days_back"),
        days_ahead=_positive_int(data.get("days_ahead", 14), "macro.days_ahead"),
    )


def _load_notification_settings(data: dict[str, Any]) -> NotificationSettings:
    telegram = data.get("telegram", {})
    return NotificationSettings(
        telegram=TelegramSettings(
            enabled=bool(telegram.get("enabled", False)),
            disable_web_page_preview=bool(telegram.get("disable_web_page_preview", True)),
        )
    )


def _load_ticker(index: int, data: dict[str, Any]) -> TickerConfig:
    symbol = data.get("symbol")
    company_name = data.get("company_name")
    if not symbol:
        raise ValueError(f"tickers[{index}].symbol is required")
    if not company_name:
        raise ValueError(f"tickers[{index}].company_name is required")
    return TickerConfig(
        symbol=str(symbol).upper(),
        company_name=str(company_name),
        aliases=[str(value) for value in data.get("aliases", [])],
        keywords=[str(value) for value in data.get("keywords", [])],
        trusted_news_domains=[str(value).lower() for value in data.get("trusted_news_domains", [])],
        trusted_x_accounts=[_load_x_account(index, idx, account) for idx, account in enumerate(data.get("trusted_x_accounts", []))],
    )


def _load_x_account(ticker_index: int, account_index: int, data: dict[str, Any]) -> TrustedXAccount:
    handle = data.get("handle")
    category = data.get("category")
    if not handle:
        raise ValueError(f"tickers[{ticker_index}].trusted_x_accounts[{account_index}].handle is required")
    if not category:
        raise ValueError(f"tickers[{ticker_index}].trusted_x_accounts[{account_index}].category is required")
    return TrustedXAccount(
        handle=str(handle).lstrip("@"),
        category=str(category),
        display_name=data.get("display_name"),
    )
