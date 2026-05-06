from datetime import date, datetime, timezone

from stock_daily_research.models import (
    DailyReport,
    EconomicEvent,
    EarningsDate,
    MarketSentiment,
    MarketSentimentComponent,
    NewsArticle,
    TickerConfig,
    TickerReport,
    ValuationSnapshot,
)
from stock_daily_research.report import (
    build_summary,
    card_state,
    days_until,
    earnings_delta,
    earnings_urgency,
    event_label,
    hero_items,
    important_news,
    news_tier,
    pe_class,
    priority_items,
    render_html_report,
    render_markdown_report,
    rsi_class,
    rsi_label,
    rule_alerts,
    sort_by_market_cap,
    topic_tags,
    top_news_count,
    ticker_insights,
    valuation_risk_label,
    write_report,
)


def test_render_markdown_report_includes_all_sections() -> None:
    report = _sample_report()

    output = render_markdown_report(report)

    assert "# Daily Stock Research - 2026-04-28" in output
    assert "## NVDA - NVIDIA Corporation" in output
    assert "Nvidia revenue beats" in output
    assert "5.26T" in output
    assert "Trailing P/E" in output
    assert "global warn" in output
    assert "news flake" in output


def test_render_html_report_includes_visual_sections() -> None:
    output = render_html_report(_sample_report())

    assert "<!doctype html>" in output
    assert "Macro Calendar" in output
    assert "FOMC Rate Decision" in output
    assert "Valuation Snapshot" in output
    assert "Ticker Cards" in output
    assert "Nvidia revenue beats" in output
    assert "5.26T" in output


def test_write_report_outputs_markdown_and_html(tmp_path) -> None:
    paths = write_report(_sample_report(), tmp_path)

    assert paths.markdown.exists()
    assert paths.html.exists()
    assert paths.markdown.suffix == ".md"
    assert paths.html.suffix == ".html"

    # Files must be raw UTF-8 with NO BOM. A leading U+FEFF would render as a
    # stray character or break HTML parsing in some browsers.
    assert paths.html.read_bytes()[:3] != b"\xef\xbb\xbf"
    assert paths.markdown.read_bytes()[:3] != b"\xef\xbb\xbf"
    assert not paths.html.read_text(encoding="utf-8").startswith(chr(0xfeff))
    assert not paths.markdown.read_text(encoding="utf-8").startswith(chr(0xfeff))


def test_sort_by_market_cap_orders_largest_first_then_unknowns() -> None:
    def make(symbol, market_cap):
        valuation = None
        if market_cap is not None:
            valuation = ValuationSnapshot(
                ticker=symbol, as_of_date=date(2026, 4, 28), source="yfinance",
                metrics={"market_cap": market_cap},
                retrieved_at=datetime(2026, 4, 28, tzinfo=timezone.utc),
            )
        return TickerReport(
            ticker=TickerConfig(symbol=symbol, company_name=f"{symbol} Inc"),
            articles=[], x_signals=[], valuation=valuation, earnings=None,
        )

    items = [
        make("SMALL", 50_000_000_000),
        make("UNKNOWN", None),
        make("HUGE", 3_000_000_000_000),
        make("MID", 500_000_000_000),
        make("NAN_MC", float("nan")),
    ]

    sorted_items = sort_by_market_cap(items)
    symbols = [it.ticker.symbol for it in sorted_items]

    assert symbols[:3] == ["HUGE", "MID", "SMALL"]
    assert set(symbols[3:]) == {"UNKNOWN", "NAN_MC"}


def test_render_html_report_sorts_ticker_cards_by_market_cap() -> None:
    def card(symbol, market_cap):
        valuation = ValuationSnapshot(
            ticker=symbol, as_of_date=date(2026, 4, 28), source="yfinance",
            metrics={"market_cap": market_cap},
            retrieved_at=datetime(2026, 4, 28, tzinfo=timezone.utc),
        ) if market_cap is not None else None
        return TickerReport(
            ticker=TickerConfig(symbol=symbol, company_name=f"{symbol} Inc"),
            articles=[], x_signals=[], valuation=valuation, earnings=None,
        )

    report = DailyReport(
        report_date=date(2026, 4, 28),
        generated_at=datetime(2026, 4, 28, tzinfo=timezone.utc),
        ticker_reports=[
            card("AAPL", 3_000_000_000_000),
            card("SMALL", 50_000_000_000),
            card("MSFT", 3_500_000_000_000),
        ],
    )

    output = render_html_report(report)

    tickers_start = output.index('id="tickers"')
    body = output[tickers_start:]
    import re
    order = re.findall(r'<article class="ticker-card[^"]*" id="ticker-([a-z]+)"', body)

    assert order == ["msft", "aapl", "small"]


def test_render_html_report_sorts_valuation_table_alphabetically() -> None:
    report = DailyReport(
        report_date=date(2026, 4, 28),
        generated_at=datetime(2026, 4, 28, tzinfo=timezone.utc),
        ticker_reports=[
            TickerReport(
                ticker=TickerConfig(symbol=symbol, company_name=f"{symbol} Inc"),
                articles=[], x_signals=[], valuation=None, earnings=None,
            )
            for symbol in ("NVDA", "AAPL", "MSFT", "AMZN")
        ],
    )

    output = render_html_report(report)

    # Locate the Valuation Snapshot section's tbody and check ticker order
    vs_start = output.index('id="valuation"')
    vs_end = output.index("</tbody>", vs_start)
    body = output[vs_start:vs_end]
    import re
    order = re.findall(r"#ticker-([a-z]+)", body)

    assert order == ["aapl", "amzn", "msft", "nvda"]


def test_render_html_report_links_table_to_ticker_cards() -> None:
    output = render_html_report(_sample_report())

    assert 'href="#ticker-nvda"' in output
    assert 'id="ticker-nvda"' in output
    assert "color-scheme: light dark" in output
    assert "prefers-color-scheme: dark" in output


def test_render_html_report_includes_theme_toggle() -> None:
    output = render_html_report(_sample_report())

    assert 'id="theme-toggle"' in output
    assert ':root[data-theme="dark"]' in output
    assert ':root[data-theme="light"]' in output
    assert 'stock-daily-theme' in output  # localStorage key
    assert ':root:not([data-theme="light"])' in output  # OS-pref override guard


def test_render_html_report_includes_interactive_dashboard_controls() -> None:
    output = render_html_report(_sample_report())

    assert 'id="quick-search"' in output
    assert 'data-mode="overview"' in output
    assert 'id="focus-filter"' in output
    assert 'id="state-filter"' in output
    assert 'id="rsi-filter"' in output
    assert 'id="valuation-sort"' in output
    assert "Market Sentiment" in output
    assert "RSI 14" in output
    assert 'id="compare-panel"' in output
    assert 'id="changes-body"' in output
    assert 'id="reviewed-count"' in output
    assert 'data-review-status="NVDA"' in output
    assert 'data-note-preview="NVDA"' in output
    assert 'data-valuation-risk=' in output
    assert 'data-top-news-count=' in output
    assert 'stock-daily-notes' in output
    assert 'data-checklist="NVDA"' in output
    assert "Manage" in output
    assert "Next earnings" in output
    assert "Valuation risk" in output
    assert "Exports: watchlist TXT" in output


def test_render_html_report_marks_imminent_earnings() -> None:
    earnings = EarningsDate(
        ticker="NVDA",
        company_name="NVIDIA Corporation",
        earnings_date=date(2026, 4, 28),  # same as report_date → today
        time_of_day="unknown",
        fiscal_quarter=None,
        fiscal_year=None,
        eps_estimate=None,
        revenue_estimate=None,
        source="yfinance",
        source_retrieved_at=datetime(2026, 4, 28, 7, 0, tzinfo=timezone.utc),
    )
    report = _sample_report()
    report.ticker_reports[0] = TickerReport(
        ticker=report.ticker_reports[0].ticker,
        articles=report.ticker_reports[0].articles,
        x_signals=[],
        valuation=report.ticker_reports[0].valuation,
        earnings=earnings,
        warnings=report.ticker_reports[0].warnings,
    )

    output = render_html_report(report)

    assert "earnings-pill imminent" in output
    assert ">today<" in output


def test_days_until_handles_relative_dates() -> None:
    anchor = date(2026, 4, 28)

    assert days_until(date(2026, 4, 28), anchor) == "today"
    assert days_until(date(2026, 4, 29), anchor) == "tomorrow"
    assert days_until(date(2026, 5, 5), anchor) == "in 7d"
    assert days_until(date(2026, 4, 27), anchor) == "1d ago"
    assert days_until(None, anchor) == ""


def test_earnings_delta_returns_integer_days_or_none() -> None:
    today = date(2026, 4, 28)
    earnings = EarningsDate(
        ticker="NVDA", company_name="NVIDIA",
        earnings_date=date(2026, 5, 1), time_of_day="unknown",
        fiscal_quarter=None, fiscal_year=None,
        eps_estimate=None, revenue_estimate=None, source="yfinance",
        source_retrieved_at=datetime(2026, 4, 28, tzinfo=timezone.utc),
    )
    item = TickerReport(
        ticker=TickerConfig(symbol="NVDA", company_name="NVIDIA"),
        articles=[], x_signals=[], valuation=None, earnings=earnings,
    )

    assert earnings_delta(item, today) == 3
    assert earnings_delta(
        TickerReport(
            ticker=TickerConfig(symbol="X", company_name="X"),
            articles=[], x_signals=[], valuation=None, earnings=None,
        ),
        today,
    ) is None


def test_earnings_urgency_buckets() -> None:
    anchor = date(2026, 4, 28)

    assert earnings_urgency(date(2026, 4, 28), anchor) == "imminent"
    assert earnings_urgency(date(2026, 4, 29), anchor) == "imminent"
    assert earnings_urgency(date(2026, 4, 30), anchor) == "soon"
    assert earnings_urgency(date(2026, 5, 5), anchor) == "week"
    assert earnings_urgency(date(2026, 5, 20), anchor) == "later"
    assert earnings_urgency(date(2026, 4, 1), anchor) == "past"


def test_pe_class_buckets() -> None:
    assert pe_class(15) == ""
    assert pe_class(75) == "elevated"
    assert pe_class(150) == "high"
    assert pe_class(250) == "extreme"
    assert pe_class(-3) == "neg"
    assert pe_class(None) == ""
    assert pe_class(float("nan")) == ""


def test_daily_change_pct_computes_from_last_and_previous() -> None:
    from stock_daily_research.report import daily_change_pct

    item = TickerReport(
        ticker=TickerConfig(symbol="NVDA", company_name="NVIDIA"),
        articles=[], x_signals=[], earnings=None,
        valuation=ValuationSnapshot(
            ticker="NVDA", as_of_date=date(2026, 4, 28), source="yfinance",
            metrics={"last_close": 138.40, "previous_close": 135.10},
            retrieved_at=datetime(2026, 4, 28, tzinfo=timezone.utc),
        ),
    )
    chg = daily_change_pct(item)
    assert chg is not None
    assert abs(chg - 2.443) < 0.01

    # Missing previous_close → None
    item_no_prev = TickerReport(
        ticker=TickerConfig(symbol="X", company_name="X"),
        articles=[], x_signals=[], earnings=None,
        valuation=ValuationSnapshot(
            ticker="X", as_of_date=date(2026, 4, 28), source="yfinance",
            metrics={"last_close": 100.0},
            retrieved_at=datetime(2026, 4, 28, tzinfo=timezone.utc),
        ),
    )
    assert daily_change_pct(item_no_prev) is None


def test_from_52w_high_pct_negative_when_below() -> None:
    from stock_daily_research.report import from_52w_high_pct

    item = TickerReport(
        ticker=TickerConfig(symbol="X", company_name="X"),
        articles=[], x_signals=[], earnings=None,
        valuation=ValuationSnapshot(
            ticker="X", as_of_date=date(2026, 4, 28), source="yfinance",
            metrics={"last_close": 80.0, "fifty_two_week_high": 100.0},
            retrieved_at=datetime(2026, 4, 28, tzinfo=timezone.utc),
        ),
    )
    pct = from_52w_high_pct(item)
    assert pct is not None
    assert abs(pct - (-20.0)) < 0.01


def test_format_pct_signs_correctly() -> None:
    from stock_daily_research.report import change_class, format_pct

    assert format_pct(2.43) == "+2.43%"
    assert format_pct(-1.5) == "-1.50%"
    assert format_pct(0) == "+0.00%"
    assert format_pct(None) == "N/A"
    assert format_pct(float("nan")) == "N/A"
    assert format_pct(2.0, sign=False) == "2.00%"

    assert change_class(2.5) == "pos"
    assert change_class(-3) == "neg"
    assert change_class(0) == "flat"
    assert change_class(None) == ""


def test_ma_signals_use_unified_grammar() -> None:
    from stock_daily_research.report import ma_signals

    def make(metrics):
        return TickerReport(
            ticker=TickerConfig(symbol="X", company_name="X Inc"),
            articles=[], x_signals=[], earnings=None,
            valuation=ValuationSnapshot(
                ticker="X", as_of_date=date(2026, 4, 28), source="yfinance",
                metrics=metrics,
                retrieved_at=datetime(2026, 4, 28, tzinfo=timezone.utc),
            ),
        )

    # Above all three MAs — uniform "Above 20D / 60D / 120D"
    sigs = ma_signals(make({
        "last_close": 110.0, "sma_5": 108.0, "sma_20": 100.0,
        "sma_60": 95.0, "sma_120": 90.0,
    }))
    assert "Above 20D / 60D / 120D" in sigs

    # Below all — uniform "Below 20D / 60D / 120D"
    sigs = ma_signals(make({
        "last_close": 80.0, "sma_5": 82.0, "sma_20": 90.0,
        "sma_60": 95.0, "sma_120": 100.0,
    }))
    assert "Below 20D / 60D / 120D" in sigs

    # Mixed — "Above 20D / 60D, below 120D"
    sigs = ma_signals(make({
        "last_close": 95.0, "sma_5": 95.0, "sma_20": 90.0,
        "sma_60": 92.0, "sma_120": 100.0,
    }))
    assert "Above 20D / 60D, below 120D" in sigs

    # Near 20D support — within +2% above
    sigs = ma_signals(make({
        "last_close": 101.0, "sma_5": 102.0, "sma_20": 100.0,
        "sma_60": 95.0, "sma_120": 90.0,
    }))
    assert "Near 20D support" in sigs

    # 5D well below 20D
    sigs = ma_signals(make({
        "last_close": 110.0, "sma_5": 95.0, "sma_20": 105.0,
        "sma_60": 100.0, "sma_120": 95.0,
    }))
    assert "5D below 20D" in sigs

    # Insufficient data — empty
    assert ma_signals(make({"last_close": 100.0})) == []


def test_ticker_insights_separates_trend_from_setup_and_risk() -> None:
    item = TickerReport(
        ticker=TickerConfig(symbol="X", company_name="X Inc"),
        articles=[], x_signals=[], earnings=None,
        valuation=ValuationSnapshot(
            ticker="X", as_of_date=date(2026, 4, 28), source="yfinance",
            metrics={
                "last_close": 80.0, "previous_close": 80.0,
                "sma_5": 82.0, "sma_20": 90.0, "sma_60": 95.0, "sma_120": 100.0,
            },
            retrieved_at=datetime(2026, 4, 28, tzinfo=timezone.utc),
        ),
    )
    insights = ticker_insights(item, anchor=date(2026, 4, 28))

    setup_text = " · ".join(insights["setup"])
    risk_text = " · ".join(insights["risk"])
    trend_text = " · ".join(insights["trend"])

    # MA signals live in their own row, never in setup or risk
    assert "Below 20D / 60D / 120D" in trend_text
    assert "Below" not in setup_text
    assert "Below 20D" not in risk_text
    # Bearish trend tagged with down tone
    assert insights["trend_tone"] == "down"
    # Tooltip carries the distance numbers
    assert "20D" in insights["trend_title"]


def test_ma_distances_returns_signed_pct() -> None:
    from stock_daily_research.report import ma_distances, format_ma_distances

    item = TickerReport(
        ticker=TickerConfig(symbol="X", company_name="X"),
        articles=[], x_signals=[], earnings=None,
        valuation=ValuationSnapshot(
            ticker="X", as_of_date=date(2026, 4, 28), source="yfinance",
            metrics={"last_close": 110.0, "sma_20": 100.0, "sma_60": 105.0},
            retrieved_at=datetime(2026, 4, 28, tzinfo=timezone.utc),
        ),
    )
    distances = ma_distances(item)
    assert distances["20D"] == 10.0
    assert abs(distances["60D"] - 4.76) < 0.01

    label = format_ma_distances(item)
    assert "20D +10.0%" in label
    assert "60D +" in label


def test_trend_tone_from_signals() -> None:
    from stock_daily_research.report import trend_tone

    assert trend_tone(["Above 20D / 60D / 120D"]) == "up"
    assert trend_tone(["Below 20D / 60D / 120D"]) == "down"
    assert trend_tone(["Above 20D / 60D, below 120D"]) == "mixed"
    assert trend_tone([]) == ""


def test_news_rationale_maps_event_types() -> None:
    from stock_daily_research.report import news_rationale

    class FakeArticle:
        def __init__(self, ev):
            self.event_type = ev

    assert news_rationale(FakeArticle("earnings")) == "Earnings read-through"
    assert news_rationale(FakeArticle("ai")) == "AI / capex implication"
    assert news_rationale(FakeArticle("deal")) == "Strategic positioning"
    assert news_rationale(FakeArticle("regulation")) == "Regulatory overhang"
    # Unknown event_type → empty
    assert news_rationale(FakeArticle("unknown_thing")) == ""


def test_overextended_tickers_requires_two_of_three_flags() -> None:
    from stock_daily_research.report import overextended_tickers

    def make(symbol, metrics):
        return TickerReport(
            ticker=TickerConfig(symbol=symbol, company_name=symbol),
            articles=[], x_signals=[], earnings=None,
            valuation=ValuationSnapshot(
                ticker=symbol, as_of_date=date(2026, 4, 28), source="yfinance",
                metrics=metrics,
                retrieved_at=datetime(2026, 4, 28, tzinfo=timezone.utc),
            ),
        )

    # All 3 flags
    all_three = make("ALL3", {
        "rsi_14": 75.0, "last_close": 105.0,
        "fifty_two_week_high": 106.0, "trailing_pe": 150.0,
    })
    # 2 flags: RSI + near high
    two = make("TWO", {
        "rsi_14": 72.0, "last_close": 100.0,
        "fifty_two_week_high": 102.0, "trailing_pe": 25.0,
    })
    # 1 flag only — not enough
    one = make("ONE", {
        "rsi_14": 75.0, "last_close": 80.0,
        "fifty_two_week_high": 130.0, "trailing_pe": 25.0,
    })
    # zero
    none = make("CALM", {
        "rsi_14": 50.0, "last_close": 80.0,
        "fifty_two_week_high": 100.0, "trailing_pe": 20.0,
    })

    report = DailyReport(
        report_date=date(2026, 4, 28),
        generated_at=datetime(2026, 4, 28, tzinfo=timezone.utc),
        ticker_reports=[all_three, two, one, none],
    )

    out = overextended_tickers(report)
    symbols = [entry["item"].ticker.symbol for entry in out]
    assert symbols == ["ALL3", "TWO"]  # ALL3 has score 3, TWO has 2; ONE/CALM filtered out
    assert out[0]["score"] == 3
    assert out[1]["score"] == 2


def test_earnings_action_routes_by_timing_and_rsi() -> None:
    from stock_daily_research.report import earnings_action

    def make(earnings_date, rsi=None):
        metrics = {"rsi_14": rsi} if rsi is not None else {}
        return TickerReport(
            ticker=TickerConfig(symbol="X", company_name="X"),
            articles=[], x_signals=[],
            valuation=ValuationSnapshot(
                ticker="X", as_of_date=date(2026, 4, 28), source="yfinance",
                metrics=metrics,
                retrieved_at=datetime(2026, 4, 28, tzinfo=timezone.utc),
            ) if rsi is not None else None,
            earnings=EarningsDate(
                ticker="X", company_name="X",
                earnings_date=earnings_date, time_of_day="unknown",
                fiscal_quarter=None, fiscal_year=None,
                eps_estimate=None, revenue_estimate=None, source="yfinance",
                source_retrieved_at=datetime(2026, 4, 28, tzinfo=timezone.utc),
            ) if earnings_date else None,
        )

    today = date(2026, 4, 28)

    assert earnings_action(make(today, rsi=75), today) == "Wait reaction (overextended)"
    assert earnings_action(make(today, rsi=25), today) == "Watch capitulation"
    assert earnings_action(make(today, rsi=50), today) == "Watch reaction"
    assert earnings_action(make(date(2026, 4, 29)), today) == "Prepare plan"
    assert earnings_action(make(date(2026, 5, 3)), today) == "Build thesis"
    assert earnings_action(make(date(2026, 4, 27)), today) == "Review outcome"
    assert earnings_action(make(date(2026, 4, 21)), today) == "Review outcome"  # 7d ago boundary
    assert earnings_action(make(date(2026, 4, 20)), today) is None  # outside window
    assert earnings_action(make(None), today) is None


def test_post_earnings_status_window() -> None:
    from stock_daily_research.report import post_earnings_status

    def make(earnings_date):
        return TickerReport(
            ticker=TickerConfig(symbol="X", company_name="X"),
            articles=[], x_signals=[], valuation=None,
            earnings=EarningsDate(
                ticker="X", company_name="X",
                earnings_date=earnings_date, time_of_day="unknown",
                fiscal_quarter=None, fiscal_year=None,
                eps_estimate=None, revenue_estimate=None, source="yfinance",
                source_retrieved_at=datetime(2026, 4, 28, tzinfo=timezone.utc),
            ) if earnings_date else None,
        )

    today = date(2026, 4, 28)

    # 1 day after earnings → banner shows
    status = post_earnings_status(make(date(2026, 4, 27)), today)
    assert status is not None
    assert status["days_ago"] == 1

    # 7 days after — still in window
    status = post_earnings_status(make(date(2026, 4, 21)), today)
    assert status is not None
    assert status["days_ago"] == 7

    # 8 days — past window
    assert post_earnings_status(make(date(2026, 4, 20)), today) is None

    # Earnings today (delta 0) — pre-earnings, no banner
    assert post_earnings_status(make(today), today) is None

    # Future earnings — no banner
    assert post_earnings_status(make(date(2026, 5, 1)), today) is None

    # No earnings → None
    assert post_earnings_status(make(None), today) is None


def test_sectors_in_use_collects_distinct_sorted_sectors() -> None:
    from stock_daily_research.report import sectors_in_use

    def make(symbol, sector):
        return TickerReport(
            ticker=TickerConfig(symbol=symbol, company_name=symbol),
            articles=[], x_signals=[], earnings=None,
            valuation=ValuationSnapshot(
                ticker=symbol, as_of_date=date(2026, 4, 28), source="yfinance",
                metrics={"sector": sector} if sector else {},
                retrieved_at=datetime(2026, 4, 28, tzinfo=timezone.utc),
            ),
        )

    report = DailyReport(
        report_date=date(2026, 4, 28),
        generated_at=datetime(2026, 4, 28, tzinfo=timezone.utc),
        ticker_reports=[
            make("NVDA", "Technology"),
            make("MSFT", "Technology"),
            make("XOM", "Energy"),
            make("UNK", None),
        ],
    )

    assert sectors_in_use(report) == ["Energy", "Technology"]


def test_event_label_translates_known_keys() -> None:
    assert event_label("earnings") == "Earnings"
    assert event_label("deal") == "Deal"
    assert event_label("analyst") == "Analyst"
    assert event_label("regulation") == "Regulation"
    assert event_label("market") == "Market"
    # Unknown falls back to title case
    assert event_label("unknown_thing") == "Unknown Thing"


def test_news_tier_buckets() -> None:
    class FakeArticle:
        def __init__(self, score):
            self.importance_score = score

    assert news_tier(FakeArticle(1.2)) == "top"
    assert news_tier(FakeArticle(0.95)) == "primary"
    assert news_tier(FakeArticle(0.7)) == "primary"
    assert news_tier(FakeArticle(0.4)) == "minor"


def test_important_news_assigns_tier_quotas() -> None:
    """Top tier is capped at 3 even when many articles share importance ≥ 1.0."""
    today = date(2026, 4, 28)
    articles = [
        NewsArticle(
            ticker="X", title=f"Headline {i}", source="Reuters",
            domain="reuters.com",
            published_at=datetime(2026, 4, 27, tzinfo=timezone.utc),
            url=f"https://x/{i}", summary="",
            event_type="earnings", importance_score=1.2,
        )
        for i in range(10)
    ]
    report = DailyReport(
        report_date=today,
        generated_at=datetime(2026, 4, 28, tzinfo=timezone.utc),
        ticker_reports=[
            TickerReport(
                ticker=TickerConfig(symbol="X", company_name="X Corp"),
                articles=articles, x_signals=[], valuation=None, earnings=None,
            ),
        ],
    )

    triples = important_news(report, limit=10)
    tiers = [t for _, _, t in triples]

    assert tiers.count("top") == 3
    assert tiers.count("primary") == 5  # positions 3..7
    assert tiers.count("minor") == 2


def test_important_news_curates_visible_top_five_across_tickers() -> None:
    today = date(2026, 4, 28)

    def article(ticker: str, idx: int, score: float = 1.0, event_type: str = "earnings") -> NewsArticle:
        return NewsArticle(
            ticker=ticker,
            title=f"{ticker} headline {idx}",
            source="Reuters",
            domain="reuters.com",
            published_at=datetime(2026, 4, 27, tzinfo=timezone.utc),
            url=f"https://example.com/{ticker}/{idx}",
            summary="",
            event_type=event_type,
            importance_score=score,
        )

    report = DailyReport(
        report_date=today,
        generated_at=datetime(2026, 4, 28, tzinfo=timezone.utc),
        ticker_reports=[
            TickerReport(
                ticker=TickerConfig(symbol="A", company_name="A"),
                articles=[article("A", i, 1.2) for i in range(5)],
                x_signals=[],
                valuation=None,
                earnings=None,
            ),
            TickerReport(
                ticker=TickerConfig(symbol="B", company_name="B"),
                articles=[article("B", 1, 1.1), article("B", 2, 1.05)],
                x_signals=[],
                valuation=None,
                earnings=None,
            ),
        ],
    )

    top_five_symbols = [item.ticker.symbol for item, _article, _tier in important_news(report, limit=7)[:5]]

    assert top_five_symbols.count("B") == 2
    assert top_five_symbols.count("A") <= 3


def test_hero_items_groups_imminent_earnings_by_day() -> None:
    earnings_today = EarningsDate(
        ticker="NVDA", company_name="NVIDIA Corporation",
        earnings_date=date(2026, 4, 28),
        time_of_day="unknown", fiscal_quarter=None, fiscal_year=None,
        eps_estimate=None, revenue_estimate=None, source="yfinance",
        source_retrieved_at=datetime(2026, 4, 28, tzinfo=timezone.utc),
    )
    earnings_tomorrow = EarningsDate(
        ticker="MSFT", company_name="Microsoft Corporation",
        earnings_date=date(2026, 4, 29),
        time_of_day="unknown", fiscal_quarter=None, fiscal_year=None,
        eps_estimate=None, revenue_estimate=None, source="yfinance",
        source_retrieved_at=datetime(2026, 4, 28, tzinfo=timezone.utc),
    )

    report = DailyReport(
        report_date=date(2026, 4, 28),
        generated_at=datetime(2026, 4, 28, tzinfo=timezone.utc),
        ticker_reports=[
            TickerReport(
                ticker=TickerConfig(symbol="NVDA", company_name="NVIDIA Corporation"),
                articles=[], x_signals=[], valuation=None, earnings=earnings_today,
            ),
            TickerReport(
                ticker=TickerConfig(symbol="MSFT", company_name="Microsoft Corporation"),
                articles=[], x_signals=[], valuation=None, earnings=earnings_tomorrow,
            ),
        ],
    )

    items = hero_items(report)

    assert len(items) >= 1
    today_item = items[0]
    assert today_item["tone"] == "imminent"
    assert "NVDA" in today_item["headline"]
    assert "today" in today_item["label"]


def test_hero_items_falls_back_to_top_news_when_no_imminent() -> None:
    article = NewsArticle(
        ticker="NVDA", title="Nvidia raises full-year guidance",
        source="Reuters", domain="reuters.com",
        published_at=datetime(2026, 4, 27, tzinfo=timezone.utc),
        url="https://reuters.com/x", summary="",
        event_type="guidance", importance_score=1.2,
    )
    report = DailyReport(
        report_date=date(2026, 4, 28),
        generated_at=datetime(2026, 4, 28, tzinfo=timezone.utc),
        ticker_reports=[
            TickerReport(
                ticker=TickerConfig(symbol="NVDA", company_name="NVIDIA Corporation"),
                articles=[article], x_signals=[], valuation=None, earnings=None,
            ),
        ],
    )

    items = hero_items(report)

    assert len(items) == 1
    assert items[0]["kind"] == "news"
    assert "guidance" in items[0]["headline"].lower()


def test_ticker_insights_summarizes_setup_and_risk() -> None:
    earnings = EarningsDate(
        ticker="NVDA", company_name="NVIDIA Corporation",
        earnings_date=date(2026, 4, 29),  # tomorrow
        time_of_day="unknown", fiscal_quarter=None, fiscal_year=None,
        eps_estimate=None, revenue_estimate=None, source="yfinance",
        source_retrieved_at=datetime(2026, 4, 28, tzinfo=timezone.utc),
    )
    valuation = ValuationSnapshot(
        ticker="NVDA", as_of_date=date(2026, 4, 28), source="yfinance",
        metrics={"trailing_pe": 250.0, "forward_pe": 50.0, "rsi_14": 74.0},
        retrieved_at=datetime(2026, 4, 28, tzinfo=timezone.utc),
    )
    item = TickerReport(
        ticker=TickerConfig(symbol="NVDA", company_name="NVIDIA Corporation", keywords=["GPU", "AI", "data center"]),
        articles=[],
        x_signals=[],
        valuation=valuation,
        earnings=earnings,
    )

    insights = ticker_insights(item, anchor=date(2026, 4, 28))

    assert any("Earnings tomorrow" in s for s in insights["setup"])
    assert any("Trailing P/E 250" in r for r in insights["risk"])
    assert any("RSI 74 overbought" in r for r in insights["risk"])
    assert insights["watch"] == ["GPU", "AI", "data center"]


def test_build_summary_includes_hot_count() -> None:
    today = date(2026, 4, 28)
    earnings_now = EarningsDate(
        ticker="NVDA", company_name="NVIDIA",
        earnings_date=today, time_of_day="unknown",
        fiscal_quarter=None, fiscal_year=None,
        eps_estimate=None, revenue_estimate=None, source="yfinance",
        source_retrieved_at=datetime(2026, 4, 28, tzinfo=timezone.utc),
    )
    report = DailyReport(
        report_date=today,
        generated_at=datetime(2026, 4, 28, tzinfo=timezone.utc),
        ticker_reports=[
            TickerReport(
                ticker=TickerConfig(symbol="NVDA", company_name="NVIDIA"),
                articles=[], x_signals=[], valuation=None, earnings=earnings_now,
            ),
            TickerReport(
                ticker=TickerConfig(symbol="X", company_name="X"),
                articles=[], x_signals=[],
                valuation=ValuationSnapshot(
                    ticker="X", as_of_date=today, source="yfinance",
                    metrics={"rsi_14": 25.0},
                    retrieved_at=datetime(2026, 4, 28, tzinfo=timezone.utc),
                ),
                earnings=None,
            ),
        ],
    )

    summary = build_summary(report)

    assert summary["hot_count"] == 1
    assert summary["ticker_count"] == 2
    assert summary["rsi_oversold_count"] == 1


def test_hero_items_surfaces_valuation_watch_when_room() -> None:
    today = date(2026, 4, 28)
    valuation = ValuationSnapshot(
        ticker="COHR", as_of_date=today, source="yfinance",
        metrics={"trailing_pe": 295.0, "forward_pe": 40.0},
        retrieved_at=datetime(2026, 4, 28, tzinfo=timezone.utc),
    )
    report = DailyReport(
        report_date=today,
        generated_at=datetime(2026, 4, 28, tzinfo=timezone.utc),
        ticker_reports=[
            TickerReport(
                ticker=TickerConfig(symbol="COHR", company_name="Coherent Corp."),
                articles=[], x_signals=[], valuation=valuation, earnings=None,
            ),
        ],
    )

    items = hero_items(report)

    valuation_cards = [it for it in items if it["kind"] == "valuation"]
    assert len(valuation_cards) == 1
    assert "COHR" in valuation_cards[0]["headline"]
    assert "P/E" in valuation_cards[0]["subtitle"]


def test_rule_alerts_and_priority_items_surface_risk_workflow() -> None:
    today = date(2026, 4, 28)
    earnings = EarningsDate(
        ticker="AMD", company_name="Advanced Micro Devices",
        earnings_date=date(2026, 5, 4), time_of_day="unknown",
        fiscal_quarter=None, fiscal_year=None,
        eps_estimate=None, revenue_estimate=None, source="yfinance",
        source_retrieved_at=datetime(2026, 4, 28, tzinfo=timezone.utc),
    )
    valuation = ValuationSnapshot(
        ticker="AMD", as_of_date=today, source="yfinance",
        metrics={"trailing_pe": 130.0},
        retrieved_at=datetime(2026, 4, 28, tzinfo=timezone.utc),
    )
    report = DailyReport(
        report_date=today,
        generated_at=datetime(2026, 4, 28, tzinfo=timezone.utc),
        ticker_reports=[
            TickerReport(
                ticker=TickerConfig(symbol="AMD", company_name="Advanced Micro Devices"),
                articles=[], x_signals=[], valuation=valuation, earnings=earnings,
            ),
        ],
    )

    alerts = rule_alerts(report)
    priorities = priority_items(report)

    assert len(alerts) == 1
    assert "AMD:" in alerts[0]["title"]
    assert "earnings in 6d" in alerts[0]["title"]
    assert "stretched valuation" in alerts[0]["title"]
    assert "Trailing P/E 130" in alerts[0]["detail"]
    assert "no trusted news" in alerts[0]["title"]
    assert priorities


def test_topic_tags_maps_watchlist_terms_to_dashboard_topics() -> None:
    item = TickerReport(
        ticker=TickerConfig(
            symbol="MU",
            company_name="Micron Technology",
            keywords=["memory", "DRAM", "HBM", "AI infrastructure"],
        ),
        articles=[],
        x_signals=[],
        valuation=None,
        earnings=None,
    )

    assert topic_tags(item) == ["ai", "memory"]


def test_compare_helpers_surface_risk_and_top_news_count() -> None:
    article = NewsArticle(
        ticker="PLTR", title="Palantir raises guidance",
        source="Reuters", domain="reuters.com",
        published_at=datetime(2026, 4, 28, tzinfo=timezone.utc),
        url="https://reuters.com/pltr", summary="",
        event_type="guidance", importance_score=1.1,
    )
    item = TickerReport(
        ticker=TickerConfig(symbol="PLTR", company_name="Palantir"),
        articles=[article],
        x_signals=[],
        valuation=ValuationSnapshot(
            ticker="PLTR", as_of_date=date(2026, 4, 28), source="yfinance",
            metrics={"trailing_pe": 219.0},
            retrieved_at=datetime(2026, 4, 28, tzinfo=timezone.utc),
        ),
        earnings=None,
    )

    assert valuation_risk_label(item) == "Extreme"
    assert top_news_count(item) == 1


def test_rsi_helpers_and_alerts_surface_technical_extremes() -> None:
    today = date(2026, 4, 28)
    item = TickerReport(
        ticker=TickerConfig(symbol="ARM", company_name="Arm Holdings"),
        articles=[],
        x_signals=[],
        valuation=ValuationSnapshot(
            ticker="ARM", as_of_date=today, source="yfinance",
            metrics={"forward_pe": 130.0, "rsi_14": 78.0},
            retrieved_at=datetime(2026, 4, 28, tzinfo=timezone.utc),
        ),
        earnings=None,
    )
    report = DailyReport(
        report_date=today,
        generated_at=datetime(2026, 4, 28, tzinfo=timezone.utc),
        ticker_reports=[item],
    )

    assert rsi_class(78.0) == "high"
    assert rsi_label(78.0) == "Overbought"
    alerts = rule_alerts(report)
    assert len(alerts) == 1
    assert "overbought technicals" in alerts[0]["title"]
    assert "RSI 14 78" in alerts[0]["detail"]


def test_card_state_classifies_by_urgency() -> None:
    today = date(2026, 4, 28)

    # Hot: imminent earnings
    earnings_now = EarningsDate(
        ticker="NVDA", company_name="NVIDIA",
        earnings_date=today, time_of_day="unknown",
        fiscal_quarter=None, fiscal_year=None,
        eps_estimate=None, revenue_estimate=None, source="yfinance",
        source_retrieved_at=datetime(2026, 4, 28, tzinfo=timezone.utc),
    )
    hot = TickerReport(
        ticker=TickerConfig(symbol="NVDA", company_name="NVIDIA"),
        articles=[], x_signals=[], valuation=None, earnings=earnings_now,
    )
    assert card_state(hot, today) == "hot"

    # Quiet: no news, no earnings, no warnings
    quiet = TickerReport(
        ticker=TickerConfig(symbol="X", company_name="X"),
        articles=[], x_signals=[], valuation=None, earnings=None,
    )
    assert card_state(quiet, today) == "quiet"

    # Warn: has data warnings
    warn = TickerReport(
        ticker=TickerConfig(symbol="Y", company_name="Y"),
        articles=[], x_signals=[], valuation=None, earnings=None,
        warnings=["Valuation fetch failed"],
    )
    assert card_state(warn, today) == "warn"


def test_card_state_earnings_tomorrow_is_warm_not_hot() -> None:
    """Hot is reserved for earnings TODAY only — tomorrow drops to warm."""
    today = date(2026, 4, 28)
    tomorrow = date(2026, 4, 29)
    earnings_tomorrow = EarningsDate(
        ticker="MSFT", company_name="Microsoft",
        earnings_date=tomorrow, time_of_day="unknown",
        fiscal_quarter=None, fiscal_year=None,
        eps_estimate=None, revenue_estimate=None, source="yfinance",
        source_retrieved_at=datetime(2026, 4, 28, tzinfo=timezone.utc),
    )
    item = TickerReport(
        ticker=TickerConfig(symbol="MSFT", company_name="Microsoft"),
        articles=[], x_signals=[], valuation=None, earnings=earnings_tomorrow,
    )
    assert card_state(item, today) == "warm"


def test_card_state_single_top_article_is_warm_not_hot() -> None:
    """Hot from news requires 2+ top-tier articles; one alone is warm."""
    today = date(2026, 4, 28)
    article = NewsArticle(
        ticker="NVDA", title="Nvidia delivers monster quarter",
        source="Reuters", domain="reuters.com",
        published_at=datetime(2026, 4, 28, tzinfo=timezone.utc),
        url="https://reuters.com/x", summary="",
        event_type="earnings", importance_score=1.2,
    )
    item = TickerReport(
        ticker=TickerConfig(symbol="NVDA", company_name="NVIDIA"),
        articles=[article], x_signals=[], valuation=None, earnings=None,
    )
    assert card_state(item, today) == "warm"


def test_important_news_dedupes_across_tickers() -> None:
    """Same article attributed to multiple tickers (because each name appears
    in the title) should appear only once in important_news."""
    article_a = NewsArticle(
        ticker="MSFT", title="Microsoft and Amazon strike cloud deal",
        source="Reuters", domain="reuters.com",
        published_at=datetime(2026, 4, 28, tzinfo=timezone.utc),
        url="https://reuters.com/cloud-deal", summary="",
        event_type="deal", importance_score=1.1,
    )
    article_b = NewsArticle(  # same URL, attributed to AMZN
        ticker="AMZN", title="Microsoft and Amazon strike cloud deal",
        source="Reuters", domain="reuters.com",
        published_at=datetime(2026, 4, 28, tzinfo=timezone.utc),
        url="https://reuters.com/cloud-deal", summary="",
        event_type="deal", importance_score=1.1,
    )
    report = DailyReport(
        report_date=date(2026, 4, 28),
        generated_at=datetime(2026, 4, 28, tzinfo=timezone.utc),
        ticker_reports=[
            TickerReport(
                ticker=TickerConfig(symbol="MSFT", company_name="Microsoft"),
                articles=[article_a], x_signals=[], valuation=None, earnings=None,
            ),
            TickerReport(
                ticker=TickerConfig(symbol="AMZN", company_name="Amazon"),
                articles=[article_b], x_signals=[], valuation=None, earnings=None,
            ),
        ],
    )

    triples = important_news(report)

    assert len(triples) == 1
    assert triples[0][1].url == "https://reuters.com/cloud-deal"


def _sample_report() -> DailyReport:
    return DailyReport(
        report_date=date(2026, 4, 28),
        generated_at=datetime(2026, 4, 28, 7, 0, tzinfo=timezone.utc),
        ticker_reports=[
            TickerReport(
                ticker=TickerConfig(symbol="NVDA", company_name="NVIDIA Corporation"),
                articles=[
                    NewsArticle(
                        ticker="NVDA",
                        title="Nvidia revenue beats",
                        source="Reuters",
                        domain="reuters.com",
                        published_at=datetime(2026, 4, 27, 12, tzinfo=timezone.utc),
                        url="https://reuters.com/x",
                        summary="",
                        event_type="earnings",
                        importance_score=1.2,
                    )
                ],
                x_signals=[],
                valuation=ValuationSnapshot(
                    ticker="NVDA",
                    as_of_date=date(2026, 4, 28),
                    source="yfinance",
                    metrics={"market_cap": 5_260_000_000_000, "trailing_pe": 44.21, "rsi_14": 62.5},
                    retrieved_at=datetime(2026, 4, 28, 7, 0, tzinfo=timezone.utc),
                ),
                earnings=None,
                warnings=["news flake"],
            )
        ],
        warnings=["global warn"],
        economic_events=[
            EconomicEvent(
                name="FOMC Rate Decision",
                category="rates",
                event_datetime=datetime(2026, 4, 30, 2, 0, tzinfo=timezone.utc),
                source="Federal Reserve",
                source_url="https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm",
                notes="Rate decision / statement expected at 2:00 PM ET.",
                source_time_label="2026-04-29 02:00 PM ET",
            )
        ],
        market_sentiment=MarketSentiment(
            score=68,
            label="Greed",
            source="yfinance proxy",
            retrieved_at=datetime(2026, 4, 28, 7, 0, tzinfo=timezone.utc),
            components=[
                MarketSentimentComponent(
                    name="SPY 20D momentum",
                    score=70.0,
                    label="risk-on",
                    detail="+5.0% over 20 sessions",
                )
            ],
        ),
    )
