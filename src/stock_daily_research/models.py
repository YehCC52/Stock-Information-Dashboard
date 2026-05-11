from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any


@dataclass(frozen=True)
class TrustedXAccount:
    handle: str
    category: str
    display_name: str | None = None


@dataclass(frozen=True)
class PositionConfig:
    status: str = "watchlist"
    shares: float | None = None
    avg_cost: float | None = None
    portfolio_weight: float | None = None
    position_size: float | None = None


@dataclass(frozen=True)
class TickerConfig:
    symbol: str
    company_name: str
    aliases: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)
    trusted_news_domains: list[str] = field(default_factory=list)
    trusted_x_accounts: list[TrustedXAccount] = field(default_factory=list)
    position: PositionConfig = field(default_factory=PositionConfig)

    @property
    def search_terms(self) -> list[str]:
        terms = [self.symbol, self.company_name, *self.aliases, *self.keywords]
        seen: set[str] = set()
        result: list[str] = []
        for term in terms:
            normalized = term.strip()
            key = normalized.lower()
            if normalized and key not in seen:
                seen.add(key)
                result.append(normalized)
        return result


@dataclass(frozen=True)
class NewsSettings:
    lookback_days: int = 3
    max_articles_per_ticker: int = 8
    provider: str = "google_news_rss"


@dataclass(frozen=True)
class XSignalSettings:
    mode: str = "manual"
    manual_file: str = "data/x_posts.yaml"


@dataclass(frozen=True)
class ValuationSettings:
    provider: str = "yfinance"


@dataclass(frozen=True)
class EarningsSettings:
    provider_order: list[str] = field(default_factory=lambda: ["yfinance"])


@dataclass(frozen=True)
class MacroSettings:
    enabled: bool = True
    days_back: int = 1
    days_ahead: int = 14
    manual_events: list["ManualMacroEvent"] = field(default_factory=list)


@dataclass(frozen=True)
class ManualMacroEvent:
    name: str
    category: str
    event_datetime: datetime
    source: str = "manual"
    source_url: str = ""
    importance: str = "high"
    notes: str | None = None


@dataclass(frozen=True)
class TelegramSettings:
    enabled: bool = False
    disable_web_page_preview: bool = True


@dataclass(frozen=True)
class NotificationSettings:
    telegram: TelegramSettings = field(default_factory=TelegramSettings)


@dataclass(frozen=True)
class AppSettings:
    report_timezone: str = "Asia/Taipei"
    news: NewsSettings = field(default_factory=NewsSettings)
    x_signals: XSignalSettings = field(default_factory=XSignalSettings)
    valuation: ValuationSettings = field(default_factory=ValuationSettings)
    earnings: EarningsSettings = field(default_factory=EarningsSettings)
    macro: MacroSettings = field(default_factory=MacroSettings)
    notifications: NotificationSettings = field(default_factory=NotificationSettings)


@dataclass(frozen=True)
class AppConfig:
    settings: AppSettings
    tickers: list[TickerConfig]


@dataclass(frozen=True)
class NewsArticle:
    ticker: str
    title: str
    source: str
    domain: str
    published_at: datetime | None
    url: str
    summary: str
    event_type: str
    importance_score: float


@dataclass(frozen=True)
class XSignal:
    ticker: str
    author_handle: str
    author_category: str
    text: str
    created_at: datetime | None
    url: str
    like_count: int = 0
    repost_count: int = 0
    reply_count: int = 0
    quote_count: int = 0
    credibility_score: float = 0.0


@dataclass(frozen=True)
class ValuationSnapshot:
    ticker: str
    as_of_date: date
    source: str
    metrics: dict[str, Any]
    retrieved_at: datetime


@dataclass(frozen=True)
class EarningsDate:
    ticker: str
    company_name: str
    earnings_date: date | None
    time_of_day: str
    fiscal_quarter: str | None
    fiscal_year: int | None
    eps_estimate: float | None
    revenue_estimate: float | None
    source: str
    source_retrieved_at: datetime


@dataclass(frozen=True)
class EconomicEvent:
    name: str
    category: str
    event_datetime: datetime
    source: str
    source_url: str
    importance: str = "high"
    notes: str | None = None
    source_time_label: str | None = None


@dataclass(frozen=True)
class MarketSentimentComponent:
    name: str
    score: float
    label: str
    detail: str


@dataclass(frozen=True)
class MarketSentiment:
    score: int
    label: str
    source: str
    retrieved_at: datetime
    components: list[MarketSentimentComponent] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class RateLevel:
    """Single rates / FX point for the macro overlay."""
    name: str            # "10Y" / "5Y" / "DXY"
    last: float
    prev: float
    change: float        # bp for yields, % for DXY
    unit: str            # "bp" or "%"


@dataclass(frozen=True)
class BreadthRow:
    """Pair-wise relative-return comparison (cap-weight vs equal-weight, etc.)."""
    label: str           # "QQQ vs QQQE"
    a_symbol: str
    b_symbol: str
    a_return: float      # 20-day total return %
    b_return: float
    spread: float        # a - b in pct points


@dataclass(frozen=True)
class MarketContext:
    """Macro overlay: rates direction, market breadth, benchmark returns.

    Computed once per run (one global fetch) — not per-ticker. Powers the
    "is the tide going up or down" framing alongside MarketSentiment.
    """
    rates: list[RateLevel] = field(default_factory=list)
    breadth: list[BreadthRow] = field(default_factory=list)
    benchmark_returns: dict[str, float] = field(default_factory=dict)
    retrieved_at: datetime | None = None
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class PremarketMove:
    symbol: str
    name: str
    last: float | None
    previous_close: float | None
    change_pct: float | None
    source: str
    note: str = ""


@dataclass(frozen=True)
class PremarketSnapshot:
    retrieved_at: datetime
    benchmarks: list[PremarketMove] = field(default_factory=list)
    watchlist_movers: list[PremarketMove] = field(default_factory=list)
    gap_movers: list[PremarketMove] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class TickerReport:
    ticker: TickerConfig
    articles: list[NewsArticle]
    x_signals: list[XSignal]
    valuation: ValuationSnapshot | None
    earnings: EarningsDate | None
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class DailyReport:
    report_date: date
    generated_at: datetime
    ticker_reports: list[TickerReport]
    warnings: list[str] = field(default_factory=list)
    economic_events: list[EconomicEvent] = field(default_factory=list)
    market_sentiment: MarketSentiment | None = None
    market_context: MarketContext | None = None
    premarket: PremarketSnapshot | None = None
