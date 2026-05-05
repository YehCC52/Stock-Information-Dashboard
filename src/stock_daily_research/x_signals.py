from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import yaml

from .models import TickerConfig, XSignal


def load_manual_x_signals(path: str | Path, tickers: list[TickerConfig]) -> list[XSignal]:
    manual_path = Path(path)
    if not manual_path.exists():
        return []

    trusted = {
        (ticker.symbol, account.handle.lower()): account.category
        for ticker in tickers
        for account in ticker.trusted_x_accounts
    }
    data = yaml.safe_load(manual_path.read_text(encoding="utf-8")) or {}
    signals: list[XSignal] = []

    for item in data.get("posts", []):
        ticker = str(item.get("ticker", "")).upper()
        handle = str(item.get("author_handle", "")).lstrip("@")
        if (ticker, handle.lower()) not in trusted:
            continue

        category = str(item.get("author_category") or trusted[(ticker, handle.lower())])
        signals.append(
            XSignal(
                ticker=ticker,
                author_handle=handle,
                author_category=category,
                text=str(item.get("text", "")).strip(),
                created_at=parse_iso_datetime(item.get("created_at")),
                url=str(item.get("url", "")).strip(),
                like_count=int(item.get("like_count", 0) or 0),
                repost_count=int(item.get("repost_count", 0) or 0),
                reply_count=int(item.get("reply_count", 0) or 0),
                quote_count=int(item.get("quote_count", 0) or 0),
                credibility_score=score_category(category),
            )
        )
    return dedupe_signals(signals)


def parse_iso_datetime(value: object) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    text = str(value).replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def score_category(category: str) -> float:
    return {
        "company_official": 1.0,
        "investor_relations": 1.0,
        "executive": 0.95,
        "sell_side_analyst": 0.8,
        "buy_side_researcher": 0.75,
        "industry_expert": 0.7,
        "data_provider": 0.65,
        "journalist": 0.6,
    }.get(category, 0.4)


def dedupe_signals(signals: list[XSignal]) -> list[XSignal]:
    seen: set[str] = set()
    result: list[XSignal] = []
    for signal in sorted(signals, key=lambda item: item.credibility_score, reverse=True):
        key = signal.url or f"{signal.ticker}:{signal.author_handle}:{signal.text[:80]}"
        if key in seen:
            continue
        seen.add(key)
        result.append(signal)
    return result
