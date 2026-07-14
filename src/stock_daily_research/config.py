from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import yaml

from .models import (
    AppConfig,
    AppSettings,
    EarningsSettings,
    InvestmentPlan,
    MARKET_DEFAULTS,
    MacroSettings,
    ManualMacroEvent,
    NewsSettings,
    NotificationSettings,
    PortfolioSettings,
    PositionConfig,
    ResearchDefaults,
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
        portfolio=_load_portfolio_settings(settings_data.get("portfolio", {})),
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
        manual_events=[_load_manual_macro_event(idx, item) for idx, item in enumerate(data.get("manual_events", []))],
    )


def _load_manual_macro_event(index: int, data: dict[str, Any]) -> ManualMacroEvent:
    name = data.get("name")
    category = data.get("category", "macro")
    event_datetime = data.get("event_datetime")
    if not name:
        raise ValueError(f"macro.manual_events[{index}].name is required")
    if not event_datetime:
        raise ValueError(f"macro.manual_events[{index}].event_datetime is required")
    try:
        dt = datetime.fromisoformat(str(event_datetime).replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"macro.manual_events[{index}].event_datetime must be ISO datetime") from exc
    if dt.tzinfo is None:
        raise ValueError(f"macro.manual_events[{index}].event_datetime must include timezone")
    return ManualMacroEvent(
        name=str(name),
        category=str(category),
        event_datetime=dt,
        source=str(data.get("source", "manual")),
        source_url=str(data.get("source_url", "")),
        importance=str(data.get("importance", "high")),
        notes=data.get("notes"),
    )


def _load_notification_settings(data: dict[str, Any]) -> NotificationSettings:
    telegram = data.get("telegram", {})
    return NotificationSettings(
        telegram=TelegramSettings(
            enabled=bool(telegram.get("enabled", False)),
            disable_web_page_preview=bool(telegram.get("disable_web_page_preview", True)),
        )
    )


def _infer_market(symbol: str) -> str | None:
    if symbol.endswith(".TW"):
        return "twse"
    if symbol.endswith(".TWO"):
        return "tpex"
    if symbol.endswith("-USD"):
        return "crypto"
    if "." in symbol:
        # A Yahoo dot-suffix means a non-US exchange we don't know. Guessing
        # "us" would also guess currency=USD and silently corrupt the
        # mixed-currency P&L guard — make the user declare the market.
        return None
    return "us"


def _load_ticker(index: int, data: dict[str, Any]) -> TickerConfig:
    symbol = data.get("symbol")
    company_name = data.get("company_name")
    if not symbol:
        raise ValueError(f"tickers[{index}].symbol is required")
    if not company_name:
        raise ValueError(f"tickers[{index}].company_name is required")
    normalized_symbol = str(symbol).upper()
    market_raw = data.get("market") or _infer_market(normalized_symbol)
    if market_raw is None:
        raise ValueError(
            f"tickers[{index}].market is required for '{normalized_symbol}': "
            "unrecognized exchange suffix, set market/currency explicitly"
        )
    market = str(market_raw).lower()
    if market not in MARKET_DEFAULTS:
        allowed = ", ".join(sorted(MARKET_DEFAULTS))
        raise ValueError(f"tickers[{index}].market must be one of {allowed}, got {market!r}")
    return TickerConfig(
        symbol=normalized_symbol,
        company_name=str(company_name),
        market=market,
        currency=str(data.get("currency") or MARKET_DEFAULTS[market]["currency"]).upper(),
        has_fundamentals=bool(data.get("has_fundamentals", True)),
        aliases=[str(value) for value in data.get("aliases", [])],
        keywords=[str(value) for value in data.get("keywords", [])],
        trusted_news_domains=[str(value).lower() for value in data.get("trusted_news_domains", [])],
        trusted_x_accounts=[_load_x_account(index, idx, account) for idx, account in enumerate(data.get("trusted_x_accounts", []))],
        position=_load_position(data.get("position", {})),
        plan=_load_plan(data.get("plan", {})),
        research=_load_research_defaults(data.get("research", {})),
        related_symbols=[str(value).upper() for value in data.get("related_symbols", [])],
    )


def _load_plan(data: dict[str, Any]) -> InvestmentPlan:
    if not isinstance(data, dict):
        return InvestmentPlan()
    return InvestmentPlan(
        bull_case=str(data.get("bull_case", "") or ""),
        bear_case=str(data.get("bear_case", "") or ""),
        entry_plan=str(data.get("entry_plan", "") or ""),
        add_zone=str(data.get("add_zone", "") or ""),
        reduce_zone=str(data.get("reduce_zone", "") or ""),
        stop_loss=str(data.get("stop_loss", "") or ""),
    )


def _load_position(data: dict[str, Any]) -> PositionConfig:
    return PositionConfig(
        status=str(data.get("status", "watchlist")),
        shares=_optional_float(data.get("shares")),
        avg_cost=_optional_float(data.get("avg_cost")),
        portfolio_weight=_optional_float(data.get("portfolio_weight")),
        position_size=_optional_float(data.get("position_size")),
        stop_loss=_optional_float(data.get("stop_loss")),
        sector=str(data.get("sector", "") or ""),
    )


def _load_research_defaults(data: dict[str, Any]) -> ResearchDefaults:
    if not isinstance(data, dict):
        return ResearchDefaults()
    return ResearchDefaults(
        thesis_state=str(data.get("thesis_state", "") or ""),
        thesis_trigger=str(data.get("thesis_trigger", "") or ""),
        thesis_text=str(data.get("thesis_text", "") or ""),
        note=str(data.get("note", "") or ""),
        tag=str(data.get("tag", "") or ""),
        review_status=str(data.get("review_status", "") or ""),
        revisit_date=_optional_date(data.get("revisit_date")),
    )


def _load_portfolio_settings(data: dict[str, Any]) -> PortfolioSettings:
    return PortfolioSettings(
        total_value=_optional_float(data.get("total_value")),
        addable_cash=_optional_float(data.get("addable_cash")),
        max_sector_weight=_optional_float(data.get("max_sector_weight")),
        max_single_weight=_optional_float(data.get("max_single_weight")),
        risk_budget_by_currency=_read_risk_budgets(data.get("risk_budget_by_currency")),
    )


def _read_risk_budgets(raw: Any) -> dict[str, float]:
    if raw in (None, ""):
        return {}
    if not isinstance(raw, dict):
        raise ValueError("portfolio.risk_budget_by_currency must be a mapping")
    budgets: dict[str, float] = {}
    for currency, value in raw.items():
        amount = _optional_float(value)
        if amount is not None and amount > 0:
            budgets[str(currency).upper()] = amount
    return budgets


def _optional_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Position field must be numeric, got {value!r}") from exc


def _optional_date(value: Any) -> date | None:
    if value is None or value == "":
        return None
    try:
        return date.fromisoformat(str(value))
    except ValueError as exc:
        raise ValueError(f"Research date field must be YYYY-MM-DD, got {value!r}") from exc


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
