from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any


MARKET_DEFAULTS: dict[str, dict[str, str]] = {
    "us": {
        "currency": "USD",
        "news_language": "en-US",
        "news_region": "US",
        "news_edition": "US:en",
    },
    "twse": {
        "currency": "TWD",
        "news_language": "zh-TW",
        "news_region": "TW",
        "news_edition": "TW:zh-Hant",
    },
    "tpex": {
        "currency": "TWD",
        "news_language": "zh-TW",
        "news_region": "TW",
        "news_edition": "TW:zh-Hant",
    },
    "crypto": {
        "currency": "USD",
        "news_language": "en-US",
        "news_region": "US",
        "news_edition": "US:en",
    },
}

MARKET_LABELS: dict[str, str] = {
    "us": "美股",
    "twse": "台股",
    "tpex": "上櫃",
    "crypto": "加密貨幣",
}

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
    stop_loss: float | None = None
    sector: str = ""


@dataclass(frozen=True)
class PortfolioSettings:
    total_value: float | None = None
    addable_cash: float | None = None
    max_sector_weight: float | None = None
    max_single_weight: float | None = None
    risk_budget_by_currency: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class InvestmentPlan:
    """Free-text trading playbook for a ticker (YAML defaults, UI overrides)."""
    bull_case: str = ""
    bear_case: str = ""
    entry_plan: str = ""
    add_zone: str = ""
    reduce_zone: str = ""
    stop_loss: str = ""

    @property
    def is_empty(self) -> bool:
        return not any(
            (
                self.bull_case,
                self.bear_case,
                self.entry_plan,
                self.add_zone,
                self.reduce_zone,
                self.stop_loss,
            )
        )


@dataclass(frozen=True)
class ResearchDefaults:
    """YAML-backed starting point for review/thesis fields."""
    thesis_state: str = ""
    thesis_trigger: str = ""
    thesis_text: str = ""
    note: str = ""
    tag: str = ""
    review_status: str = ""
    revisit_date: date | None = None

    @property
    def is_empty(self) -> bool:
        return not any(
            (
                self.thesis_state,
                self.thesis_trigger,
                self.thesis_text,
                self.note,
                self.tag,
                self.review_status,
                self.revisit_date,
            )
        )


@dataclass(frozen=True)
class TickerConfig:
    symbol: str
    company_name: str
    market: str = "us"
    currency: str = "USD"
    has_fundamentals: bool = True
    aliases: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)
    trusted_news_domains: list[str] = field(default_factory=list)
    trusted_x_accounts: list[TrustedXAccount] = field(default_factory=list)
    position: PositionConfig = field(default_factory=PositionConfig)
    plan: InvestmentPlan = field(default_factory=InvestmentPlan)
    research: ResearchDefaults = field(default_factory=ResearchDefaults)
    related_symbols: list[str] = field(default_factory=list)

    @property
    def display_symbol(self) -> str:
        """Human-facing symbol without the Yahoo Finance exchange suffix."""
        if self.market == "twse" and self.symbol.endswith(".TW"):
            return self.symbol[:-3]
        if self.market == "tpex" and self.symbol.endswith(".TWO"):
            return self.symbol[:-4]
        if self.market == "crypto" and "-" in self.symbol:
            return self.symbol.rsplit("-", 1)[0]
        return self.symbol

    @property
    def has_earnings(self) -> bool:
        """Only company-like assets expose a meaningful earnings calendar."""
        return self.has_fundamentals and self.market != "crypto"

    @property
    def news_language(self) -> str:
        return MARKET_DEFAULTS[self.market]["news_language"]

    @property
    def news_region(self) -> str:
        return MARKET_DEFAULTS[self.market]["news_region"]

    @property
    def news_edition(self) -> str:
        return MARKET_DEFAULTS[self.market]["news_edition"]

    @property
    def default_news_domains(self) -> list[str]:
        if self.market in {"twse", "tpex"}:
            return ["money.udn.com", "cnyes.com", "moneydj.com"]
        if self.market == "crypto":
            return ["coindesk.com", "cointelegraph.com", "theblock.co"]
        return ["reuters.com", "cnbc.com"]

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
    portfolio: PortfolioSettings = field(default_factory=PortfolioSettings)


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
class TickerResearchState:
    ticker: str
    tag: str = ""
    thesis_state: str = ""
    thesis_trigger: str = ""
    thesis_text: str = ""
    note: str = ""
    checklist: list[str] = field(default_factory=list)
    revisit_date: date | None = None
    pinned: bool = False
    review_status: str = "not-reviewed"
    last_reviewed_at: datetime | None = None
    updated_at: datetime | None = None
    bull_case: str = ""
    bear_case: str = ""
    entry_plan: str = ""
    add_zone: str = ""
    reduce_zone: str = ""
    stop_loss: str = ""
    earnings_questions: list[str] = field(default_factory=list)
    position: PositionConfig | None = None


@dataclass(frozen=True)
class PostEarningsReview:
    ticker: str
    earnings_date: date | None = None
    eps: str = ""
    revenue: str = ""
    guide: str = ""
    eps_surprise_pct: float | None = None
    revenue_surprise_pct: float | None = None
    fy1_eps_revision_after: float | None = None
    fy1_revenue_revision_after: float | None = None
    conclusion: str = ""
    next_step: str = ""
    gross_margin_change: str = ""
    management_keywords: str = ""
    thesis_changed: str = ""
    updated_at: datetime | None = None


@dataclass(frozen=True)
class TickerHistoryPoint:
    report_date: date
    generated_at: datetime
    ticker: str
    thesis_state: str = ""
    review_status: str = "not-reviewed"
    last_reviewed_at: datetime | None = None
    news_count: int = 0
    top_news_count: int = 0
    valuation_risk: str = "None"
    rsi: float | None = None
    daily_change_pct: float | None = None
    premarket_change_pct: float | None = None
    earnings_days: int | None = None
    warning_count: int = 0
    attention_score: float = 0.0
    news_burst_score: float = 0.0
    last_close: float | None = None
    right_side_status: str = ""
    right_side_tone: str = ""
    right_side_ready_count: int = 0
    right_side_check_count: int = 0


@dataclass(frozen=True)
class TaiwanMarketSnapshot:
    ticker: str
    revenue_month: str = ""
    monthly_revenue: float | None = None
    monthly_revenue_mom_pct: float | None = None
    monthly_revenue_yoy_pct: float | None = None
    cash_dividend_per_share: float | None = None
    dividend_year: str = ""
    foreign_net_shares: float | None = None
    investment_trust_net_shares: float | None = None
    dealer_net_shares: float | None = None
    foreign_net_shares_5d: float | None = None
    investment_trust_net_shares_5d: float | None = None
    institutional_net_buy_days_5d: int | None = None
    institutional_flow_days: int = 0
    institutional_as_of: date | None = None
    source: str = ""
    retrieved_at: datetime | None = None


@dataclass(frozen=True)
class TickerReport:
    ticker: TickerConfig
    articles: list[NewsArticle]
    x_signals: list[XSignal]
    valuation: ValuationSnapshot | None
    earnings: EarningsDate | None
    warnings: list[str] = field(default_factory=list)
    taiwan_market: TaiwanMarketSnapshot | None = None


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
    research_states: dict[str, TickerResearchState] = field(default_factory=dict)
    post_earnings_reviews: dict[str, PostEarningsReview] = field(default_factory=dict)
    ticker_history: dict[str, list[TickerHistoryPoint]] = field(default_factory=dict)
    history_overview: dict[str, Any] = field(default_factory=dict)
    settings: "AppSettings | None" = None
