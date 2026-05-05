from datetime import datetime, timezone

from stock_daily_research.models import NewsArticle, TickerConfig
from stock_daily_research.news import (
    GoogleNewsRssProvider,
    classify_event,
    dedupe_articles,
    is_noise_article,
    is_relevant_article,
    keyword_score,
    normalize_title,
)


def test_classify_event_detects_earnings() -> None:
    event_type, score = classify_event("Nvidia beats estimates on AI chip demand")

    assert event_type == "earnings"
    assert score >= 1.0


def test_classify_event_distinguishes_categories() -> None:
    # Partnership / deal — was historically getting tagged "earnings"
    event_type, _ = classify_event("OpenAI shakes up partnership with Microsoft")
    assert event_type == "deal"

    # AI startup / funding
    event_type, _ = classify_event("Former Google DeepMind researcher's AI startup raises $200M")
    assert event_type == "ai"

    # Regulator
    event_type, _ = classify_event("DOJ sues Apple over App Store practices")
    assert event_type == "regulation"

    # Analyst
    event_type, _ = classify_event("Morgan Stanley raises Nvidia price target to $200")
    assert event_type == "analyst"

    # Market move (was mistagged "earnings" because of stray keywords)
    event_type, _ = classify_event("Nasdaq, S&P 500 end lower as tech stocks slip")
    assert event_type == "market"


def test_classify_event_falls_back_to_other_when_uncertain() -> None:
    event_type, _ = classify_event("Some company does a thing today")
    assert event_type == "other"


def test_dedupe_articles_prefers_higher_score() -> None:
    lower = NewsArticle(
        ticker="NVDA",
        title="Nvidia earnings beat expectations",
        source="CNBC",
        domain="cnbc.com",
        published_at=datetime.now(timezone.utc),
        url="https://example.com/a?utm=1",
        summary="",
        event_type="earnings",
        importance_score=0.5,
    )
    higher = NewsArticle(
        ticker="NVDA",
        title="Nvidia earnings beat expectations",
        source="Reuters",
        domain="reuters.com",
        published_at=datetime.now(timezone.utc),
        url="https://example.com/b",
        summary="",
        event_type="earnings",
        importance_score=1.2,
    )

    result = dedupe_articles([lower, higher])

    assert len(result) == 1
    assert result[0].source == "Reuters"


def test_normalize_title_removes_punctuation() -> None:
    assert normalize_title("NVIDIA: AI Chips!") == "nvidia ai chips"


def test_is_relevant_article_requires_company_identity() -> None:
    ticker = TickerConfig(symbol="MSFT", company_name="Microsoft Corporation", aliases=["Microsoft"])

    assert is_relevant_article(ticker, "Microsoft earnings preview")
    assert not is_relevant_article(ticker, "S&P 500 rises into heavy earnings week")


def test_is_relevant_article_rejects_short_symbol_alone() -> None:
    """Short tickers like ARM and MU collide with English words / other-exchange suffixes."""
    arm = TickerConfig(symbol="ARM", company_name="Arm Holdings plc", aliases=["Arm"])
    mu = TickerConfig(symbol="MU", company_name="Micron Technology", aliases=["Micron"])

    # Body-part word should NOT trigger ARM (short alias "Arm" is dropped entirely)
    assert not is_relevant_article(arm, "Patient breaks arm in skiing accident")
    # Title-cased "music arm" shouldn't trigger either
    assert not is_relevant_article(arm, "Bertelsmann sells music arm to investor group")
    # Full company name match
    assert is_relevant_article(arm, "Arm Holdings posts solid licensing growth")
    # ".MU" suffix from another exchange should NOT trigger MU
    assert not is_relevant_article(mu, "Frankfurt-listed BMW.MU shares rise")
    # "Micron" alias (≥4 chars) should match
    assert is_relevant_article(mu, "Micron raises HBM guidance")


def test_is_relevant_article_long_symbol_matches_alone() -> None:
    googl = TickerConfig(symbol="GOOGL", company_name="Alphabet Inc.", aliases=["Alphabet", "Google"])

    # Long symbol can match alone since collision risk is low
    assert is_relevant_article(googl, "GOOGL upgraded by analyst")


def test_is_relevant_article_ignores_summary_peripheral_mentions() -> None:
    """Title is the only relevance signal — summary mentions don't pull in non-subject articles."""
    googl = TickerConfig(symbol="GOOGL", company_name="Alphabet Inc.", aliases=["Alphabet", "Google"])

    # Title is about Teradyne; summary mentions Alphabet peripherally — must reject
    assert not is_relevant_article(
        googl,
        "Teradyne forecasts sequential decline in quarterly revenue and profit",
        summary="Names mentioned: Microsoft, Alphabet, Nvidia",
    )
    # Title actually about Alphabet — passes
    assert is_relevant_article(
        googl,
        "Alphabet revenue tops expectations on cloud strength",
        summary="",
    )


def test_is_noise_article_rejects_quote_pages() -> None:
    assert is_noise_article("NVDA Stock Price", "https://example.com/quote/NVDA")
    assert is_noise_article("About Vanguard ETF", "https://example.com/etfs/voo")
    assert is_noise_article("Real-time NVDA quote", "https://example.com/symbols/NVDA")
    assert is_noise_article("Should you buy AAPL?", "https://example.com/article/123")
    assert is_noise_article("How to invest in semiconductors", "https://example.com/x")


def test_is_noise_article_rejects_etf_and_biography_pages() -> None:
    # Leveraged / option-income ETF profiles
    assert is_noise_article(
        "About YieldMax AMD Option Income Strategy ETF",
        "https://example.com/etfs/amdy",
    )
    assert is_noise_article(
        "Direxion Daily AMD Bull 2X Shares",
        "https://example.com/page/123",
    )
    # Officer biography pages
    assert is_noise_article(
        "Scott Gawel, Intel Corp: Profile and Biography",
        "https://example.com/profile/scott-gawel",
    )


def test_is_noise_article_passes_real_articles() -> None:
    assert not is_noise_article(
        "Nvidia revenue beats expectations on AI demand",
        "https://reuters.com/business/nvidia-revenue-beats-2026-04-29",
    )
    assert not is_noise_article(
        "Apple unveils new MacBook lineup",
        "https://cnbc.com/2026/04/29/apple-unveils-mac.html",
    )


def test_keyword_score_boosts_when_keyword_present() -> None:
    ticker = TickerConfig(
        symbol="NVDA",
        company_name="NVIDIA Corporation",
        keywords=["GPU", "AI chips"],
    )

    assert keyword_score(ticker, "Nvidia ships new GPU lineup") == 0.1
    assert keyword_score(ticker, "Nvidia hires new CFO") == 0.0
    assert keyword_score(TickerConfig(symbol="X", company_name="X"), "anything") == 0.0


def test_fetch_for_ticker_isolates_per_domain_failures(monkeypatch) -> None:
    ticker = TickerConfig(
        symbol="NVDA",
        company_name="NVIDIA Corporation",
        trusted_news_domains=["bad.com", "good.com"],
    )
    provider = GoogleNewsRssProvider()

    good_article = NewsArticle(
        ticker="NVDA",
        title="Nvidia earnings beat expectations",
        source="Good",
        domain="good.com",
        published_at=datetime.now(timezone.utc),
        url="https://good.com/a",
        summary="",
        event_type="earnings",
        importance_score=1.2,
    )

    def fake_fetch(self, t, domain, lookback_days, min_published_at):
        if domain == "bad.com":
            raise RuntimeError("boom")
        return [good_article]

    monkeypatch.setattr(GoogleNewsRssProvider, "_fetch_for_domain", fake_fetch)

    articles, warnings = provider.fetch_for_ticker(ticker, lookback_days=3, max_articles=10)

    assert articles == [good_article]
    assert any("bad.com" in warning for warning in warnings)
