from dataclasses import replace
from datetime import date, datetime, timezone

from stock_daily_research.models import (
    DailyReport,
    EconomicEvent,
    EarningsDate,
    MarketContext,
    MarketSentiment,
    MarketSentimentComponent,
    NewsArticle,
    PostEarningsReview,
    PositionConfig,
    PremarketMove,
    PremarketSnapshot,
    RateLevel,
    TickerConfig,
    TickerHistoryPoint,
    TickerResearchState,
    TickerReport,
    ValuationSnapshot,
)
from stock_daily_research.report import (
    build_summary,
    book_today_summary,
    capital_allocation_queue,
    card_state,
    days_until,
    earnings_delta,
    earnings_urgency,
    eps_power_summary,
    eps_revision_class,
    event_label,
    hero_items,
    important_news,
    macro_risk_meter,
    morning_briefing_cards,
    news_tier,
    pe_class,
    position_view,
    post_earnings_items,
    pre_earnings_card,
    premarket_triage,
    priority_items,
    quality_of_move,
    render_html_report,
    render_markdown_report,
    rsi_class,
    rsi_label,
    rule_alerts,
    sector_leadership,
    sort_by_market_cap,
    source_reliability,
    topic_tags,
    todays_catalysts,
    todays_focus,
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
    assert "Generated: 2026-04-28 15:00 Taiwan Time (UTC+8)" in output
    assert "Market data timestamp: 2026-04-28 11:00 UTC" in output
    assert "global warn" in output
    assert "news flake" in output


def test_render_html_report_includes_visual_sections() -> None:
    output = render_html_report(_sample_report())

    assert "<!doctype html>" in output
    assert "Regime" in output
    assert "Premarket tone" in output
    assert "Top risk" in output
    assert "Focus" in output
    assert "Macro Calendar" in output
    assert "Overnight / Premarket" in output
    assert "Today&#39;s Focus" in output or "Today's Focus" in output
    assert "focus-rank" in output
    assert "section-primary" in output
    assert "Today's Catalysts" in output
    assert "Sector Leadership" in output
    assert "Macro risk meter" in output
    assert "FOMC Rate Decision" in output
    assert "Valuation Snapshot" in output
    assert "TTM EPS" in output
    assert "FY1 EPS Rev 30D" in output
    assert "FY1 Revenue Rev 30D" in output
    assert "Next Q Revenue Rev 30D" in output
    assert "My Book Today" in output
    assert "My Book Impact Today" in output
    assert "Ticker Cards" in output
    assert "Nvidia revenue beats" in output
    assert "+4.00% on 1.8x volume" in output
    assert "5.26T" in output
    assert "Position &amp; book" in output
    assert "What Changed Since Last Run" in output
    assert "Generated: 2026-04-28 15:00 Taiwan Time (UTC+8)" in output
    assert "2026-04-28 15:00 TWN / UTC+8" in output
    assert "Market data timestamp: 2026-04-28 11:00 UTC" in output
    assert "Capital Allocation Queue" in output
    assert "No action before event" in output
    assert "Avoid chase" in output
    assert "window.claude.complete" in output


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
    assert 'stock-daily-draft-notes' in output
    assert 'data-checklist="NVDA"' in output
    assert 'data-thesis="NVDA"' in output
    assert 'data-thesis-trigger="NVDA"' in output
    assert "stock-daily-draft-thesis" in output
    assert "stock-daily-draft-thesis-triggers" in output
    assert "data-premarket-change=" in output
    assert "data-volume-x=" in output
    assert "data-position-weight=" in output
    assert "from-high-chip" in output
    assert "From high -5.45%" in output
    assert "data-revenue-rev-30d=" in output
    assert "data-next-q-revenue-rev-30d=" in output
    assert "enhanceFocusFromLocalState" in output
    assert "thesis_trigger" in output
    assert "FY1 rev rev" in output
    assert "NextQ rev rev" in output
    assert "stock-daily-draft-post-earnings" in output
    assert "data-local-revisit-hero" in output
    assert "syncRevisitHero" in output
    assert "Manage" in output
    assert "Next earnings" in output
    assert "Valuation risk" in output
    assert "Exports: watchlist TXT" in output
    assert "Research Queue" in output
    assert "What Changed in 30d" in output


def test_render_html_report_seeds_sqlite_backed_research_state_and_history() -> None:
    base = _sample_report()
    report = replace(
        base,
        research_states={
            "NVDA": TickerResearchState(
                ticker="NVDA",
                tag="High conviction",
                thesis_state="active",
                thesis_trigger="guidance",
                note="Datacenter demand still broadening.",
                checklist=["earnings", "valuation", "news", "thesis"],
                revisit_date=date(2026, 4, 30),
                pinned=True,
                review_status="reviewed",
                last_reviewed_at=datetime(2026, 4, 28, 6, 0, tzinfo=timezone.utc),
            )
        },
        post_earnings_reviews={
            "NVDA": PostEarningsReview(
                ticker="NVDA",
                earnings_date=date(2026, 4, 27),
                eps="beat",
                revenue="beat",
                guide="up",
                conclusion="Thesis intact.",
                next_step="Watch valuation reaction.",
            )
        },
        ticker_history={
            "NVDA": [
                TickerHistoryPoint(
                    report_date=date(2026, 4, 28),
                    generated_at=datetime(2026, 4, 28, 7, 0, tzinfo=timezone.utc),
                    ticker="NVDA",
                    thesis_state="active",
                    review_status="reviewed",
                    news_count=1,
                    top_news_count=1,
                    valuation_risk="Elevated",
                    warning_count=1,
                    attention_score=14.0,
                    news_burst_score=1.5,
                ),
                TickerHistoryPoint(
                    report_date=date(2026, 4, 27),
                    generated_at=datetime(2026, 4, 27, 7, 0, tzinfo=timezone.utc),
                    ticker="NVDA",
                    thesis_state="building",
                    review_status="in-progress",
                    news_count=0,
                    top_news_count=0,
                    valuation_risk="None",
                    warning_count=0,
                    attention_score=4.0,
                    news_burst_score=0.0,
                ),
            ]
        },
        history_overview={
            "history_days": 45,
            "archive_dates": ["2026-04-28", "2026-04-27"],
        },
    )

    output = render_html_report(report)

    assert "Research timeline" in output
    assert "Review queue" in output
    assert "Recent thesis changes" in output
    assert "Archive" in output
    assert '"thesis_state": "active"' in output
    assert '"history_days": 45' in output
    assert "Thesis state changed" in output
    assert "Research memory" in output
    assert "Reviewed" in output


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
    assert eps_revision_class(1.2) == "pos"
    assert eps_revision_class(-1.2) == "neg"
    assert eps_revision_class(0.1) == "flat"


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


def test_portfolio_impact_summary_ranks_holdings() -> None:
    from stock_daily_research.report import portfolio_impact_summary
    from stock_daily_research.models import PositionConfig

    def holding(symbol, weight, last, prev):
        return TickerReport(
            ticker=TickerConfig(
                symbol=symbol, company_name=f"{symbol} Inc",
                position=PositionConfig(status="holding", portfolio_weight=weight),
            ),
            articles=[], x_signals=[], earnings=None,
            valuation=ValuationSnapshot(
                ticker=symbol, as_of_date=date(2026, 5, 12), source="yfinance",
                metrics={"last_close": last, "previous_close": prev},
                retrieved_at=datetime(2026, 5, 12, tzinfo=timezone.utc),
            ),
        )

    def watchlist(symbol):
        return TickerReport(
            ticker=TickerConfig(symbol=symbol, company_name=symbol),
            articles=[], x_signals=[], earnings=None, valuation=None,
        )

    report = DailyReport(
        report_date=date(2026, 5, 12),
        generated_at=datetime(2026, 5, 12, tzinfo=timezone.utc),
        ticker_reports=[
            holding("NVDA", 20.0, 110.0, 100.0),
            holding("MSFT", 15.0, 95.0, 100.0),
            holding("AAPL", 10.0, 101.0, 100.0),
            watchlist("AMZN"),
        ],
    )

    summary = portfolio_impact_summary(report)

    assert len(summary["holdings"]) == 3
    assert [r["symbol"] for r in summary["holdings"]] == ["NVDA", "MSFT", "AAPL"]
    assert summary["winners"][0]["symbol"] == "NVDA"
    assert summary["losers"][0]["symbol"] == "MSFT"
    assert abs(summary["total_impact_pct"] - 1.35) < 0.01


def test_portfolio_impact_summary_empty_when_no_holdings() -> None:
    from stock_daily_research.report import portfolio_impact_summary

    report = DailyReport(
        report_date=date(2026, 5, 12),
        generated_at=datetime(2026, 5, 12, tzinfo=timezone.utc),
        ticker_reports=[
            TickerReport(
                ticker=TickerConfig(symbol="NVDA", company_name="NVDA"),
                articles=[], x_signals=[], earnings=None, valuation=None,
            ),
        ],
    )
    summary = portfolio_impact_summary(report)
    assert summary["holdings"] == []
    assert summary["winners"] == []
    assert summary["losers"] == []


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


def test_relative_strength_computes_spread_vs_benchmarks() -> None:
    from stock_daily_research.report import format_relative_strength, relative_strength

    item = TickerReport(
        ticker=TickerConfig(symbol="X", company_name="X"),
        articles=[], x_signals=[], earnings=None,
        valuation=ValuationSnapshot(
            ticker="X", as_of_date=date(2026, 4, 28), source="yfinance",
            metrics={"return_20d": 8.3},
            retrieved_at=datetime(2026, 4, 28, tzinfo=timezone.utc),
        ),
    )
    rs = relative_strength(item, {"spy_20d": 2.1, "qqq_20d": 5.5})
    assert rs == {"vs_spy": 6.2, "vs_qqq": 2.8}

    phrases = format_relative_strength(rs)
    assert any("vs SPY 20D" in p for p in phrases)
    assert any("+6.2%" in p for p in phrases)


def _score_item(metrics: dict) -> TickerReport:
    return TickerReport(
        ticker=TickerConfig(symbol="X", company_name="X Inc"),
        articles=[], x_signals=[], earnings=None,
        valuation=ValuationSnapshot(
            ticker="X", as_of_date=date(2026, 5, 12), source="yfinance",
            metrics=metrics,
            retrieved_at=datetime(2026, 5, 12, tzinfo=timezone.utc),
        ),
    )


def test_right_side_score_breakout_confirmed() -> None:
    from stock_daily_research.report import right_side_score

    item = _score_item({
        "last_close": 120.0,
        "sma_20": 110.0, "sma_60": 100.0, "sma_120": 90.0,
        "return_20d": 12.0, "volume_vs_20d": 1.8,
        "fy1_eps_revision_30d": 3.0, "rsi_14": 60.0,
        "fifty_two_week_high": 130.0,
    })
    result = right_side_score(item, {"spy_20d": 2.0, "qqq_20d": 4.0})
    assert result is not None
    assert result["score"] >= 75
    assert result["status"] == "Breakout confirmed"
    assert result["tone"] == "up"


def test_right_side_score_extended_when_stretched() -> None:
    from stock_daily_research.report import right_side_score

    item = _score_item({
        "last_close": 130.0,
        "sma_20": 120.0, "sma_60": 110.0, "sma_120": 100.0,
        "return_20d": 8.0, "volume_vs_20d": 1.0,
        "fy1_eps_revision_30d": 1.0, "rsi_14": 76.0,
        "fifty_two_week_high": 130.5,
    })
    result = right_side_score(item, {"spy_20d": 2.0, "qqq_20d": 4.0})
    assert result is not None
    assert result["status"] == "Extended, do not chase"
    assert result["tone"] == "extended"


def test_right_side_score_avoid_when_all_red() -> None:
    from stock_daily_research.report import right_side_score

    item = _score_item({
        "last_close": 50.0,
        "sma_20": 60.0, "sma_60": 70.0, "sma_120": 80.0,
        "return_20d": -15.0, "volume_vs_20d": 0.4,
        "fy1_eps_revision_30d": -5.0, "rsi_14": 35.0,
        "forward_pe": 250.0,
        "fifty_two_week_high": 100.0,
    })
    result = right_side_score(item, {"spy_20d": 2.0, "qqq_20d": 3.0})
    assert result is not None
    # Below all MAs (-10), RS lagging (-5), low vol (-5), EPS rev down (-5), Extreme P/E (-10) → score = 15
    assert result["score"] < 25
    assert result["status"] == "Avoid"


def test_right_side_score_returns_none_without_valuation() -> None:
    from stock_daily_research.report import right_side_score

    item = TickerReport(
        ticker=TickerConfig(symbol="X", company_name="X"),
        articles=[], x_signals=[], earnings=None, valuation=None,
    )
    assert right_side_score(item, {"spy_20d": 1.0}) is None


def test_right_side_score_reasons_ordered_by_magnitude() -> None:
    from stock_daily_research.report import right_side_score

    item = _score_item({
        "last_close": 105.0,
        "sma_20": 100.0, "sma_60": 95.0, "sma_120": 90.0,
        "return_20d": 7.0, "volume_vs_20d": 1.6,
        "fy1_eps_revision_30d": 3.5, "rsi_14": 72.0,
        "fifty_two_week_high": 110.0,
    })
    result = right_side_score(item, {"spy_20d": 1.0, "qqq_20d": 2.0})
    assert result is not None
    # First reason should have the largest absolute magnitude
    magnitudes = [int(r.split()[0]) for r in result["reasons"]]
    abs_magnitudes = [abs(m) for m in magnitudes]
    assert abs_magnitudes == sorted(abs_magnitudes, reverse=True)


def test_relative_strength_skips_when_data_missing() -> None:
    from stock_daily_research.report import relative_strength

    item = TickerReport(
        ticker=TickerConfig(symbol="X", company_name="X"),
        articles=[], x_signals=[], earnings=None,
        valuation=None,
    )
    assert relative_strength(item, {"spy_20d": 1.0}) == {}


def test_ticker_insights_includes_rs_phrases() -> None:
    item = TickerReport(
        ticker=TickerConfig(symbol="NVDA", company_name="NVIDIA"),
        articles=[], x_signals=[], earnings=None,
        valuation=ValuationSnapshot(
            ticker="NVDA", as_of_date=date(2026, 4, 28), source="yfinance",
            metrics={"return_20d": 10.0, "last_close": 100.0},
            retrieved_at=datetime(2026, 4, 28, tzinfo=timezone.utc),
        ),
    )
    insights = ticker_insights(item, anchor=date(2026, 4, 28), benchmarks={"spy_20d": 2.0, "qqq_20d": 4.0})
    assert insights["rs"]
    assert insights["rs_tone"] == "up"
    assert any("vs SPY 20D" in p for p in insights["rs"])

    # No benchmarks → empty
    insights_no_bench = ticker_insights(item, anchor=date(2026, 4, 28))
    assert insights_no_bench["rs"] == []


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


def test_todays_catalysts_groups_earnings_macro_and_post_earnings() -> None:
    today = date(2026, 4, 28)
    before_open = EarningsDate(
        ticker="NVDA", company_name="NVIDIA",
        earnings_date=today, time_of_day="before_market",
        fiscal_quarter=None, fiscal_year=None,
        eps_estimate=None, revenue_estimate=None, source="yfinance",
        source_retrieved_at=datetime(2026, 4, 28, tzinfo=timezone.utc),
    )
    yesterday = EarningsDate(
        ticker="MSFT", company_name="Microsoft",
        earnings_date=date(2026, 4, 27), time_of_day="after_market",
        fiscal_quarter=None, fiscal_year=None,
        eps_estimate=None, revenue_estimate=None, source="yfinance",
        source_retrieved_at=datetime(2026, 4, 28, tzinfo=timezone.utc),
    )
    macro = EconomicEvent(
        name="FOMC Rate Decision",
        category="rates",
        event_datetime=datetime(2026, 4, 28, 18, 0, tzinfo=timezone.utc),
        source="Federal Reserve",
        source_url="https://example.com/fomc",
    )
    report = DailyReport(
        report_date=today,
        generated_at=datetime(2026, 4, 28, tzinfo=timezone.utc),
        ticker_reports=[
            TickerReport(TickerConfig("NVDA", "NVIDIA"), [], [], None, before_open),
            TickerReport(TickerConfig("MSFT", "Microsoft"), [], [], None, yesterday),
        ],
        economic_events=[macro],
    )

    catalysts = todays_catalysts(report)

    assert catalysts["before_open"][0].ticker.symbol == "NVDA"
    assert catalysts["macro"][0].name == "FOMC Rate Decision"
    assert catalysts["post_earnings"][0]["item"].ticker.symbol == "MSFT"
    assert post_earnings_items(report)[0]["days_ago"] == 1


def test_post_earnings_scoreboard_uses_metric_defaults_before_manual_review() -> None:
    today = date(2026, 4, 28)
    earnings = EarningsDate(
        ticker="MSFT", company_name="Microsoft",
        earnings_date=date(2026, 4, 27), time_of_day="after_market",
        fiscal_quarter=None, fiscal_year=None, eps_estimate=None, revenue_estimate=None,
        source="yfinance", source_retrieved_at=datetime(2026, 4, 28, tzinfo=timezone.utc),
    )
    report = DailyReport(
        report_date=today,
        generated_at=datetime(2026, 4, 28, tzinfo=timezone.utc),
        ticker_reports=[
            TickerReport(
                ticker=TickerConfig(symbol="MSFT", company_name="Microsoft"),
                articles=[], x_signals=[], earnings=earnings,
                valuation=ValuationSnapshot(
                    ticker="MSFT", as_of_date=today, source="yfinance",
                    metrics={
                        "latest_eps_surprise_pct": 6.5,
                        "latest_revenue_surprise_pct": -2.0,
                        "fy1_eps_revision_30d": 1.5,
                        "fy1_revenue_revision_30d": -0.8,
                    },
                    retrieved_at=datetime(2026, 4, 28, tzinfo=timezone.utc),
                ),
            )
        ],
    )

    output = render_html_report(report)

    assert 'data-pe-score-row="MSFT"' in output
    assert 'data-default="beat"' in output
    assert '+6.50%' in output
    assert 'data-default="-2.0"' in output


def test_quality_of_move_summarizes_volume_gap_and_atr() -> None:
    item = TickerReport(
        ticker=TickerConfig(symbol="X", company_name="X"),
        articles=[], x_signals=[], earnings=None,
        valuation=ValuationSnapshot(
            ticker="X", as_of_date=date(2026, 4, 28), source="yfinance",
            metrics={
                "last_close": 104.0,
                "previous_close": 100.0,
                "volume_vs_20d": 1.8,
                "gap_percent": 3.5,
                "move_vs_atr": 1.2,
                "eps_growth_pct": -2.0,
                "fy1_eps_revision_30d": -1.5,
            },
            retrieved_at=datetime(2026, 4, 28, tzinfo=timezone.utc),
        ),
    )

    quality = quality_of_move(item)

    assert "+4.00% on 1.8x volume" in quality
    assert "gap up 3.5%" in quality
    assert "move > 20D ATR (1.2x)" in quality


def test_eps_power_summary_labels_growth_and_revisions() -> None:
    item = TickerReport(
        ticker=TickerConfig(symbol="X", company_name="X"),
        articles=[], x_signals=[], earnings=None,
        valuation=ValuationSnapshot(
            ticker="X", as_of_date=date(2026, 4, 28), source="yfinance",
            metrics={"ttm_eps": 5.0, "next_fy_eps": 6.0, "eps_growth_pct": 20.0, "fy1_eps_revision_30d": 2.5},
            retrieved_at=datetime(2026, 4, 28, tzinfo=timezone.utc),
        ),
    )

    summary = eps_power_summary(item)

    assert "EPS: FY1 +20%" in summary
    assert "revisions up" in summary


def test_macro_risk_meter_buckets_pressure() -> None:
    ctx = MarketContext(
        rates=[
            RateLevel(name="5Y", last=4.5, prev=4.4, change=6.0, unit="bp"),
            RateLevel(name="10Y", last=4.7, prev=4.6, change=8.0, unit="bp"),
            RateLevel(name="DXY", last=104.5, prev=104.0, change=0.48, unit="%"),
            RateLevel(name="WTI", last=82.0, prev=80.0, change=2.5, unit="%"),
        ],
        retrieved_at=datetime(2026, 4, 28, tzinfo=timezone.utc),
    )

    rows = macro_risk_meter(ctx)
    levels = {row["name"]: row["level"] for row in rows}

    assert levels["Rates pressure"] == "high"
    assert levels["Dollar pressure"] == "medium"
    assert levels["Oil inflation pressure"] == "high"


def test_position_view_computes_pl_and_book_impact() -> None:
    item = TickerReport(
        ticker=TickerConfig(
            symbol="NVDA",
            company_name="NVIDIA",
            position=PositionConfig(status="holding", shares=10, avg_cost=80.0, portfolio_weight=5.0),
        ),
        articles=[], x_signals=[], earnings=None,
        valuation=ValuationSnapshot(
            ticker="NVDA", as_of_date=date(2026, 4, 28), source="yfinance",
            metrics={"last_close": 100.0, "previous_close": 95.0},
            retrieved_at=datetime(2026, 4, 28, tzinfo=timezone.utc),
        ),
    )

    view = position_view(item)

    assert view["position_size"] == 1000.0
    assert view["pl_pct"] == 25.0
    assert abs(view["book_impact"] - 0.263) < 0.01


def test_book_impact_ranking_prioritizes_holdings_by_estimated_impact() -> None:
    from stock_daily_research.report import book_impact_ranking

    def make(symbol, weight, move):
        return TickerReport(
            ticker=TickerConfig(
                symbol=symbol,
                company_name=symbol,
                position=PositionConfig(status="holding", portfolio_weight=weight),
            ),
            articles=[], x_signals=[], earnings=None,
            valuation=ValuationSnapshot(
                ticker=symbol, as_of_date=date(2026, 4, 28), source="yfinance",
                metrics={"last_close": 100.0 + move, "previous_close": 100.0},
                retrieved_at=datetime(2026, 4, 28, tzinfo=timezone.utc),
            ),
        )

    report = DailyReport(
        report_date=date(2026, 4, 28),
        generated_at=datetime(2026, 4, 28, tzinfo=timezone.utc),
        ticker_reports=[make("LOW", 2.0, 1.0), make("HIGH", 10.0, -3.0)],
    )

    rows = book_impact_ranking(report)

    assert rows[0]["item"].ticker.symbol == "HIGH"
    assert rows[0]["action"] == "Review now"


def test_book_today_summary_surfaces_portfolio_morning_cards() -> None:
    today = date(2026, 4, 28)

    def make(symbol, weight, move, *, pe=None, rsi=None, earnings_date=None):
        earnings = None
        if earnings_date:
            earnings = EarningsDate(
                ticker=symbol, company_name=symbol,
                earnings_date=earnings_date, time_of_day="unknown",
                fiscal_quarter=None, fiscal_year=None, eps_estimate=None, revenue_estimate=None,
                source="yfinance", source_retrieved_at=datetime(2026, 4, 28, tzinfo=timezone.utc),
            )
        return TickerReport(
            ticker=TickerConfig(
                symbol=symbol,
                company_name=symbol,
                position=PositionConfig(status="holding", portfolio_weight=weight),
            ),
            articles=[], x_signals=[], earnings=earnings,
            valuation=ValuationSnapshot(
                ticker=symbol, as_of_date=today, source="yfinance",
                metrics={"last_close": 100.0 + move, "previous_close": 100.0, "trailing_pe": pe, "rsi_14": rsi},
                retrieved_at=datetime(2026, 4, 28, tzinfo=timezone.utc),
            ),
        )

    report = DailyReport(
        report_date=today,
        generated_at=datetime(2026, 4, 28, tzinfo=timezone.utc),
        ticker_reports=[
            make("WIN", 12.0, 3.0),
            make("LOSS", 10.0, -4.0),
            make("RISK", 7.0, 0.5, pe=150.0, rsi=76.0),
            make("EVENT", 5.0, 0.2, earnings_date=today),
        ],
    )

    cards = book_today_summary(report)
    labels = [card["label"] for card in cards]

    assert "Biggest positive impact" in labels
    assert "Biggest negative impact" in labels
    assert "Highest risk holding" in labels
    assert "Holding with event soon" in labels


def test_todays_focus_combines_alerts_premarket_and_positions() -> None:
    today = date(2026, 4, 28)
    earnings = EarningsDate(
        ticker="NVDA", company_name="NVIDIA",
        earnings_date=today, time_of_day="unknown",
        fiscal_quarter=None, fiscal_year=None, eps_estimate=None, revenue_estimate=None,
        source="yfinance", source_retrieved_at=datetime(2026, 4, 28, tzinfo=timezone.utc),
    )
    item = TickerReport(
        ticker=TickerConfig(
            symbol="NVDA", company_name="NVIDIA",
            position=PositionConfig(status="holding", portfolio_weight=8.0),
        ),
        articles=[NewsArticle(
            ticker="NVDA", title="Nvidia earnings headline", source="Reuters", domain="reuters.com",
            published_at=datetime(2026, 4, 28, tzinfo=timezone.utc),
            url="https://example.com/nvda", summary="", event_type="earnings", importance_score=1.2,
        )],
        x_signals=[],
        valuation=ValuationSnapshot(
            ticker="NVDA", as_of_date=today, source="yfinance",
            metrics={"last_close": 110.0, "previous_close": 100.0, "rsi_14": 75.0, "trailing_pe": 130.0, "fy1_eps_revision_30d": -2.0},
            retrieved_at=datetime(2026, 4, 28, tzinfo=timezone.utc),
        ),
        earnings=earnings,
    )
    report = DailyReport(
        report_date=today,
        generated_at=datetime(2026, 4, 28, tzinfo=timezone.utc),
        ticker_reports=[item],
        premarket=PremarketSnapshot(
            retrieved_at=datetime(2026, 4, 28, tzinfo=timezone.utc),
            watchlist_movers=[PremarketMove("NVDA", "NVIDIA", 106.0, 100.0, 6.0, "pre-market")],
            gap_movers=[PremarketMove("NVDA", "NVIDIA", 106.0, 100.0, 6.0, "pre-market")],
        ),
    )

    focus = todays_focus(report)

    assert focus["review_first"][0]["item"].ticker.symbol == "NVDA"
    assert any("EPS rev" in reason for reason in focus["review_first"][0]["reasons"])
    assert focus["no_action_before_event"][0]["item"].ticker.symbol == "NVDA"
    assert any("no action before earnings review" in reason for reason in focus["no_action_before_event"][0]["reasons"])
    assert focus["avoid_chase"] == []


def test_capital_allocation_queue_grades_trade_actions() -> None:
    today = date(2026, 4, 28)

    def item(symbol: str, metrics: dict[str, float], earnings=None) -> TickerReport:
        return TickerReport(
            ticker=TickerConfig(symbol=symbol, company_name=symbol),
            articles=[],
            x_signals=[],
            valuation=ValuationSnapshot(
                ticker=symbol,
                as_of_date=today,
                source="yfinance",
                metrics=metrics,
                retrieved_at=datetime(2026, 4, 28, tzinfo=timezone.utc),
            ),
            earnings=earnings,
        )

    earnings = EarningsDate(
        ticker="EVT", company_name="EVT",
        earnings_date=today, time_of_day="unknown",
        fiscal_quarter=None, fiscal_year=None,
        eps_estimate=None, revenue_estimate=None,
        source="yfinance",
        source_retrieved_at=datetime(2026, 4, 28, tzinfo=timezone.utc),
    )
    report = DailyReport(
        report_date=today,
        generated_at=datetime(2026, 4, 28, tzinfo=timezone.utc),
        ticker_reports=[
            item("ADD", {
                "last_close": 110.0, "sma_20": 100.0, "sma_60": 95.0, "sma_120": 90.0,
                "volume_vs_20d": 1.8, "fy1_eps_revision_30d": 3.0, "rsi_14": 60.0,
                "forward_pe": 30.0, "fifty_two_week_high": 140.0,
            }),
            item("EVT", {"last_close": 100.0, "fy1_eps_revision_30d": 2.0, "rsi_14": 55.0}, earnings),
            item("CUT", {"last_close": 100.0, "fy1_eps_revision_30d": -2.0, "rsi_14": 55.0}),
        ],
        research_states={
            "ADD": TickerResearchState(ticker="ADD", thesis_state="active"),
            "EVT": TickerResearchState(ticker="EVT", thesis_state="active"),
            "CUT": TickerResearchState(ticker="CUT", thesis_state="weakening"),
        },
    )

    queue = capital_allocation_queue(report)

    assert queue["A"][0]["item"].ticker.symbol == "ADD"
    assert queue["C"][0]["item"].ticker.symbol == "EVT"
    assert queue["E"][0]["item"].ticker.symbol == "CUT"


def test_sector_leadership_and_premarket_triage() -> None:
    today = date(2026, 4, 28)
    nvda = TickerReport(
        ticker=TickerConfig(symbol="NVDA", company_name="NVIDIA", keywords=["GPU", "AI data center"]),
        articles=[NewsArticle(
            ticker="NVDA", title="Nvidia catalyst", source="Reuters", domain="reuters.com",
            published_at=datetime(2026, 4, 28, tzinfo=timezone.utc),
            url="https://example.com/nvda", summary="", event_type="product", importance_score=1.0,
        )],
        x_signals=[],
        valuation=ValuationSnapshot(
            ticker="NVDA", as_of_date=today, source="yfinance",
            metrics={"last_close": 104.0, "previous_close": 100.0, "return_5d": 6.0, "return_20d": 12.0, "move_vs_atr": 1.1, "volume_vs_20d": 1.8},
            retrieved_at=datetime(2026, 4, 28, tzinfo=timezone.utc),
        ),
        earnings=None,
    )
    quiet = TickerReport(
        ticker=TickerConfig(symbol="QUIET", company_name="Quiet Corp"),
        articles=[], x_signals=[],
        valuation=ValuationSnapshot(
            ticker="QUIET", as_of_date=today, source="yfinance",
            metrics={"last_close": 51.0, "previous_close": 50.0, "return_5d": 1.0, "return_20d": 2.0},
            retrieved_at=datetime(2026, 4, 28, tzinfo=timezone.utc),
        ),
        earnings=None,
    )
    report = DailyReport(
        report_date=today,
        generated_at=datetime(2026, 4, 28, tzinfo=timezone.utc),
        ticker_reports=[nvda, quiet],
        market_context=MarketContext(benchmark_returns={"spy_20d": 5.0}),
        premarket=PremarketSnapshot(
            retrieved_at=datetime(2026, 4, 28, tzinfo=timezone.utc),
            watchlist_movers=[
                PremarketMove("NVDA", "NVIDIA", 107.0, 100.0, 7.0, "pre-market"),
                PremarketMove("QUIET", "Quiet Corp", 51.0, 50.0, 2.0, "pre-market"),
            ],
        ),
    )

    groups = sector_leadership(report)
    triage = premarket_triage(report)

    assert any(row["label"] == "Semis" for row in groups)
    assert triage["catalyst_backed"][0]["item"].ticker.symbol == "NVDA"
    assert triage["catalyst_backed"][0]["headline_count"] == 1
    assert "trusted" in triage["catalyst_backed"][0]["source_tier"] or "tier" in triage["catalyst_backed"][0]["source_tier"]
    assert triage["unclear"][0]["item"].ticker.symbol == "QUIET"


def test_source_reliability_buckets_official_and_tier1() -> None:
    class Article:
        def __init__(self, domain, source=""):
            self.domain = domain
            self.source = source

    assert source_reliability(Article("sec.gov"))["tier"] == "official"
    assert source_reliability(Article("reuters.com"))["tier"] == "tier1"
    assert source_reliability(Article("example.com"))["tier"] == "trusted"


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
                ticker=TickerConfig(
                    symbol="NVDA",
                    company_name="NVIDIA Corporation",
                    position=PositionConfig(status="holding", portfolio_weight=10.0),
                ),
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
                ticker=TickerConfig(
                    symbol="NVDA",
                    company_name="NVIDIA Corporation",
                    position=PositionConfig(status="holding", portfolio_weight=10.0),
                ),
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


def test_morning_briefing_cards_build_four_first_screen_cards() -> None:
    cards = morning_briefing_cards(_sample_report())
    labels = [card["label"] for card in cards]

    assert labels == ["Regime", "Premarket tone", "Top risk", "Focus"]
    assert "QQQ" in str(cards[1]["headline"])
    assert cards[3]["anchor"] == "#todays-focus"


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


def test_rule_alerts_surface_stop_loss_distance() -> None:
    today = date(2026, 4, 28)
    report = DailyReport(
        report_date=today,
        generated_at=datetime(2026, 4, 28, tzinfo=timezone.utc),
        ticker_reports=[
            TickerReport(
                ticker=TickerConfig(
                    symbol="NVDA",
                    company_name="NVIDIA Corporation",
                    position=PositionConfig(status="holding", portfolio_weight=8.0, stop_loss=100.0),
                ),
                articles=[],
                x_signals=[],
                valuation=ValuationSnapshot(
                    ticker="NVDA",
                    as_of_date=today,
                    source="yfinance",
                    metrics={"last_close": 101.0},
                    retrieved_at=datetime(2026, 4, 28, tzinfo=timezone.utc),
                ),
                earnings=None,
            ),
        ],
    )

    alerts = rule_alerts(report)

    assert len(alerts) == 1
    assert "stop-loss alert" in alerts[0]["title"]
    assert "Last $101.00 is +1.00% from stop $100.00." in alerts[0]["detail"]
    assert "8.00% weight" in alerts[0]["detail"]
    assert alerts[0]["tone"] == "danger"


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
            metrics={"forward_pe": 130.0, "rsi_14": 78.0, "last_close": 97.0, "fifty_two_week_high": 100.0},
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
    assert "-3.00% from 52W high" in alerts[0]["detail"]


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
                ticker=TickerConfig(
                    symbol="NVDA",
                    company_name="NVIDIA Corporation",
                    position=PositionConfig(status="holding", portfolio_weight=10.0),
                ),
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
                    metrics={
                        "market_cap": 5_260_000_000_000,
                        "trailing_pe": 44.21,
                        "forward_pe": 32.0,
                        "ttm_eps": 4.2,
                        "next_fy_eps": 5.1,
                        "eps_growth_pct": 21.4,
                        "fy1_eps_revision_30d": 2.2,
                        "fy1_revenue_revision_30d": 3.4,
                        "next_q_revenue_revision_30d": 1.1,
                        "revenue_growth_pct": 18.0,
                        "rsi_14": 62.5,
                        "last_close": 104.0,
                        "previous_close": 100.0,
                        "fifty_two_week_high": 110.0,
                        "volume_vs_20d": 1.8,
                        "gap_percent": 3.5,
                        "atr_20_percent": 2.4,
                        "move_vs_atr": 1.2,
                    },
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
        market_context=MarketContext(
            rates=[
                RateLevel(name="10Y", last=4.7, prev=4.6, change=8.0, unit="bp"),
                RateLevel(name="DXY", last=104.5, prev=104.0, change=0.48, unit="%"),
                RateLevel(name="WTI", last=82.0, prev=80.0, change=2.5, unit="%"),
            ],
            retrieved_at=datetime(2026, 4, 28, 7, 0, tzinfo=timezone.utc),
        ),
        premarket=PremarketSnapshot(
            retrieved_at=datetime(2026, 4, 28, 11, 0, tzinfo=timezone.utc),
            benchmarks=[
                PremarketMove(
                    symbol="QQQ",
                    name="QQQ premarket",
                    last=450.0,
                    previous_close=445.0,
                    change_pct=1.12,
                    source="pre-market",
                ),
            ],
            watchlist_movers=[
                PremarketMove(
                    symbol="NVDA",
                    name="NVIDIA Corporation",
                    last=107.0,
                    previous_close=100.0,
                    change_pct=7.0,
                    source="pre-market",
                ),
            ],
            gap_movers=[
                PremarketMove(
                    symbol="NVDA",
                    name="NVIDIA Corporation",
                    last=107.0,
                    previous_close=100.0,
                    change_pct=7.0,
                    source="pre-market",
                ),
            ],
        ),
    )


def test_position_view_includes_unrealized_pl_dollar_and_stop_distance() -> None:
    item = TickerReport(
        ticker=TickerConfig(
            symbol="NVDA", company_name="NVIDIA",
            position=PositionConfig(
                status="holding", shares=10, avg_cost=80.0,
                portfolio_weight=5.0, stop_loss=92.0, sector="Semis",
            ),
        ),
        articles=[], x_signals=[], earnings=None,
        valuation=ValuationSnapshot(
            ticker="NVDA", as_of_date=date(2026, 5, 12), source="yfinance",
            metrics={"last_close": 100.0, "previous_close": 95.0},
            retrieved_at=datetime(2026, 5, 12, tzinfo=timezone.utc),
        ),
    )

    view = position_view(item)

    assert view["pl_dollar"] == 200.0
    assert abs(view["stop_distance_pct"] - 8.6956) < 0.1
    assert view["stop_distance_tone"] == "ok"
    assert view["sector"] == "Semis"


def test_position_view_stop_distance_tone_escalates_when_close_to_stop() -> None:
    item = TickerReport(
        ticker=TickerConfig(
            symbol="X", company_name="X",
            position=PositionConfig(status="holding", shares=5, avg_cost=100.0, stop_loss=99.0),
        ),
        articles=[], x_signals=[], earnings=None,
        valuation=ValuationSnapshot(
            ticker="X", as_of_date=date(2026, 5, 12), source="yfinance",
            metrics={"last_close": 100.0, "previous_close": 100.0},
            retrieved_at=datetime(2026, 5, 12, tzinfo=timezone.utc),
        ),
    )

    view = position_view(item)
    assert view["stop_distance_tone"] == "danger"


def test_sector_concentration_groups_holdings() -> None:
    from stock_daily_research.report import sector_concentration

    def holding(symbol, weight, sector):
        return TickerReport(
            ticker=TickerConfig(
                symbol=symbol, company_name=symbol,
                position=PositionConfig(status="holding", portfolio_weight=weight, sector=sector),
            ),
            articles=[], x_signals=[], earnings=None, valuation=None,
        )

    report = DailyReport(
        report_date=date(2026, 5, 12),
        generated_at=datetime(2026, 5, 12, tzinfo=timezone.utc),
        ticker_reports=[
            holding("NVDA", 20.0, "Semis"),
            holding("AMD", 10.0, "Semis"),
            holding("AAPL", 8.0, "Hardware"),
        ],
    )

    buckets = sector_concentration(report)
    assert [b["sector"] for b in buckets] == ["Semis", "Hardware"]
    assert buckets[0]["weight"] == 30.0
    assert buckets[0]["count"] == 2
    assert set(buckets[0]["tickers"]) == {"NVDA", "AMD"}


def test_sector_concentration_flags_over_cap() -> None:
    from stock_daily_research.report import sector_concentration
    from stock_daily_research.models import AppSettings, PortfolioSettings

    report = DailyReport(
        report_date=date(2026, 5, 12),
        generated_at=datetime(2026, 5, 12, tzinfo=timezone.utc),
        ticker_reports=[
            TickerReport(
                ticker=TickerConfig(
                    symbol="NVDA", company_name="NVDA",
                    position=PositionConfig(status="holding", portfolio_weight=40.0, sector="Semis"),
                ),
                articles=[], x_signals=[], earnings=None, valuation=None,
            ),
        ],
        settings=AppSettings(portfolio=PortfolioSettings(max_sector_weight=25.0)),
    )

    buckets = sector_concentration(report)
    assert buckets[0]["over_cap"] is True
    assert buckets[0]["cap"] == 25.0


def test_stop_distance_warnings_filters_to_close_to_stop() -> None:
    from stock_daily_research.report import stop_distance_warnings

    def holding(symbol, last, stop):
        return TickerReport(
            ticker=TickerConfig(
                symbol=symbol, company_name=symbol,
                position=PositionConfig(status="holding", portfolio_weight=10.0, stop_loss=stop),
            ),
            articles=[], x_signals=[], earnings=None,
            valuation=ValuationSnapshot(
                ticker=symbol, as_of_date=date(2026, 5, 12), source="yfinance",
                metrics={"last_close": last, "previous_close": last},
                retrieved_at=datetime(2026, 5, 12, tzinfo=timezone.utc),
            ),
        )

    report = DailyReport(
        report_date=date(2026, 5, 12),
        generated_at=datetime(2026, 5, 12, tzinfo=timezone.utc),
        ticker_reports=[
            holding("NEAR", 101.0, 100.0),   # 1% above stop → danger
            holding("WARN", 104.0, 100.0),   # 4% above → warn
            holding("SAFE", 120.0, 100.0),   # 20% above → excluded
        ],
    )

    warnings = stop_distance_warnings(report)
    symbols = [w["symbol"] for w in warnings]
    assert symbols == ["NEAR", "WARN"]
    assert warnings[0]["tone"] == "danger"
    assert warnings[1]["tone"] == "warn"


def test_portfolio_impact_summary_surfaces_addable_cash_and_sectors() -> None:
    from stock_daily_research.report import portfolio_impact_summary
    from stock_daily_research.models import AppSettings, PortfolioSettings

    holding = TickerReport(
        ticker=TickerConfig(
            symbol="NVDA", company_name="NVDA",
            position=PositionConfig(
                status="holding", portfolio_weight=15.0, stop_loss=90.0, sector="Semis",
            ),
        ),
        articles=[], x_signals=[], earnings=None,
        valuation=ValuationSnapshot(
            ticker="NVDA", as_of_date=date(2026, 5, 12), source="yfinance",
            metrics={"last_close": 100.0, "previous_close": 95.0},
            retrieved_at=datetime(2026, 5, 12, tzinfo=timezone.utc),
        ),
    )

    report = DailyReport(
        report_date=date(2026, 5, 12),
        generated_at=datetime(2026, 5, 12, tzinfo=timezone.utc),
        ticker_reports=[holding],
        settings=AppSettings(
            portfolio=PortfolioSettings(
                total_value=100000.0, addable_cash=25000.0,
                max_sector_weight=30.0, max_single_weight=10.0,
            ),
        ),
    )

    summary = portfolio_impact_summary(report)
    assert summary["addable_cash"] == 25000.0
    assert summary["total_value"] == 100000.0
    assert summary["max_single_weight"] == 10.0
    assert summary["total_weight_pct"] == 15.0
    assert summary["sectors"][0]["sector"] == "Semis"
    assert [r["symbol"] for r in summary["over_concentrated"]] == ["NVDA"]


def _news(symbol, title, source, event_type="other", score=1.0):
    return NewsArticle(
        ticker=symbol, title=title, source=source, domain=f"{source.lower()}.com",
        published_at=datetime(2026, 5, 12, tzinfo=timezone.utc),
        url=f"https://{source.lower()}.com/{abs(hash(title)) % 100000}",
        summary="", event_type=event_type, importance_score=score,
    )


def test_event_clusters_groups_same_story_across_sources() -> None:
    from stock_daily_research.report import event_clusters

    item = TickerReport(
        ticker=TickerConfig(symbol="TSLA", company_name="Tesla"),
        articles=[
            _news("TSLA", "Tesla SpaceX merger speculation heats up", "Bloomberg", "deal", 1.2),
            _news("TSLA", "Musk floats SpaceX Tesla merger, sources say", "CNBC", "deal", 1.1),
            _news("TSLA", "SpaceX Tesla merger talks draw scrutiny", "Reuters", "deal", 1.0),
            _news("TSLA", "Tesla unveils new charging network expansion", "CNBC", "product", 0.9),
        ],
        x_signals=[], earnings=None, valuation=None,
    )
    report = DailyReport(
        report_date=date(2026, 5, 12),
        generated_at=datetime(2026, 5, 12, tzinfo=timezone.utc),
        ticker_reports=[item],
    )

    clusters = event_clusters(report)
    # The 3 merger stories cluster; the charging-network story stays single-source → dropped.
    assert len(clusters) == 1
    cluster = clusters[0]
    assert cluster["article_count"] == 3
    assert cluster["source_count"] == 3
    assert cluster["confidence"] == "high"
    assert cluster["impact"] == "strategic optionality"
    assert "Bloomberg" in cluster["sources"]
    assert cluster["tickers"] == ["TSLA"]


def test_event_clusters_drops_single_source_stories() -> None:
    from stock_daily_research.report import event_clusters

    item = TickerReport(
        ticker=TickerConfig(symbol="NVDA", company_name="NVIDIA"),
        articles=[
            _news("NVDA", "NVIDIA Blackwell ramp accelerates demand", "Reuters", "product", 1.0),
            _news("NVDA", "Apple expands services revenue sharply", "CNBC", "earnings", 1.0),
        ],
        x_signals=[], earnings=None, valuation=None,
    )
    report = DailyReport(
        report_date=date(2026, 5, 12),
        generated_at=datetime(2026, 5, 12, tzinfo=timezone.utc),
        ticker_reports=[item],
    )

    assert event_clusters(report) == []


def test_event_clusters_confidence_medium_for_two_sources() -> None:
    from stock_daily_research.report import event_clusters

    item = TickerReport(
        ticker=TickerConfig(symbol="INTC", company_name="Intel"),
        articles=[
            _news("INTC", "Intel foundry secures major customer deal", "Bloomberg", "deal", 1.1),
            _news("INTC", "Intel foundry lands major customer, sources say", "Reuters", "deal", 1.0),
        ],
        x_signals=[], earnings=None, valuation=None,
    )
    report = DailyReport(
        report_date=date(2026, 5, 12),
        generated_at=datetime(2026, 5, 12, tzinfo=timezone.utc),
        ticker_reports=[item],
    )

    clusters = event_clusters(report)
    assert len(clusters) == 1
    assert clusters[0]["confidence"] == "medium"
    assert "review" in clusters[0]["action"]


def _pre_earnings_report(earnings_date, *, metrics=None, questions=None):
    item = TickerReport(
        ticker=TickerConfig(symbol="NVDA", company_name="NVIDIA"),
        articles=[], x_signals=[],
        valuation=ValuationSnapshot(
            ticker="NVDA", as_of_date=date(2026, 4, 28), source="yfinance",
            metrics=metrics or {},
            retrieved_at=datetime(2026, 4, 28, tzinfo=timezone.utc),
        ),
        earnings=EarningsDate(
            ticker="NVDA", company_name="NVIDIA",
            earnings_date=earnings_date, time_of_day="after_market",
            fiscal_quarter="Q1", fiscal_year=2026,
            eps_estimate=1.25, revenue_estimate=44_000_000_000.0, source="yfinance",
            source_retrieved_at=datetime(2026, 4, 28, tzinfo=timezone.utc),
        ),
    )
    research_states = {}
    if questions is not None:
        research_states["NVDA"] = TickerResearchState(ticker="NVDA", earnings_questions=questions)
    return DailyReport(
        report_date=date(2026, 4, 28),
        generated_at=datetime(2026, 4, 28, tzinfo=timezone.utc),
        ticker_reports=[item],
        research_states=research_states,
    ), item


def test_pre_earnings_card_within_window_surfaces_estimates() -> None:
    report, item = _pre_earnings_report(
        date(2026, 4, 30),
        metrics={"fy1_eps_revision_30d": 3.2, "return_20d": 8.0, "rsi_14": 62.0,
                 "last_close": 100.0, "fifty_two_week_high": 110.0},
    )
    card = pre_earnings_card(report, item)
    assert card is not None
    assert card["days_until"] == 2
    assert card["eps_estimate"] == 1.25
    assert card["revenue_estimate"] == 44_000_000_000.0
    assert card["eps_revision_30d"] == 3.2
    assert card["rsi"] == 62.0
    assert card["overextended"] is False
    assert card["questions"] == ["", "", ""]


def test_pre_earnings_card_flags_overextended() -> None:
    report, item = _pre_earnings_report(
        date(2026, 4, 29),
        metrics={"rsi_14": 78.0, "last_close": 109.0, "fifty_two_week_high": 110.0},
    )
    card = pre_earnings_card(report, item)
    assert card is not None
    assert card["overextended"] is True


def test_pre_earnings_card_fills_question_slots_from_state() -> None:
    report, item = _pre_earnings_report(
        date(2026, 4, 28),
        questions=["Data center growth?", "Margin trajectory?"],
    )
    card = pre_earnings_card(report, item)
    assert card is not None
    assert card["days_until"] == 0
    assert card["questions"] == ["Data center growth?", "Margin trajectory?", ""]


def test_pre_earnings_card_none_outside_window() -> None:
    report, item = _pre_earnings_report(date(2026, 5, 10))
    assert pre_earnings_card(report, item) is None
    report_past, item_past = _pre_earnings_report(date(2026, 4, 27))
    assert pre_earnings_card(report_past, item_past) is None
