from dataclasses import replace
from datetime import date, datetime, timedelta, timezone

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
    analyst_consensus,
    book_today_summary,
    capital_allocation_queue,
    card_state,
    days_until,
    daily_summary,
    earnings_delta,
    earnings_urgency,
    earnings_urgency_label,
    eps_power_summary,
    eps_outlook,
    named_analyst_targets,
    eps_revision_class,
    event_label,
    hero_items,
    important_news,
    macro_risk_meter,
    market_label,
    map_change_bin,
    morning_briefing_cards,
    moving_average_snapshot,
    news_tier,
    pe_class,
    position_view,
    ticker_delta,
    attention_score_breakdown,
    _valuation_risk_direction,
    post_earnings_items,
    pre_earnings_card,
    premarket_triage,
    premarket_watchlist_moves,
    priority_items,
    quality_of_move,
    render_html_report,
    render_markdown_report,
    rsi_class,
    rsi_label,
    rule_alerts,
    sector_leadership,
    sector_map_markets,
    sort_by_market_cap,
    source_reliability,
    topic_tags,
    todays_catalysts,
    todays_focus,
    top_news_count,
    ticker_insights,
    valuation_risk_label,
    write_report,
    plan_triggers,
    morning_actions,
    ticker_sparkline,
    _parse_price_levels,
    _plausible_levels,
    derive_portfolio_weights,
    portfolio_impact_summary,
    portfolio_brief,
    report_output_dir,
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
    assert '<main id="page-top" class="page">' in output
    assert 'href="#page-top"' in output
    assert "盤勢" in output
    assert "盤前" in output
    assert "主要風險" in output
    assert "今日焦點" in output
    assert "今日摘要" in output
    assert "daily-summary-item" in output
    assert "總經日曆" in output
    assert "隔夜 / 盤前" in output
    assert "今日焦點" in output
    assert "focus-rank" in output
    assert "section-primary" in output
    assert "今日催化" in output
    assert "產業地圖" in output
    assert "sector-map" in output
    assert "map-tile" in output
    assert "map-market-panel" in output
    assert "總經風險儀表" in output
    assert "資料品質" in output
    assert "全域警示" in output
    assert "盤前公布財報" in output
    assert "FOMC 利率決策" in output
    assert "估值快照" in output
    assert "EPS（TTM→FY1）" in output
    assert "4.20 → 5.10" in output
    assert "預估 +21.40%" in output
    assert "TTM EPS" in output
    assert "FY1 EPS 修正 30D" in output
    assert "FY1 營收修正 30D" in output
    assert "下季營收修正 30D" in output
    assert "持股總覽" in output
    assert "持股貢獻明細" in output
    assert "個股卡片" in output
    assert "Nvidia revenue beats" in output
    assert "+4.00% / 1.8x 成交量" in output
    assert "5.26T" in output
    assert "持股與損益" in output
    assert "上次報告後的變化" in output
    assert "產生時間：2026-04-28 15:00 台灣時間 (UTC+8)" in output
    assert "已檢視財報" in output
    assert "已投入比重" in output
    assert "earnings reviewed" not in output
    assert "Invested weight" not in output
    assert "2026-04-28 15:00 TWN / UTC+8" in output
    assert "行情時間：2026-04-28 11:00 UTC" in output
    assert "資金配置清單" in output
    assert "事件前暫停" in output
    assert "避免追高" in output
    assert "window.claude.complete" in output


def test_render_html_report_shows_forward_eps_and_attributed_targets() -> None:
    report = _sample_report()
    item = report.ticker_reports[0]
    assert item.valuation is not None
    metrics = {
        **item.valuation.metrics,
        "forward_eps": 5.35,
        "analyst_target_low": 95.0,
        "analyst_target_mean": 128.0,
        "analyst_target_median": 130.0,
        "analyst_target_high": 165.0,
        "analyst_opinion_count": 54,
    }
    analyst_article = NewsArticle(
        ticker="NVDA",
        title="Morgan Stanley raises Nvidia price target from $120 to $140",
        source="Reuters",
        domain="reuters.com",
        published_at=datetime(2026, 4, 27, tzinfo=timezone.utc),
        url="https://reuters.com/nvda-target",
        summary="",
        event_type="analyst",
        importance_score=0.9,
    )
    report = replace(
        report,
        ticker_reports=[
            replace(
                item,
                articles=[*item.articles, analyst_article],
                valuation=replace(item.valuation, metrics=metrics),
            )
        ],
    )

    output = render_html_report(report)

    assert "Forward EPS（NTM）" in output
    assert "共識目標" in output
    assert "USD 130.00" in output
    assert "+25.00%" in output
    assert "54 位分析師" in output
    assert "品質、估值與觀察" in output
    assert "摩根士丹利 上調至 USD 140.00" in output
    assert 'href="https://reuters.com/nvda-target"' in output


def test_write_report_outputs_markdown_and_html(tmp_path) -> None:
    paths = write_report(_sample_report(), tmp_path)

    assert paths.markdown.exists()
    assert paths.html.exists()
    assert paths.markdown.suffix == ".md"
    assert paths.html.suffix == ".html"
    assert paths.markdown.parent == tmp_path / "2026" / "04"
    assert paths.html.parent == tmp_path / "2026" / "04"
    assert paths.brief.parent == tmp_path / "2026" / "04"
    assert report_output_dir(tmp_path, date(2026, 11, 5)) == tmp_path / "2026" / "11"

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
    assert 'id="market-workspace"' in output
    assert output.index('id="market-workspace"') < output.index('<nav class="toc"')
    assert output.count('class="market-tabs"') == 1
    assert 'market-stat-tickers' in output
    assert 'id="market-summary-list"' in output
    assert 'function updateMarketSummary(' in output
    assert 'function updateMarketWorkspace()' in output
    assert 'is-market-hidden' in output
    assert 'market-header-ticker-count' in output
    assert 'id="market-context"' in output
    assert '"#changes .change-item"' in output
    assert '"#changes-30d .change-item"' in output
    assert '"#rule-alerts .alert-item"' in output
    assert '"#data-quality tbody tr"' in output
    assert 'allHoldingsMatch' in output
    assert 'market-summary-macro' in output
    assert 'class="morning-tile" data-market="us" href="#ticker-nvda"' in output
    assert "element.matches('a[href^="#ticker-"]')" in output
    assert 'class="map-tabs"' not in output
    assert '<button type="button" class="map-tab' not in output
    assert 'id="valuation-table" class="valuation-table is-compact"' in output
    assert 'id="toggle-valuation-columns"' in output
    assert 'function setupValuationColumns()' in output
    assert 'data-market-tab="us"' in output
    assert 'data-market-tab="taiwan"' in output
    assert 'data-market-tab="crypto"' in output
    assert 'stock-daily-market-tab' in output
    assert 'function setupMarketTabs()' in output
    assert 'data-market="us"' in output
    assert 'market-badge' in output
    assert 'id="rsi-filter"' in output
    assert 'id="valuation-sort"' in output
    assert "市場情緒" in output
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
    assert "距高點 -5.45%" in output
    assert "data-revenue-rev-30d=" in output
    assert "data-next-q-revenue-rev-30d=" in output
    assert "enhanceFocusFromLocalState" in output
    assert "thesis_trigger" in output
    assert "FY1營收修正" in output
    assert "下季營收修正" in output
    assert "stock-daily-draft-post-earnings" in output
    assert "data-local-revisit-hero" in output
    assert "syncRevisitHero" in output
    assert "管理" in output
    assert "下次財報" in output
    assert "估值風險" in output
    assert "觀察清單 TXT" in output
    assert "研究待辦" in output
    assert "30 天變化" in output


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

    assert "研究紀錄" in output
    assert "優先檢視" in output
    assert "論點變動" in output
    assert "歷史報告" in output
    assert '"thesis_state": "active"' in output
    assert '"history_days": 45' in output
    assert "投資論點狀態改變" in output
    assert "研究記憶" in output
    assert "已檢視" in output


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
    assert 'class="earnings-pill imminent" data-market="us"' in output
    assert "即將公布" in output
    assert ">今日<" in output


def test_days_until_handles_relative_dates() -> None:
    anchor = date(2026, 4, 28)

    assert days_until(date(2026, 4, 28), anchor) == "今日"
    assert days_until(date(2026, 4, 29), anchor) == "明日"
    assert days_until(date(2026, 5, 5), anchor) == "7天後"
    assert days_until(date(2026, 4, 27), anchor) == "1天前"
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


def test_earnings_urgency_label_localizes_buckets() -> None:
    anchor = date(2026, 4, 28)

    assert earnings_urgency_label(date(2026, 4, 28), anchor) == "即將公布"
    assert earnings_urgency_label(date(2026, 4, 30), anchor) == "近期"
    assert earnings_urgency_label(date(2026, 5, 5), anchor) == "本週"
    assert earnings_urgency_label(date(2026, 5, 20), anchor) == "稍後"
    assert earnings_urgency_label(date(2026, 4, 1), anchor) == "已過期"


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

    assert news_rationale(FakeArticle("earnings")) == "財報解讀"
    assert news_rationale(FakeArticle("ai")) == "AI/資本支出啟示"
    assert news_rationale(FakeArticle("deal")) == "戰略佈局"
    assert news_rationale(FakeArticle("regulation")) == "監管風險"
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


def test_zh_text_translates_composite_trend_and_relative_dates() -> None:
    from stock_daily_research.report import zh_text

    translated = zh_text("Earnings in 7d | Above 60D / 120D, below 20D")

    assert translated == "\u8ca1\u5831 7 \u5929\u5f8c | \u7ad9\u4e0a 60D / 120D\uff0c\u4f4e\u65bc 20D"


def test_zh_text_translates_decision_workflow_phrases() -> None:
    from stock_daily_research.report import zh_text

    assert zh_text("event risk | no action before earnings review") == (
        "\u4e8b\u4ef6\u98a8\u96aa | \u8ca1\u5831\u6aa2\u8996\u524d\u66ab\u505c\u64cd\u4f5c"
    )
    assert zh_text("Review only before event") == "\u4e8b\u4ef6\u524d\u50c5\u6aa2\u8996\uff0c\u4e0d\u64cd\u4f5c"
    assert zh_text("less stretched") == "\u56de\u6a94\u5e45\u5ea6\u8f03\u6eab\u548c"
    assert zh_text("event window") == "\u4e8b\u4ef6\u7a97\u53e3"

def test_zh_text_keeps_alert_phrases_coherent() -> None:
    from stock_daily_research.report import zh_text

    assert zh_text("8 trusted headline(s), 2 top-tier.") == "8 則可信新聞，2 則一級新聞。"
    assert zh_text("FY1 EPS revision +15.8% over 30D.") == "FY1 EPS 預估 30 日修正 +15.8%。"
    assert zh_text("6 headline(s); revisit thesis before chasing.") == "6 則新聞；追價前先重新檢查投資論點。"
    translated = zh_text(
        "RSI 14 70, -0.37% from 52W high; avoid chasing without a fresh catalyst."
    )
    assert translated == "RSI 14 70, 距 52 週高點 -0.37%；沒有新催化時避免追價。"
    assert "修正ision" not in translated
    assert "新聞(s)" not in translated


def test_technical_playbook_classifies_breakout_pullback_extended_and_weakening() -> None:
    from stock_daily_research.report import technical_playbook

    breakout = technical_playbook(_score_item({
        "last_close": 120.0,
        "sma_20": 110.0, "sma_60": 100.0, "sma_120": 90.0,
        "sma_20_slope_5d": 1.2, "prior_20d_high": 118.0,
        "volume_vs_20d": 1.8, "rsi_14": 60.0,
    }))
    assert breakout is not None
    assert breakout["status"] == "Breakout confirmed"
    assert "Breakout above prior 20D high" in breakout["criteria"]

    pullback = technical_playbook(_score_item({
        "last_close": 101.0,
        "sma_20": 100.0, "sma_60": 95.0, "sma_120": 90.0,
        "sma_20_slope_5d": 0.5, "prior_20d_high": 110.0,
        "volume_vs_20d": 0.8, "rsi_14": 55.0,
    }))
    assert pullback is not None
    assert pullback["status"] == "Pullback watch"

    extended = technical_playbook(_score_item({
        "last_close": 112.0,
        "sma_20": 100.0, "sma_60": 95.0, "sma_120": 90.0,
        "sma_20_slope_5d": 0.8, "prior_20d_high": 116.0,
        "volume_vs_20d": 1.0, "rsi_14": 62.0,
    }))
    assert extended is not None
    assert extended["status"] == "Extended, do not chase"

    weakening = technical_playbook(_score_item({
        "last_close": 80.0,
        "sma_20": 90.0, "sma_60": 95.0, "sma_120": 100.0,
        "sma_20_slope_5d": -1.5, "prior_20d_high": 100.0, "prior_20d_low": 82.0,
        "volume_vs_20d": 1.0, "rsi_14": 40.0,
    }))
    assert weakening is not None
    assert weakening["status"] == "Trend weakening"
    assert "Breakdown below prior 20D low" in weakening["criteria"]


def test_render_html_report_includes_technical_playbook() -> None:
    item = _score_item({
        "last_close": 120.0,
        "sma_20": 110.0, "sma_60": 100.0, "sma_120": 90.0,
        "sma_20_slope_5d": 1.2, "prior_20d_high": 118.0,
        "volume_vs_20d": 1.8, "rsi_14": 60.0,
    })
    report = DailyReport(
        report_date=date(2026, 5, 12),
        generated_at=datetime(2026, 5, 12, tzinfo=timezone.utc),
        ticker_reports=[item],
    )

    output = render_html_report(report)

    assert 'class="insight-row technical tech-up"' in output
    assert 'data-technical-priority="5"' in output
    assert 'class="technical-breakdown"' in output


def test_moving_average_snapshot_uses_market_specific_annual_line() -> None:
    metrics = {
        "last_close": 130.0,
        "sma_5": 125.0,
        "sma_10": 120.0,
        "sma_20": 115.0,
        "sma_60": 110.0,
        "sma_120": 100.0,
        "sma_200": 95.0,
        "sma_240": 90.0,
        "price_history_sessions": 500,
        "price_history_as_of_date": "2026-07-27",
    }
    us_item = _score_item(metrics)
    taiwan_item = replace(
        us_item,
        ticker=replace(
            us_item.ticker,
            symbol="2330.TW",
            company_name="台積電",
            market="twse",
            currency="TWD",
        ),
    )

    us_view = moving_average_snapshot(us_item)
    taiwan_view = moving_average_snapshot(taiwan_item)

    assert [row["label"] for row in us_view["rows"]] == [
        "MA5", "MA10", "MA20", "MA60", "MA120", "MA200",
    ]
    assert [row["label"] for row in taiwan_view["rows"]] == [
        "MA5", "MA10", "MA20", "MA60", "MA120", "MA240",
    ]
    assert us_view["summary"] == "完整多頭排列"
    assert taiwan_view["summary"] == "完整多頭排列"
    assert us_view["source"] == "Yahoo Finance 遠端日線"
    assert us_view["as_of"] == "2026-07-27"
    assert us_view["sessions"] == 500


def test_moving_average_snapshot_marks_unavailable_long_average() -> None:
    item = _score_item({
        "last_close": 120.0,
        "sma_5": 118.0,
        "sma_10": 116.0,
        "sma_20": 112.0,
        "sma_60": 105.0,
        "sma_120": 100.0,
        "sma_200": None,
        "price_history_sessions": 120,
        "price_history_as_of_date": "2026-07-27",
    })

    view = moving_average_snapshot(item)

    assert view["available_count"] == 5
    assert view["missing_count"] == 1
    assert view["summary"] == "站上多數可用均線"
    assert view["rows"][-1]["label"] == "MA200"
    assert view["rows"][-1]["value"] is None
    assert view["rows"][-1]["relation"] == "資料不足"


def test_render_html_report_includes_market_aware_moving_average_panels() -> None:
    metrics = {
        "last_close": 130.0,
        "sma_5": 125.0,
        "sma_10": 120.0,
        "sma_20": 115.0,
        "sma_60": 110.0,
        "sma_120": 100.0,
        "sma_200": 95.0,
        "sma_240": 90.0,
        "price_history_sessions": 500,
        "price_history_as_of_date": "2026-07-27",
    }
    us_item = _score_item(metrics)
    taiwan_item = replace(
        _score_item(metrics),
        ticker=TickerConfig(
            symbol="2330.TW", company_name="台積電", market="twse", currency="TWD",
        ),
    )
    report = DailyReport(
        report_date=date(2026, 7, 28),
        generated_at=datetime(2026, 7, 28, tzinfo=timezone.utc),
        ticker_reports=[us_item, taiwan_item],
    )

    output = render_html_report(report)

    assert output.count('class="moving-average-panel"') == 2
    assert '<span class="moving-average-label">MA200 · 年線</span>' in output
    assert '<span class="moving-average-label">MA240 · 年線</span>' in output
    assert output.count("Yahoo Finance 遠端日線") == 2
    grid_css = output.split(".moving-average-grid {", 1)[1].split("}", 1)[0]
    value_css = output.split(".moving-average-value {", 1)[1].split("}", 1)[0]
    distance_css = output.split(".moving-average-distance {", 1)[1].split("}", 1)[0]
    assert "grid-template-columns: repeat(2, minmax(0, 1fr));" in grid_css
    assert "margin: 7px 0 0;" in grid_css
    assert "white-space: nowrap;" in value_css
    assert "overflow-wrap: normal;" in value_css
    assert "word-break: normal;" in value_css
    assert "white-space: nowrap;" in distance_css
    assert "@media (max-width: 360px)" in output


def _framework_item(
    closes: list[float],
    highs: list[float],
    lows: list[float],
    volumes: list[float],
    **overrides: object,
) -> TickerReport:
    count = len(closes)
    metrics: dict[str, object] = {
        "last_close": closes[-1],
        "previous_close": closes[-2],
        "sma_20": sum(closes[-20:]) / min(20, count),
        "sma_60": closes[-1],
        "sma_120": closes[-1],
        "sma_20_slope_5d": 0.0,
        "return_20d": (closes[-1] - closes[0]) / closes[0] * 100.0,
        "rsi_14": 55.0,
        "fifty_two_week_high": max(highs) * 1.1,
        "chart_dates_60": [f"2026-06-{index + 1:02d}" for index in range(count)],
        "chart_close_60": closes,
        "chart_high_60": highs,
        "chart_low_60": lows,
        "chart_volume_60": volumes,
        "chart_sma20_60": [sum(closes[max(0, index - 19):index + 1]) / min(20, index + 1) for index in range(count)],
        "chart_sma60_60": [sum(closes[:index + 1]) / (index + 1) for index in range(count)],
    }
    metrics.update(overrides)
    return _score_item(metrics)


def _demand_breakout_item() -> TickerReport:
    closes = [90.0 + index * 0.5 for index in range(20)] + [103.0]
    highs = [value + 1.0 for value in closes[:-1]] + [104.0]
    lows = [value - 1.0 for value in closes[:-1]] + [99.0]
    volumes = [100.0] * 20 + [200.0]
    return _framework_item(
        closes,
        highs,
        lows,
        volumes,
        sma_20=100.0,
        sma_60=95.0,
        sma_120=90.0,
        sma_20_slope_5d=1.0,
        prior_20d_high=100.5,
        prior_20d_low=89.0,
        breakout_days_ago=0.0,
        breakout_pivot=100.5,
        breakout_hold_pct=2.49,
        breakout_volume_vs_20d=2.0,
    )


def test_volume_price_analysis_confirms_demand_on_quality_breakout() -> None:
    from stock_daily_research.report import volume_price_analysis

    result = volume_price_analysis(_demand_breakout_item())

    assert result is not None
    assert result["status"] == "\u9700\u6c42\u78ba\u8a8d"
    assert result["event"] == "\u653e\u91cf\u7a81\u7834"
    assert result["score_adjustment"] == 5
    assert result["breakout"] is True
    assert result["close_location"] >= 0.65


def test_supply_breakdown_penalizes_right_side_score() -> None:
    from stock_daily_research.report import right_side_score, volume_price_analysis

    closes = [110.0 - index * 0.4 for index in range(20)] + [98.0]
    highs = [value + 1.0 for value in closes[:-1]] + [103.0]
    lows = [value - 1.0 for value in closes[:-1]] + [97.0]
    item = _framework_item(
        closes,
        highs,
        lows,
        [100.0] * 20 + [220.0],
        sma_20=102.0,
        sma_60=106.0,
        sma_120=110.0,
        sma_20_slope_5d=-1.0,
        fy1_eps_revision_30d=0.0,
    )

    vpa = volume_price_analysis(item)
    score = right_side_score(item)

    assert vpa is not None
    assert vpa["status"] == "\u4f9b\u7d66\u78ba\u8a8d"
    assert vpa["score_adjustment"] == -5
    assert score is not None
    assert any(reason.startswith("-5 VPA") for reason in score["reasons"])
    assert not any(reason.startswith("+5 volume") for reason in score["reasons"])


def test_wyckoff_spring_remains_a_candidate_until_tested() -> None:
    from stock_daily_research.report import trading_framework_analysis

    item = _framework_item(
        [100.0] * 20 + [100.5],
        [102.0] * 21,
        [98.0] * 20 + [96.0],
        [100.0] * 20 + [120.0],
        sma_20=100.0,
        sma_60=100.0,
        sma_120=100.0,
        sma_20_slope_5d=0.0,
    )

    result = trading_framework_analysis(item)

    assert result is not None
    assert result["wyckoff"]["event"] == "Spring \u5047\u8dcc\u7834"
    assert result["wyckoff"]["phase"] == "\u5438\u7c4c\u5019\u9078"
    assert result["wyckoff"]["candidate"] is True
    assert result["operator"]["status"] == "\u7b49\u5f85\u6e2c\u8a66"


def test_adam_reflection_is_visible_but_not_scored() -> None:
    from stock_daily_research.report import (
        adam_reflection_scenario,
        price_structure_chart,
        right_side_score,
    )

    item = _demand_breakout_item()
    scenario = adam_reflection_scenario(item)
    score = right_side_score(item)
    chart = price_structure_chart(item)

    assert scenario is not None
    assert scenario["periods"] == 5
    assert scenario["projected_end"] > item.valuation.metrics["last_close"]
    assert "\u4e0d\u7d0d\u5165\u53f3\u5074\u5206\u6578" in scenario["note"]
    assert score is not None
    assert all("Adam" not in reason for reason in score["reasons"])
    assert 'class="price-line-adam"' in chart
    assert 'class="price-chart-scenario-divider"' in chart


def test_render_html_report_includes_integrated_trading_framework() -> None:
    item = _demand_breakout_item()
    report = DailyReport(
        report_date=date(2026, 6, 21),
        generated_at=datetime(2026, 6, 21, tzinfo=timezone.utc),
        ticker_reports=[item],
    )

    output = render_html_report(report)

    assert 'class="market-reading reading-up"' in output
    assert 'class="framework-evidence-grid"' in output
    assert "\u9700\u6c42\u78ba\u8a8d" in output
    assert "SOS \u5f37\u52e2\u8a0a\u865f" in output
    assert "\u4e9e\u7576\u53cd\u5c04\u60c5\u5883" in output


def test_morning_actions_surfaces_confirmed_demand_structure() -> None:
    from stock_daily_research.report import morning_actions

    report = DailyReport(
        report_date=date(2026, 6, 21),
        generated_at=datetime(2026, 6, 21, tzinfo=timezone.utc),
        ticker_reports=[_demand_breakout_item()],
    )

    actions = morning_actions(report)

    framework_action = next(
        action for action in actions if action["label"] == "Demand confirmed"
    )
    assert framework_action["display_label"] == "\u91cf\u50f9\u78ba\u8a8d"
    assert "SOS \u5f37\u52e2\u8a0a\u865f" in framework_action["display_headline"]
    assert framework_action["tone"] == "good"


def test_price_regime_reset_suspends_signals_and_renders_rebuild_state() -> None:
    from stock_daily_research.report import (
        price_regime_status,
        right_side_check,
        right_side_execution_plan,
        right_side_score,
    )

    closes = [11.5 + index * 0.1 for index in range(8)]
    item = _score_item({
        "last_close": closes[-1],
        "previous_close": closes[-2],
        "technical_history_version": 2,
        "price_regime_change_date": "2026-06-29",
        "price_regime_change_pct": -95.7,
        "price_history_sessions": len(closes),
        "chart_dates_60": [f"2026-07-{index + 7:02d}" for index in range(8)],
        "chart_close_60": closes,
        "chart_high_60": [value + 0.2 for value in closes],
        "chart_low_60": [value - 0.2 for value in closes],
        "chart_volume_60": [1_000_000.0] * 8,
        "chart_sma20_60": [None] * 8,
        "chart_sma60_60": [None] * 8,
    })
    report = DailyReport(
        report_date=date(2026, 7, 16),
        generated_at=datetime(2026, 7, 16, tzinfo=timezone.utc),
        ticker_reports=[item],
    )

    regime = price_regime_status(item)
    output = render_html_report(report)

    assert regime is not None
    assert regime["remaining_sessions"] == 13
    assert right_side_score(item) is None
    assert right_side_check(item) is None
    assert right_side_execution_plan(report, item) is None
    assert 'data-price-regime-reset="1"' in output
    assert "8/21" in output

def test_right_side_check_accepts_breakout_without_contraction() -> None:
    from stock_daily_research.report import right_side_check

    item = _score_item({
        "last_close": 103.5,
        "sma_20": 102.0,
        "sma_60": 98.0,
        "sma_120": 90.0,
        "volume_vs_20d": 1.6,
        "prior_20d_high": 101.0,
        "prior_20d_low": 100.0,
        "atr_20": 1.5,
        "atr_contraction_ratio": 1.05,
        "bb_width_20_percentile": 60.0,
        "volume_5d_vs_20d": 1.20,
        "breakout_days_ago": 2.0,
        "breakout_pivot": 101.0,
        "breakout_hold_pct": 2.48,
        "breakout_volume_vs_20d": 1.6,
    })

    result = right_side_check(item)

    assert result is not None
    assert result["status"] == "Right-side ready"
    assert result["active_pathway"] == "breakout"
    assert result["pathway_status"] == "Breakout entry ready"
    checks = {check["label"]: check for check in result["checks"]}
    assert checks["Breakout entry"]["status"] == "Breakout holding"
    assert checks["Contraction watch"]["passed"] is False


def test_right_side_check_rejects_a_failed_breakout_even_when_trend_is_up() -> None:
    from stock_daily_research.report import right_side_check

    item = _score_item({
        "last_close": 99.0,
        "sma_20": 98.0,
        "sma_60": 95.0,
        "sma_120": 90.0,
        "prior_20d_high": 100.0,
        "prior_20d_low": 90.0,
        "atr_20": 2.0,
        "atr_contraction_ratio": 0.70,
        "bb_width_20_percentile": 20.0,
        "volume_5d_vs_20d": 0.75,
        "breakout_days_ago": 2.0,
        "breakout_pivot": 100.0,
        "breakout_hold_pct": -1.0,
        "breakout_volume_vs_20d": 1.8,
    })

    result = right_side_check(item)

    assert result is not None
    assert result["status"] == "Protect capital first"
    assert result["tone"] == "down"
    breakout = next(
        check for check in result["checks"] if check["label"] == "Breakout entry"
    )
    assert breakout["status"] == "Breakout failed"


def test_right_side_check_accepts_pullback_without_recent_breakout() -> None:
    from stock_daily_research.report import right_side_check

    item = _score_item({
        "last_close": 101.0,
        "previous_close": 100.5,
        "sma_20": 100.0,
        "sma_60": 95.0,
        "sma_120": 90.0,
        "rsi_14": 55.0,
        "volume_vs_20d": 0.8,
        "atr_contraction_ratio": 1.0,
        "bb_width_20_percentile": 55.0,
        "volume_5d_vs_20d": 1.0,
    })

    result = right_side_check(item)

    assert result is not None
    assert result["status"] == "Right-side ready"
    assert result["active_pathway"] == "pullback"
    assert result["pathway_status"] == "Pullback entry ready"
    checks = {check["label"]: check for check in result["checks"]}
    assert checks["Pullback entry"]["status"] == "Pullback holding support"
    assert checks["Breakout entry"]["passed"] is False
    assert checks["Contraction watch"]["passed"] is False


def test_right_side_check_keeps_contraction_as_waiting_state() -> None:
    from stock_daily_research.report import right_side_check

    item = _score_item({
        "last_close": 105.0,
        "sma_20": 100.0,
        "sma_60": 95.0,
        "sma_120": 90.0,
        "rsi_14": 55.0,
        "volume_vs_20d": 1.0,
        "atr_contraction_ratio": 0.65,
        "bb_width_20_percentile": 15.0,
        "volume_5d_vs_20d": 0.70,
    })

    result = right_side_check(item)

    assert result is not None
    assert result["status"] == "Base building"
    assert result["active_pathway"] == "contraction"
    assert result["actionable"] is False


def test_right_side_check_requires_trend_support_for_contraction_watch() -> None:
    from stock_daily_research.report import right_side_check

    item = _score_item({
        "last_close": 90.0,
        "sma_20": 100.0,
        "sma_60": 105.0,
        "sma_120": 110.0,
        "rsi_14": 35.0,
        "volume_vs_20d": 0.7,
        "atr_contraction_ratio": 0.65,
        "bb_width_20_percentile": 15.0,
        "volume_5d_vs_20d": 0.70,
    })

    result = right_side_check(item)

    assert result is not None
    assert result["status"] == "Protect capital first"
    contraction = next(
        check for check in result["checks"] if check["key"] == "contraction"
    )
    assert contraction["status"] == "Contraction lacks trend support"
    assert contraction["passed"] is False

def test_render_html_report_includes_right_side_path_and_optional_gates() -> None:
    item = _score_item({
        "last_close": 103.5,
        "sma_20": 102.0,
        "sma_60": 98.0,
        "sma_120": 90.0,
        "volume_vs_20d": 1.6,
        "prior_20d_high": 101.0,
        "prior_20d_low": 100.0,
        "atr_20": 1.5,
        "atr_contraction_ratio": 1.05,
        "bb_width_20_percentile": 60.0,
        "volume_5d_vs_20d": 1.20,
        "breakout_days_ago": 2.0,
        "breakout_pivot": 101.0,
        "breakout_hold_pct": 2.48,
        "breakout_volume_vs_20d": 1.6,
    })
    report = DailyReport(
        report_date=date(2026, 5, 12),
        generated_at=datetime(2026, 5, 12, tzinfo=timezone.utc),
        ticker_reports=[item],
    )

    output = render_html_report(report)

    assert 'class="insight-row right-side-check check-up"' in output
    assert 'class="right-side-breakdown"' in output
    assert 'class="right-side-check-row tone-up"' in output
    assert "\u7a81\u7834\u8def\u5f91\u6210\u7acb" in output
    assert 'class="optional"' in output
    assert '<span class="gate-mark">&mdash;</span>' in output


def test_right_side_score_high_quality_without_breakout_uses_trend_label() -> None:
    from stock_daily_research.report import right_side_score

    item = _score_item({
        "last_close": 105.0,
        "sma_20": 103.0,
        "sma_60": 100.0,
        "sma_120": 90.0,
        "return_20d": 12.0,
        "volume_vs_20d": 1.8,
        "fy1_eps_revision_30d": 3.0,
        "rsi_14": 60.0,
        "fifty_two_week_high": 130.0,
    })

    result = right_side_score(item, {"spy_20d": 2.0, "qqq_20d": 4.0})

    assert result is not None
    assert result["score"] >= 75
    assert result["status"] == "Trend setup strong"
    assert result["tone"] == "up"


def test_right_side_score_reserves_breakout_label_for_confirmed_structure() -> None:
    from stock_daily_research.report import right_side_score

    item = _score_item({
        "last_close": 105.0,
        "sma_20": 103.0,
        "sma_60": 100.0,
        "sma_120": 90.0,
        "prior_20d_high": 104.0,
        "return_20d": 12.0,
        "volume_vs_20d": 1.8,
        "fy1_eps_revision_30d": 3.0,
        "rsi_14": 60.0,
        "fifty_two_week_high": 130.0,
    })

    result = right_side_score(item, {"spy_20d": 2.0, "qqq_20d": 4.0})

    assert result is not None
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
    # RSI and valuation are context, not invalidation; confirmed penalties total -25.
    assert result["score"] == 25
    assert result["status"] == "Thesis weakening"


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

    assert earnings_action(make(today, rsi=75), today) == "等待反應（過度延伸）"
    assert earnings_action(make(today, rsi=25), today) == "觀察恐慌賣壓"
    assert earnings_action(make(today, rsi=50), today) == "觀察反應"
    assert earnings_action(make(date(2026, 4, 29)), today) == "準備計畫"
    assert earnings_action(make(date(2026, 5, 3)), today) == "建立論點"
    assert earnings_action(make(date(2026, 4, 27)), today) == "檢視結果"
    assert earnings_action(make(date(2026, 4, 21)), today) == "檢視結果"  # 7d ago boundary
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


def test_eps_outlook_shows_growth_and_handles_negative_base() -> None:
    item = TickerReport(
        ticker=TickerConfig(symbol="X", company_name="X"),
        articles=[], x_signals=[], earnings=None,
        valuation=ValuationSnapshot(
            ticker="X", as_of_date=date(2026, 4, 28), source="yfinance",
            metrics={"ttm_eps": 5.0, "next_fy_eps": 6.0, "eps_growth_pct": 20.0},
            retrieved_at=datetime(2026, 4, 28, tzinfo=timezone.utc),
        ),
    )

    outlook = eps_outlook(item)
    assert item.valuation is not None
    turnaround = eps_outlook(replace(
        item,
        valuation=replace(
            item.valuation,
            metrics={"ttm_eps": -1.0, "next_fy_eps": 0.5, "eps_growth_pct": 150.0},
        ),
    ))

    assert outlook["value_label"] == "5.00 → 6.00"
    assert outlook["signal_label"] == "預估 +20.00%"
    assert outlook["growth"] == 20.0
    assert turnaround["signal_label"] == "預估轉盈"
    assert turnaround["growth"] is None


def test_analyst_consensus_prefers_median_and_marks_old_snapshots() -> None:
    item = TickerReport(
        ticker=TickerConfig(symbol="NVDA", company_name="NVIDIA"),
        articles=[],
        x_signals=[],
        earnings=None,
        valuation=ValuationSnapshot(
            ticker="NVDA",
            as_of_date=date(2026, 4, 10),
            source="yfinance",
            metrics={
                "last_close": 200.0,
                "analyst_target_low": 170.0,
                "analyst_target_mean": 235.0,
                "analyst_target_median": 240.0,
                "analyst_target_high": 300.0,
                "analyst_opinion_count": 48,
            },
            retrieved_at=datetime(2026, 4, 10, tzinfo=timezone.utc),
        ),
    )

    view = analyst_consensus(item, date(2026, 4, 28))

    assert view["available"] is True
    assert view["target"] == 240.0
    assert view["reference_kind"] == "中位"
    assert view["upside"] == 20.0
    assert view["range_label"] == "USD 170.00–300.00"
    assert view["opinion_count"] == 48
    assert view["stale"] is True


def test_named_analyst_targets_require_attribution_and_matching_currency() -> None:
    anchor = date(2026, 4, 28)
    articles = [
        NewsArticle(
            ticker="NVDA",
            title="Morgan Stanley raises Nvidia price target from $220 to $250",
            source="Reuters",
            domain="reuters.com",
            published_at=datetime(2026, 4, 27, tzinfo=timezone.utc),
            url="https://reuters.com/nvda-target",
            summary="",
            event_type="analyst",
            importance_score=0.9,
        ),
        NewsArticle(
            ticker="NVDA",
            title="Goldman Sachs raises Nvidia price target to $300",
            source="Seeking Alpha",
            domain="seekingalpha.com",
            published_at=datetime(2026, 4, 27, tzinfo=timezone.utc),
            url="https://seekingalpha.com/nvda-target",
            summary="",
            event_type="analyst",
            importance_score=0.9,
        ),
        NewsArticle(
            ticker="NVDA",
            title="高盛將台積電目標價上調至新台幣 1,800 元",
            source="Reuters",
            domain="reuters.com",
            published_at=datetime(2026, 4, 27, tzinfo=timezone.utc),
            url="https://reuters.com/tw-target",
            summary="",
            event_type="analyst",
            importance_score=0.9,
        ),
    ]
    item = TickerReport(
        ticker=TickerConfig(symbol="NVDA", company_name="NVIDIA"),
        articles=articles,
        x_signals=[],
        valuation=None,
        earnings=None,
    )

    targets = named_analyst_targets(item, anchor)

    assert len(targets) == 1
    assert targets[0]["firm"] == "摩根士丹利"
    assert targets[0]["target"] == 250.0
    assert targets[0]["previous_target"] == 220.0
    assert targets[0]["currency"] == "USD"


def test_named_analyst_targets_parse_taiwan_dollar_headline() -> None:
    article = NewsArticle(
        ticker="2330.TW",
        title="高盛將台積電目標價由 1,600 元上調至 1,800 元",
        source="經濟日報",
        domain="money.udn.com",
        published_at=datetime(2026, 4, 27, tzinfo=timezone.utc),
        url="https://money.udn.com/tsmc-target",
        summary="",
        event_type="analyst",
        importance_score=0.9,
    )
    item = TickerReport(
        ticker=TickerConfig(symbol="2330.TW", company_name="台積電", market="twse", currency="TWD"),
        articles=[article],
        x_signals=[],
        valuation=None,
        earnings=None,
    )

    targets = named_analyst_targets(item, date(2026, 4, 28))

    assert targets[0]["target_label"] == "TWD 1,800.00"
    assert targets[0]["previous_label"] == "TWD 1,600.00"


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
                "last_close": 102.0,
                "previous_close": 101.0,
                "sma_20": 100.0,
                "sma_60": 95.0,
                "sma_120": 90.0,
                "return_20d": 10.0,
                "return_60d": 15.0,
                "return_120d": 20.0,
                "volume_vs_20d": 1.8,
                "fy1_eps_revision_30d": 3.0,
                "rsi_14": 60.0,
                "forward_pe": 30.0,
                "fifty_two_week_high": 140.0,
                "prior_20d_high": 101.0,
                "prior_20d_low": 98.0,
                "atr_20": 2.0,
                "atr_contraction_ratio": 1.0,
                "bb_width_20_percentile": 50.0,
                "volume_5d_vs_20d": 1.1,
                "breakout_days_ago": 1.0,
                "breakout_pivot": 101.0,
                "breakout_hold_pct": 0.99,
                "breakout_volume_vs_20d": 1.8,
            }),
            item("WEAK", {
                "last_close": 95.0,
                "previous_close": 96.0,
                "sma_20": 100.0,
                "sma_60": 98.0,
                "sma_120": 90.0,
                "return_20d": 10.0,
                "return_60d": 12.0,
                "return_120d": 15.0,
                "volume_vs_20d": 1.8,
                "fy1_eps_revision_30d": 3.0,
                "rsi_14": 55.0,
                "forward_pe": 30.0,
                "fifty_two_week_high": 140.0,
                "prior_20d_high": 120.0,
                "prior_20d_low": 80.0,
                "atr_20": 5.0,
                "atr_contraction_ratio": 1.0,
                "bb_width_20_percentile": 50.0,
                "volume_5d_vs_20d": 1.1,
            }),
            item("EVT", {"last_close": 100.0, "fy1_eps_revision_30d": 2.0, "rsi_14": 55.0}, earnings),
            item("CUT", {"last_close": 100.0, "fy1_eps_revision_30d": -2.0, "rsi_14": 55.0}),
        ],
        market_context=MarketContext(benchmark_returns={
            "spy_20d": 2.0,
            "qqq_20d": 3.0,
            "spy_60d": 5.0,
            "qqq_60d": 6.0,
            "spy_120d": 8.0,
            "qqq_120d": 9.0,
        }),
        research_states={
            "ADD": TickerResearchState(ticker="ADD", thesis_state="active"),
            "WEAK": TickerResearchState(ticker="WEAK", thesis_state="active"),
            "EVT": TickerResearchState(ticker="EVT", thesis_state="active"),
            "CUT": TickerResearchState(ticker="CUT", thesis_state="weakening"),
        },
    )

    queue = capital_allocation_queue(report)

    assert [row["item"].ticker.symbol for row in queue["A"]] == ["ADD"]
    assert {row["item"].ticker.symbol for row in queue["C"]} == {"EVT", "WEAK"}
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
    semis = next(row for row in groups if row["label"] == "Semis")
    assert semis["label_zh"] == "半導體"
    assert semis["tiles"][0]["symbol"] == "NVDA"
    assert semis["tiles"][0]["change"] == 4.0
    assert semis["tiles"][0]["bin"] == "up-3"
    # Exclusive assignment: NVDA matches Semis and AI infra, but maps once.
    assert sum(1 for row in groups for tile in row["tiles"] if tile["symbol"] == "NVDA") == 1
    assert triage["catalyst_backed"][0]["item"].ticker.symbol == "NVDA"
    assert triage["catalyst_backed"][0]["headline_count"] == 1
    assert "trusted" in triage["catalyst_backed"][0]["source_tier"] or "tier" in triage["catalyst_backed"][0]["source_tier"]
    assert triage["unclear"][0]["item"].ticker.symbol == "QUIET"


def test_us_sector_map_uses_decision_oriented_groups() -> None:
    cases = [
        ("COHR", ["optical networking", "photonics"]),
        ("AMD", ["GPU", "CPU", "AI chips"]),
        ("INTC", ["foundry", "CPU", "semiconductor"]),
        ("ARM", ["chip design", "CPU architecture"]),
        ("MSFT", ["Azure", "Copilot"]),
        ("PLTR", ["AIP", "data analytics", "artificial intelligence"]),
        ("TSLA", ["electric vehicles", "energy storage"]),
    ]
    report = DailyReport(
        report_date=date(2026, 7, 20),
        generated_at=datetime(2026, 7, 20, tzinfo=timezone.utc),
        ticker_reports=[
            TickerReport(
                ticker=TickerConfig(symbol=symbol, company_name=symbol, keywords=keywords),
                articles=[],
                x_signals=[],
                valuation=None,
                earnings=None,
            )
            for symbol, keywords in cases
        ],
    )

    groups = sector_leadership(report)
    assigned = {
        tile["symbol"]: row["label_zh"]
        for row in groups
        for tile in row["tiles"]
    }

    assert assigned == {
        "COHR": "光通訊／光子元件",
        "AMD": "CPU",
        "INTC": "CPU",
        "ARM": "CPU",
        "MSFT": "企業軟體／雲端／AI 平台",
        "PLTR": "企業軟體／雲端／AI 平台",
        "TSLA": "電動車／能源儲存",
    }

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


def test_daily_summary_prioritizes_decision_items() -> None:
    summary = daily_summary(_sample_report())

    assert summary["headline"].startswith("今天分成")
    assert summary["tone"] == "danger"
    assert summary["items"][0]["label"] == "盤前缺口"
    assert summary["items"][0]["anchor"] == "#ticker-nvda"
    assert any(item["label"] == "重點新聞" for item in summary["items"])


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

    assert labels == ["盤勢", "盤前", "主要風險", "今日焦點"]
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
    assert "earnings 6天後" in alerts[0]["title"]
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


def test_premarket_section_excludes_non_us_watchlist_rows() -> None:
    report = _sample_report()
    taiwan_item = TickerReport(
        ticker=TickerConfig(
            symbol="2330.TW",
            company_name="台積電",
            market="twse",
            currency="TWD",
        ),
        articles=[],
        x_signals=[],
        valuation=None,
        earnings=None,
    )
    taiwan_move = PremarketMove(
        symbol="2330.TW",
        name="台積電",
        last=1100.0,
        previous_close=1000.0,
        change_pct=10.0,
        source="latest close",
    )
    assert report.premarket is not None
    mixed = replace(
        report,
        ticker_reports=[*report.ticker_reports, taiwan_item],
        premarket=replace(
            report.premarket,
            watchlist_movers=[taiwan_move, *report.premarket.watchlist_movers],
            gap_movers=[taiwan_move, *report.premarket.gap_movers],
        ),
    )

    output = render_html_report(mixed)
    premarket_html = output.split('<section id="premarket"', 1)[1].split("</section>", 1)[0]

    assert "2330.TW" not in premarket_html
    assert [move.symbol for move in premarket_watchlist_moves(mixed)] == ["NVDA"]
    assert [move.symbol for move in premarket_watchlist_moves(mixed, gaps=True)] == ["NVDA"]
    assert build_summary(mixed)["premarket_gap_count"] == 1

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


def _make_history_point(
    report_date: date,
    attention_score: float = 0.0,
    rsi: float | None = None,
    news_count: int = 0,
    valuation_risk: str = "None",
) -> TickerHistoryPoint:
    return TickerHistoryPoint(
        report_date=report_date,
        generated_at=datetime(report_date.year, report_date.month, report_date.day, tzinfo=timezone.utc),
        ticker="NVDA",
        thesis_state="watching",
        review_status="not-reviewed",
        news_count=news_count,
        top_news_count=0,
        valuation_risk=valuation_risk,
        rsi=rsi,
        daily_change_pct=None,
        premarket_change_pct=None,
        earnings_days=None,
        warning_count=0,
        attention_score=attention_score,
        news_burst_score=0.0,
    )


def _delta_report(curr: TickerHistoryPoint, prev: TickerHistoryPoint) -> DailyReport:
    return DailyReport(
        report_date=curr.report_date,
        generated_at=datetime(2026, 4, 28, tzinfo=timezone.utc),
        ticker_reports=[],
        ticker_history={"NVDA": [curr, prev]},
    )


def test_ticker_delta_happy_path() -> None:
    curr = _make_history_point(date(2026, 4, 28), attention_score=14.0, rsi=65.0, news_count=5, valuation_risk="High")
    prev = _make_history_point(date(2026, 4, 27), attention_score=9.0, rsi=62.0, news_count=3, valuation_risk="Elevated")
    report = _delta_report(curr, prev)
    result = ticker_delta(report, "NVDA")
    assert result is not None
    assert result.attention_score_delta == 5.0
    assert result.rsi_delta == 3.0
    assert result.news_count_delta == 2
    assert result.valuation_risk_direction == "up"


def test_ticker_delta_returns_none_with_no_history() -> None:
    report = DailyReport(
        report_date=date(2026, 4, 28),
        generated_at=datetime(2026, 4, 28, tzinfo=timezone.utc),
        ticker_reports=[],
        ticker_history={},
    )
    assert ticker_delta(report, "NVDA") is None


def test_ticker_delta_returns_none_with_only_one_point() -> None:
    curr = _make_history_point(date(2026, 4, 28), attention_score=10.0)
    report = DailyReport(
        report_date=date(2026, 4, 28),
        generated_at=datetime(2026, 4, 28, tzinfo=timezone.utc),
        ticker_reports=[],
        ticker_history={"NVDA": [curr]},
    )
    assert ticker_delta(report, "NVDA") is None


def test_ticker_delta_rsi_none_when_either_missing() -> None:
    curr = _make_history_point(date(2026, 4, 28), rsi=None)
    prev = _make_history_point(date(2026, 4, 27), rsi=60.0)
    report = _delta_report(curr, prev)
    result = ticker_delta(report, "NVDA")
    assert result is not None
    assert result.rsi_delta is None


def test_valuation_risk_direction_up() -> None:
    assert _valuation_risk_direction("None", "High") == "up"
    assert _valuation_risk_direction("Elevated", "Extreme") == "up"


def test_valuation_risk_direction_down() -> None:
    assert _valuation_risk_direction("High", "Elevated") == "down"
    assert _valuation_risk_direction("Extreme", "None") == "down"


def test_valuation_risk_direction_same() -> None:
    assert _valuation_risk_direction("Elevated", "Elevated") == "same"
    assert _valuation_risk_direction(None, "High") == "same"
    assert _valuation_risk_direction("Unknown", "High") == "same"


def _attention_report(
    current: TickerHistoryPoint,
    *,
    is_holding: bool = False,
) -> DailyReport:
    item = TickerReport(
        ticker=TickerConfig(
            symbol="NVDA",
            company_name="NVIDIA",
            position=PositionConfig(status="holding" if is_holding else "watchlist"),
        ),
        articles=[], x_signals=[], valuation=None, earnings=None,
    )
    return DailyReport(
        report_date=current.report_date,
        generated_at=datetime(2026, 4, 28, tzinfo=timezone.utc),
        ticker_reports=[item],
        ticker_history={"NVDA": [current]},
    )


def test_attention_score_breakdown_matches_persisted_formula() -> None:
    current = TickerHistoryPoint(
        report_date=date(2026, 4, 28),
        generated_at=datetime(2026, 4, 28, tzinfo=timezone.utc),
        ticker="NVDA",
        thesis_state="weakening",
        review_status="not-reviewed",
        news_count=4,
        top_news_count=1,
        valuation_risk="High",
        rsi=None,
        daily_change_pct=None,
        premarket_change_pct=None,
        earnings_days=0,
        warning_count=0,
        attention_score=41.0,
        news_burst_score=2.0,
    )
    report = _attention_report(current, is_holding=True)

    result = attention_score_breakdown(report, "NVDA")

    assert result is not None
    assert [(c.label, c.value, c.kind) for c in result] == [
        ("新聞量", 6.0, "news"),
        ("重要新聞", 6.0, "news"),
        ("持股中", 4.0, "holding"),
        ("財報當天", 8.0, "earnings"),
        ("估值風險", 4.0, "risk"),
        ("論點鬆動", 5.0, "risk"),
        ("新聞爆量", 8.0, "burst"),
    ]
    assert sum(c.value for c in result) == current.attention_score


def test_attention_score_breakdown_includes_stale_review_component() -> None:
    current = TickerHistoryPoint(
        report_date=date(2026, 4, 28),
        generated_at=datetime(2026, 4, 28, tzinfo=timezone.utc),
        ticker="NVDA",
        thesis_state="active",
        review_status="not-reviewed",
        news_count=0,
        top_news_count=0,
        valuation_risk="None",
        rsi=None,
        daily_change_pct=None,
        premarket_change_pct=None,
        earnings_days=None,
        warning_count=0,
        attention_score=3.0,
        news_burst_score=0.0,
        last_reviewed_at=None,
    )
    report = _attention_report(current)

    result = attention_score_breakdown(report, "NVDA")

    assert result is not None
    assert [(c.label, c.value, c.kind) for c in result] == [("太久沒複查", 3.0, "stale")]


def test_attention_score_breakdown_returns_none_without_history() -> None:
    report = DailyReport(
        report_date=date(2026, 4, 28),
        generated_at=datetime(2026, 4, 28, tzinfo=timezone.utc),
        ticker_reports=[],
        ticker_history={},
    )
    assert attention_score_breakdown(report, "NVDA") is None


def test_attention_score_breakdown_returns_none_when_all_components_zero() -> None:
    current = TickerHistoryPoint(
        report_date=date(2026, 4, 28),
        generated_at=datetime(2026, 4, 28, tzinfo=timezone.utc),
        ticker="NVDA",
        thesis_state="watching",
        review_status="not-reviewed",
        news_count=0,
        top_news_count=0,
        valuation_risk="None",
        rsi=None,
        daily_change_pct=None,
        premarket_change_pct=None,
        earnings_days=None,
        warning_count=0,
        attention_score=0.0,
        news_burst_score=0.0,
    )
    report = _attention_report(current)

    assert attention_score_breakdown(report, "NVDA") is None


def _plan_report(
    symbol: str = "NVDA",
    last_close: float = 800.0,
    *,
    entry_plan: str = "",
    add_zone: str = "",
    reduce_zone: str = "",
    stop_loss_text: str = "",
    thesis_state: str = "",
    position: PositionConfig | None = None,
    earnings_date: date | None = None,
) -> DailyReport:
    earnings = None
    if earnings_date is not None:
        earnings = EarningsDate(
            ticker=symbol, company_name=f"{symbol} Inc",
            earnings_date=earnings_date, time_of_day="after_market",
            fiscal_quarter="Q1", fiscal_year=2026,
            eps_estimate=None, revenue_estimate=None, source="yfinance",
            source_retrieved_at=datetime(2026, 4, 28, tzinfo=timezone.utc),
        )
    item = TickerReport(
        ticker=TickerConfig(symbol=symbol, company_name=f"{symbol} Inc", position=position or PositionConfig()),
        articles=[],
        x_signals=[],
        valuation=ValuationSnapshot(
            ticker=symbol, as_of_date=date(2026, 4, 28), source="yfinance",
            metrics={"last_close": last_close},
            retrieved_at=datetime(2026, 4, 28, tzinfo=timezone.utc),
        ),
        earnings=earnings,
    )
    state = TickerResearchState(
        ticker=symbol,
        entry_plan=entry_plan, add_zone=add_zone, reduce_zone=reduce_zone,
        stop_loss=stop_loss_text, thesis_state=thesis_state,
    )
    return DailyReport(
        report_date=date(2026, 4, 28),
        generated_at=datetime(2026, 4, 28, tzinfo=timezone.utc),
        ticker_reports=[item],
        research_states={symbol: state},
    )


def test_parse_price_levels_extracts_numbers() -> None:
    assert _parse_price_levels("buy 800-820") == [800.0, 820.0]
    assert _parse_price_levels("add below $1,250.50") == [1250.5]
    assert _parse_price_levels("") == []
    assert _parse_price_levels("no numbers here") == []


def test_plausible_levels_filters_outliers() -> None:
    # last_close 800 → keep 240..2400; drop 30 ("hold 30 days") and 5000
    assert _plausible_levels([30.0, 800.0, 5000.0], 800.0) == [800.0]
    assert _plausible_levels([700.0, 900.0], 800.0) == [700.0, 900.0]


def test_plan_triggers_add_zone_in_zone() -> None:
    report = _plan_report(last_close=810.0, add_zone="800-820")
    triggers = plan_triggers(report)
    assert len(triggers) == 1
    assert triggers[0]["kind"] == "add"
    assert triggers[0]["status"] == "in_zone"
    assert triggers[0]["tone"] == "good"


def test_plan_triggers_reduce_zone_not_reached() -> None:
    # price 810 below reduce zone 900-950 → no trigger
    report = _plan_report(last_close=810.0, reduce_zone="900-950")
    assert plan_triggers(report) == []


def test_plan_triggers_reduce_zone_reached() -> None:
    report = _plan_report(last_close=920.0, reduce_zone="900-950")
    triggers = plan_triggers(report)
    assert len(triggers) == 1
    assert triggers[0]["kind"] == "reduce"
    assert triggers[0]["status"] == "in_zone"


def test_plan_triggers_stop_breached() -> None:
    report = _plan_report(last_close=740.0, stop_loss_text="stop 750")
    triggers = plan_triggers(report)
    assert len(triggers) == 1
    assert triggers[0]["kind"] == "stop"
    assert triggers[0]["tone"] == "danger"
    assert triggers[0]["display_label"] == "計畫停損"
    assert triggers[0]["display_headline"] == "NVDA 跌破計畫停損 $750.00"


def test_plan_triggers_none_without_last_close() -> None:
    report = _plan_report(add_zone="800-820")
    report.ticker_reports[0].valuation.metrics["last_close"] = None
    assert plan_triggers(report) == []


def test_morning_actions_includes_plan_trigger_and_earnings() -> None:
    report = _plan_report(
        last_close=740.0,
        stop_loss_text="stop 750",
        earnings_date=date(2026, 4, 28),
    )
    actions = morning_actions(report)
    labels = {a["label"] for a in actions}
    assert "Plan stop" in labels
    assert "Earnings" in labels
    display_labels = {a["display_label"] for a in actions}
    assert "計畫停損" in display_labels
    assert "財報" in display_labels
    assert any(a["display_headline"] == "NVDA 今日公布財報" for a in actions)
    # stop (rank 6) should sort before earnings (rank 4)
    assert actions[0]["label"] == "Plan stop"


def test_morning_actions_empty_when_quiet() -> None:
    report = _plan_report(last_close=810.0)  # no plan, no earnings, no thesis crack
    assert morning_actions(report) == []


def test_morning_actions_thesis_crack() -> None:
    report = _plan_report(last_close=810.0, thesis_state="broken")
    actions = morning_actions(report)
    assert any(a["label"] == "Thesis" for a in actions)
    assert any(a["display_headline"] == "NVDA 投資論點失效" for a in actions)


def test_ticker_sparkline_renders_svg_with_history() -> None:
    curr = _make_history_point(date(2026, 4, 28), attention_score=14.0)
    prev = _make_history_point(date(2026, 4, 27), attention_score=9.0)
    report = _delta_report(curr, prev)
    svg = ticker_sparkline(report, "NVDA")
    assert svg.startswith("<svg")
    assert "polyline" in svg


def test_ticker_sparkline_empty_with_one_point() -> None:
    curr = _make_history_point(date(2026, 4, 28), attention_score=14.0)
    report = DailyReport(
        report_date=date(2026, 4, 28),
        generated_at=datetime(2026, 4, 28, tzinfo=timezone.utc),
        ticker_reports=[],
        ticker_history={"NVDA": [curr]},
    )
    assert ticker_sparkline(report, "NVDA") == ""


def _holding_report(holdings: list[tuple]) -> DailyReport:
    """holdings: list of (symbol, shares, avg_cost, last_close, prev_close, weight)."""
    reports = []
    for sym, shares, avg_cost, last, prev, weight in holdings:
        reports.append(
            TickerReport(
                ticker=TickerConfig(
                    symbol=sym, company_name=f"{sym} Inc",
                    position=PositionConfig(status="holding", shares=shares, avg_cost=avg_cost, portfolio_weight=weight),
                ),
                articles=[], x_signals=[],
                valuation=ValuationSnapshot(
                    ticker=sym, as_of_date=date(2026, 4, 28), source="yfinance",
                    metrics={"last_close": last, "previous_close": prev},
                    retrieved_at=datetime(2026, 4, 28, tzinfo=timezone.utc),
                ),
                earnings=None,
            )
        )
    return DailyReport(
        report_date=date(2026, 4, 28),
        generated_at=datetime(2026, 4, 28, tzinfo=timezone.utc),
        ticker_reports=reports,
    )


def test_derive_portfolio_weights_normalizes_by_size() -> None:
    # A: 10 sh @ last 150 = 1500; B: 5 sh @ last 100 = 500; total 2000 → 75% / 25%
    report = _holding_report([
        ("A", 10.0, 100.0, 150.0, 150.0, None),
        ("B", 5.0, 100.0, 100.0, 100.0, None),
    ])
    out = derive_portfolio_weights(report)
    weights = {tr.ticker.symbol: tr.ticker.position.portfolio_weight for tr in out.ticker_reports}
    assert weights["A"] == 75.0
    assert weights["B"] == 25.0


def test_derive_portfolio_weights_preserves_manual_override() -> None:
    report = _holding_report([
        ("A", 10.0, 100.0, 150.0, 150.0, 60.0),  # manual weight set
        ("B", 5.0, 100.0, 100.0, 100.0, None),
    ])
    out = derive_portfolio_weights(report)
    weights = {tr.ticker.symbol: tr.ticker.position.portfolio_weight for tr in out.ticker_reports}
    assert weights["A"] == 60.0  # untouched
    assert weights["B"] == 25.0  # derived from total size 2000


def test_derive_portfolio_weights_falls_back_to_avg_cost() -> None:
    # No last_close → size uses avg_cost
    report = DailyReport(
        report_date=date(2026, 4, 28),
        generated_at=datetime(2026, 4, 28, tzinfo=timezone.utc),
        ticker_reports=[
            TickerReport(
                ticker=TickerConfig(symbol="A", company_name="A Inc",
                    position=PositionConfig(status="holding", shares=10.0, avg_cost=100.0)),
                articles=[], x_signals=[], valuation=None, earnings=None,
            )
        ],
    )
    out = derive_portfolio_weights(report)
    assert out.ticker_reports[0].ticker.position.portfolio_weight == 100.0


def test_portfolio_impact_summary_total_pl_leaders_laggards() -> None:
    # MU +69% (avg 100 → last 169), X -20% (avg 100 → last 80)
    report = _holding_report([
        ("MU", 10.0, 100.0, 169.0, 168.0, None),
        ("X", 10.0, 100.0, 80.0, 80.0, None),
    ])
    report = derive_portfolio_weights(report)
    summary = portfolio_impact_summary(report)
    assert summary["pl_leaders"][0]["symbol"] == "MU"
    assert summary["pl_leaders"][0]["pl_pct"] == 69.0
    assert summary["pl_laggards"][0]["symbol"] == "X"
    assert summary["pl_laggards"][0]["pl_pct"] == -20.0
    # total cost 2000, total mv 1690+800=2490 → +490, +24.5%
    assert summary["total_pl_dollar"] == 490.0
    assert summary["total_pl_pct"] == 24.5


def test_portfolio_impact_summary_concentration_default_threshold() -> None:
    # A is 80% of book → over the default 15% threshold
    report = _holding_report([
        ("A", 80.0, 100.0, 100.0, 100.0, None),
        ("B", 20.0, 100.0, 100.0, 100.0, None),
    ])
    report = derive_portfolio_weights(report)
    summary = portfolio_impact_summary(report)
    assert summary["concentration_threshold"] == 15.0
    over = {r["symbol"] for r in summary["over_concentrated"]}
    assert "A" in over   # 80% weight
    assert "B" in over   # 20% weight (also > 15)


def test_portfolio_impact_summary_no_concentration_when_balanced() -> None:
    # 8 equal holdings = 12.5% each, all under 15%
    holdings = [(chr(65 + i), 10.0, 100.0, 100.0, 100.0, None) for i in range(8)]
    report = derive_portfolio_weights(_holding_report(holdings))
    summary = portfolio_impact_summary(report)
    assert summary["over_concentrated"] == []


def test_portfolio_brief_includes_key_lines() -> None:
    report = _holding_report([
        ("MU", 10.0, 100.0, 80.0, 95.0, None),   # total return -20%, down today
        ("ARM", 5.0, 100.0, 174.0, 170.0, None),  # total return +74%, up today
    ])
    report = derive_portfolio_weights(report)
    text = portfolio_brief(report)
    assert "Portfolio Brief - 2026-04-28" in text
    assert "unrealized P&L" in text
    assert "Leaders:" in text or "Laggards:" in text


def test_portfolio_brief_empty_when_no_holdings() -> None:
    report = DailyReport(
        report_date=date(2026, 4, 28),
        generated_at=datetime(2026, 4, 28, tzinfo=timezone.utc),
        ticker_reports=[],
    )
    text = portfolio_brief(report)
    assert "No holdings configured." in text

def test_market_label_uses_taiwan_market_names() -> None:
    assert market_label("us") == "\u7f8e\u80a1"
    assert market_label("twse") == "\u53f0\u80a1"
    assert market_label("tpex") == "\u4e0a\u6ac3"

def test_render_html_report_marks_taiwan_stock_and_uses_short_symbol() -> None:
    report = _sample_report()
    taiwan_item = replace(
        report.ticker_reports[0],
        ticker=TickerConfig(
            symbol="2330.TW",
            company_name="\u53f0\u7063\u7a4d\u9ad4\u96fb\u8def\u88fd\u9020\u80a1\u4efd\u6709\u9650\u516c\u53f8",
            market="twse",
            currency="TWD",
            aliases=["\u53f0\u7a4d\u96fb"],
        ),
    )

    output = render_html_report(replace(report, ticker_reports=[taiwan_item]))

    assert 'data-market="twse"' in output
    assert 'ticker-symbol">2330<span class="market-badge">台股</span>' in output
    assert 'currency-code">TWD</span>' in output


def test_map_change_bin_buckets() -> None:
    assert map_change_bin(None) == "na"
    assert map_change_bin(float("nan")) == "na"
    assert map_change_bin(0.0) == "flat"
    assert map_change_bin(0.5) == "flat"
    assert map_change_bin(-0.5) == "flat"
    assert map_change_bin(0.8) == "up-1"
    assert map_change_bin(1.5) == "up-2"
    assert map_change_bin(3.0) == "up-3"
    assert map_change_bin(-0.8) == "down-1"
    assert map_change_bin(-1.5) == "down-2"
    assert map_change_bin(-4.2) == "down-3"


def test_sector_leadership_assigns_crypto_group() -> None:
    today = date(2026, 7, 10)
    btc = TickerReport(
        ticker=TickerConfig(
            symbol="BTC-USD", company_name="Bitcoin", market="crypto",
            keywords=["crypto", "ETF flows"],
        ),
        articles=[], x_signals=[],
        valuation=ValuationSnapshot(
            ticker="BTC-USD", as_of_date=today, source="yfinance",
            metrics={"last_close": 61800.0, "previous_close": 60000.0, "return_5d": 5.0, "return_20d": 9.0},
            retrieved_at=datetime(2026, 7, 10, tzinfo=timezone.utc),
        ),
        earnings=None,
    )
    report = DailyReport(
        report_date=today,
        generated_at=datetime(2026, 7, 10, tzinfo=timezone.utc),
        ticker_reports=[btc],
    )

    groups = sector_leadership(report)

    crypto = next(row for row in groups if row["label"] == "加密貨幣")
    assert crypto["label_zh"] == "加密貨幣"
    assert crypto["tiles"][0]["symbol"] == "BTC"
    assert crypto["tiles"][0]["bin"] == "up-3"
    assert crypto["tiles"][0]["anchor"] == "ticker-btc-usd"


def test_sector_map_markets_splits_us_tw_crypto() -> None:
    today = date(2026, 7, 10)

    def item(symbol, market, company, keywords, change_pct, cap):
        prev = 100.0
        return TickerReport(
            ticker=TickerConfig(symbol=symbol, company_name=company, market=market, keywords=keywords),
            articles=[], x_signals=[],
            valuation=ValuationSnapshot(
                ticker=symbol, as_of_date=today, source="yfinance",
                metrics={"last_close": prev * (1 + change_pct / 100.0), "previous_close": prev, "market_cap": cap},
                retrieved_at=datetime(2026, 7, 10, tzinfo=timezone.utc),
            ),
            earnings=None,
        )

    report = DailyReport(
        report_date=today,
        generated_at=datetime(2026, 7, 10, tzinfo=timezone.utc),
        ticker_reports=[
            item("NVDA", "us", "NVIDIA", ["GPU"], 2.0, 5e12),
            item("2330.TW", "twse", "台灣積體電路", ["半導體", "晶圓代工"], 1.0, 2e13),
            item("0050.TW", "twse", "元大台灣50", ["台股ETF", "臺灣50指數"], 0.4, 1e11),
            item("BTC-USD", "crypto", "Bitcoin", ["crypto", "ETF flows"], 4.0, 1.2e12),
        ],
    )

    panels = sector_map_markets(report)
    assert [p["key"] for p in panels] == ["us", "taiwan", "crypto"]
    assert [p["label"] for p in panels] == ["美股", "台股", "加密貨幣"]
    assert [p["ticker_count"] for p in panels] == [1, 2, 1]
    # Breadth (漲跌家數): 2330 +1%, 0050 +0.4% — both advancing.
    taiwan_panel = panels[1]
    assert (taiwan_panel["advancers"], taiwan_panel["flat"], taiwan_panel["decliners"]) == (2, 0, 0)

    us_rows, tw_rows, crypto_rows = (p["rows"] for p in panels)
    # Each market uses its own taxonomy: NVDA in the US Semis theme, 2330 in
    # the Taiwan 晶圓代工 chain — never a shared row.
    assert [t["symbol"] for r in us_rows if r["label"] == "Semis" for t in r["tiles"]] == ["NVDA"]
    assert [t["symbol"] for r in tw_rows if r["label"] == "晶圓代工" for t in r["tiles"]] == ["2330"]
    # 0050 lands in the ETF group; BTC's "ETF flows" keyword stays in Crypto.
    assert [t["symbol"] for r in tw_rows if r["label"] == "ETF / 指數" for t in r["tiles"]] == ["0050"]
    assert [t["symbol"] for r in crypto_rows if r["label"] == "加密貨幣" for t in r["tiles"]] == ["BTC"]
    # Every row is tagged with its market for the flat detail table.
    assert all(r["market"] == "taiwan" and r["market_label"] == "台股" for r in tw_rows)


def test_tw_sector_groups_cover_local_chains() -> None:
    today = date(2026, 7, 10)

    def tw_item(symbol, company, keywords, market="twse"):
        return TickerReport(
            ticker=TickerConfig(symbol=symbol, company_name=company, market=market, keywords=keywords),
            articles=[], x_signals=[],
            valuation=ValuationSnapshot(
                ticker=symbol, as_of_date=today, source="yfinance",
                metrics={"last_close": 101.0, "previous_close": 100.0},
                retrieved_at=datetime(2026, 7, 10, tzinfo=timezone.utc),
            ),
            earnings=None,
        )

    report = DailyReport(
        report_date=today,
        generated_at=datetime(2026, 7, 10, tzinfo=timezone.utc),
        ticker_reports=[
            tw_item("3711.TW", "日月光投資控股", ["半導體封裝", "半導體測試", "SiP"]),
            tw_item("2330.TW", "台灣積體電路", ["晶圓代工", "半導體", "CoWoS"]),
            tw_item("3037.TW", "欣興電子", ["ABF 載板", "IC 載板", "高階 HDI", "半導體封裝"]),
            tw_item("8046.TW", "南亞電路板", ["ABF 載板", "BT 載板", "半導體封裝"]),
            tw_item("3189.TW", "景碩科技", ["ABF 載板", "BT 載板", "半導體封裝"]),
            # tpex (上櫃) shares the 台股 panel with twse.
            tw_item("6770.TWO", "力積電", ["功率半導體", "MOSFET"], market="tpex"),
            tw_item("2327.TW", "國巨", ["被動元件", "MLCC"]),
            tw_item("3017.TW", "奇鋐", ["散熱", "水冷"]),
            # 電源 / 重電 outranks 散熱 even though 台達電 also carries 散熱.
            tw_item("2308.TW", "台達電子工業", ["電源供應器", "伺服器電源", "散熱"]),
        ],
    )

    panels = sector_map_markets(report)

    assert len(panels) == 1 and panels[0]["key"] == "taiwan"
    by_label = {row["label"]: [t["symbol"] for t in row["tiles"]] for row in panels[0]["rows"]}
    assert by_label["載板 / PCB"] == ["3037", "8046", "3189"]
    assert by_label["封測"] == ["3711"]
    assert by_label["晶圓代工"] == ["2330"]
    assert by_label["功率元件"] == ["6770"]
    assert by_label["被動元件"] == ["2327"]
    assert by_label["散熱"] == ["3017"]
    assert by_label["電源 / 重電"] == ["2308"]


def test_sector_term_boundary_prevents_substring_false_positives() -> None:
    today = date(2026, 7, 10)

    def us_item(symbol, company, keywords, industry=""):
        return TickerReport(
            ticker=TickerConfig(symbol=symbol, company_name=company, keywords=keywords),
            articles=[], x_signals=[],
            valuation=ValuationSnapshot(
                ticker=symbol, as_of_date=today, source="yfinance",
                metrics={"last_close": 101.0, "previous_close": 100.0, "industry": industry},
                retrieved_at=datetime(2026, 7, 10, tzinfo=timezone.utc),
            ),
            earnings=None,
        )

    report = DailyReport(
        report_date=today,
        generated_at=datetime(2026, 7, 10, tzinfo=timezone.utc),
        ticker_reports=[
            # "sustainable" contains "ai", "systems" contains "ems" — neither
            # may fire now that short tokens are boundary-matched.
            us_item("XYZ", "Xyz Corp", ["sustainable water systems"]),
            # A standalone "AI" keyword still counts.
            us_item("ABCD", "Abcd Corp", ["AI", "data center"]),
            # AAPL belongs to Consumer hardware, not AI infra.
            us_item("AAPL", "Apple Inc.", ["iPhone", "Mac", "services", "AI"], industry="Consumer Electronics"),
            # RKLB belongs to Space, not Other watchlist.
            us_item("RKLB", "Rocket Lab USA", ["space launch", "Electron rocket", "satellites"]),
        ],
    )

    panels = sector_map_markets(report)

    assert len(panels) == 1 and panels[0]["key"] == "us"
    by_label = {row["label"]: [t["symbol"] for t in row["tiles"]] for row in panels[0]["rows"]}
    assert by_label["Other watchlist"] == ["XYZ"]
    assert by_label["AI infra"] == ["ABCD"]
    assert by_label["Consumer hardware"] == ["AAPL"]
    assert by_label["Space"] == ["RKLB"]


def test_sort_by_market_cap_keeps_markets_separate() -> None:
    today = date(2026, 7, 10)

    def item(symbol, market, cap):
        return TickerReport(
            ticker=TickerConfig(symbol=symbol, company_name=symbol, market=market),
            articles=[], x_signals=[],
            valuation=ValuationSnapshot(
                ticker=symbol, as_of_date=today, source="yfinance",
                metrics={"market_cap": cap},
                retrieved_at=datetime(2026, 7, 10, tzinfo=timezone.utc),
            ),
            earnings=None,
        )

    ordered = sort_by_market_cap([
        # 2330's TWD market cap is numerically larger than NVDA's USD cap,
        # but currencies aren't comparable — US names stay first.
        item("2330.TW", "twse", 26e12),
        item("BTC-USD", "crypto", 1.2e12),
        item("NVDA", "us", 5e12),
        item("AAPL", "us", 4e12),
        item("5425.TWO", "tpex", 4e10),
    ])

    assert [tr.ticker.symbol for tr in ordered] == ["NVDA", "AAPL", "2330.TW", "5425.TWO", "BTC-USD"]


def test_html_report_renders_taiwan_snapshot_and_cross_market_link() -> None:
    from stock_daily_research.models import TaiwanMarketSnapshot
    from stock_daily_research.report import format_tw_revenue, format_tw_shares, related_ticker_links

    us_item = TickerReport(
        ticker=TickerConfig(symbol="TSM", company_name="TSMC ADR", related_symbols=["2330.TW"]),
        articles=[], x_signals=[], valuation=None, earnings=None,
    )
    tw_item = TickerReport(
        ticker=TickerConfig(symbol="2330.TW", company_name="TSMC", market="twse", currency="TWD", related_symbols=["TSM"]),
        articles=[], x_signals=[], valuation=None, earnings=None,
        taiwan_market=TaiwanMarketSnapshot(
            ticker="2330.TW", revenue_month="202606", monthly_revenue=100_000_000,
            monthly_revenue_yoy_pct=18.7, cash_dividend_per_share=5.0, dividend_year="2025",
            foreign_net_shares=123_400, investment_trust_net_shares=-50_000,
            dealer_net_shares=1_000, institutional_as_of=date(2026, 7, 14), source="TWSE OpenAPI / T86",
        ),
    )
    report = DailyReport(
        report_date=date(2026, 7, 14), generated_at=datetime(2026, 7, 14, tzinfo=timezone.utc),
        ticker_reports=[us_item, tw_item],
    )

    links = related_ticker_links(report)
    output = render_html_report(report)

    assert links["TSM"][0]["symbol"] == "2330.TW"
    assert links["2330.TW"][0]["symbol"] == "TSM"
    assert 'class="cross-market-links"' in output
    assert 'href="#ticker-2330.tw"' in output
    assert 'class="tw-market-snapshot"' in output
    assert "TWSE OpenAPI / T86" in output
    assert format_tw_shares(123_400).endswith(chr(int("80a1", 16)))
    assert format_tw_revenue(1_390_000) == "13.9" + chr(int("5104", 16)) + chr(int("5143", 16))

def test_relative_strength_uses_taiwan_benchmark_instead_of_us_benchmarks() -> None:
    from stock_daily_research.report import relative_strength, relative_strength_profile

    item = TickerReport(
        ticker=TickerConfig(symbol="2330.TW", company_name="TSMC", market="twse", currency="TWD"),
        articles=[],
        x_signals=[],
        earnings=None,
        valuation=ValuationSnapshot(
            ticker="2330.TW",
            as_of_date=date(2026, 5, 12),
            source="yfinance",
            metrics={"return_20d": 12.0, "return_60d": 20.0, "return_120d": 35.0},
            retrieved_at=datetime(2026, 5, 12, tzinfo=timezone.utc),
        ),
    )
    benchmarks = {
        "spy_20d": 1.0,
        "qqq_20d": 2.0,
        "twii_20d": 8.0,
        "twii_60d": 12.0,
        "twii_120d": 25.0,
    }

    assert relative_strength(item, benchmarks) == {"vs_twii": 4.0}
    profile = relative_strength_profile(item, benchmarks)
    assert profile["benchmark_label"] == "TWII"
    assert profile["positive_horizons"] == 3


def test_right_side_check_structure_is_independent_of_portfolio_budget() -> None:
    from stock_daily_research.models import PortfolioSettings
    from stock_daily_research.report import right_side_check

    item = TickerReport(
        ticker=TickerConfig(
            symbol="X",
            company_name="X Inc",
            currency="USD",
            position=PositionConfig(stop_loss=100.0),
        ),
        articles=[],
        x_signals=[],
        earnings=None,
        valuation=ValuationSnapshot(
            ticker="X",
            as_of_date=date(2026, 5, 12),
            source="yfinance",
            metrics={
                "last_close": 103.5,
                "sma_20": 102.0,
                "sma_60": 98.0,
                "sma_120": 90.0,
                "volume_vs_20d": 1.6,
                "prior_20d_high": 101.0,
                "prior_20d_low": 100.0,
                "atr_20": 1.5,
                "atr_contraction_ratio": 0.65,
                "bb_width_20_percentile": 15.0,
                "volume_5d_vs_20d": 0.70,
                "breakout_days_ago": 2.0,
                "breakout_pivot": 101.0,
                "breakout_hold_pct": 2.48,
                "breakout_volume_vs_20d": 1.6,
            },
            retrieved_at=datetime(2026, 5, 12, tzinfo=timezone.utc),
        ),
    )

    without_budget = right_side_check(item)
    with_budget = right_side_check(
        item,
        portfolio=PortfolioSettings(risk_budget_by_currency={"USD": 100.0}),
    )

    assert without_budget is not None
    assert with_budget is not None
    assert with_budget["status"] == without_budget["status"] == "Right-side ready"
    assert with_budget["checks"] == without_budget["checks"]
    assert {check["label"] for check in with_budget["checks"]} == {
        "Breakout entry",
        "Pullback entry",
        "Contraction watch",
    }

def test_right_side_check_withholds_signal_when_technical_data_is_missing() -> None:
    from stock_daily_research.report import right_side_check

    assert right_side_check(_score_item({"last_close": 100.0})) is None


def test_right_side_signal_validation_uses_archived_observations_and_dedupes_streaks() -> None:
    from stock_daily_research.report import right_side_signal_validation

    start = date(2026, 5, 1)
    session_dates = []
    cursor = start
    while len(session_dates) < 21:
        if cursor.weekday() < 5:
            session_dates.append(cursor.isoformat())
        cursor += timedelta(days=1)
    session_closes = [100.0 + index for index in range(21)]
    item = _score_item({
        "last_close": session_closes[-1],
        "chart_dates_60": session_dates,
        "chart_close_60": session_closes,
    })

    points = [
        TickerHistoryPoint(
            report_date=start + timedelta(days=index),
            generated_at=datetime(2026, 5, 1, tzinfo=timezone.utc) + timedelta(days=index),
            ticker="X",
            last_close=100.0 + index,
            right_side_status="Right-side ready" if index in (0, 1) else "Wait for confirmation",
            signal_entry=100.0,
            signal_stop=95.0,
            signal_risk_pct=5.0,
        )
        for index in range(21)
    ]
    report = DailyReport(
        report_date=date.fromisoformat(session_dates[-1]),
        generated_at=datetime(2026, 5, 29, tzinfo=timezone.utc),
        ticker_reports=[item],
        ticker_history={"X": points},
    )

    validation = right_side_signal_validation(report)

    assert validation["signals_recorded"] == 1
    rows = {row["sessions"]: row for row in validation["horizons"]}
    assert rows[5]["sample_size"] == 1
    assert rows[5]["average_return"] == 5.0
    assert rows[20]["win_rate"] == 100.0
    assert rows[5]["expectancy_r"] == 1.0
    assert rows[20]["expectancy_r"] == 4.0


def test_stock_health_diagnostic_scores_strong_and_weak_setups() -> None:
    from stock_daily_research.report import stock_health_diagnostic

    strong = _score_item({
        "last_close": 120.0, "previous_close": 116.0,
        "sma_20": 110.0, "sma_60": 100.0, "sma_120": 90.0,
        "sma_20_slope_5d": 1.5, "prior_20d_high": 118.0,
        "return_5d": 6.0, "return_20d": 14.0, "rsi_14": 60.0,
        "volume_vs_20d": 1.8, "atr_contraction_ratio": 0.75,
        "bb_width_20_percentile": 20.0, "volume_5d_vs_20d": 0.75,
        "breakout_volume_vs_20d": 1.8, "atr_20_percent": 2.0,
        "fy1_eps_revision_30d": 4.0, "eps_growth_pct": 28.0,
        "revenue_growth_pct": 16.0, "latest_eps_surprise_pct": 7.0,
        "fifty_two_week_high": 130.0,
    })
    weak = replace(
        _score_item({
            "last_close": 50.0, "previous_close": 55.0,
            "sma_20": 60.0, "sma_60": 70.0, "sma_120": 80.0,
            "sma_20_slope_5d": -2.0, "return_5d": -8.0,
            "return_20d": -18.0, "rsi_14": 35.0,
            "volume_vs_20d": 2.0, "atr_20_percent": 9.0,
            "fy1_eps_revision_30d": -5.0, "eps_growth_pct": -20.0,
            "revenue_growth_pct": -12.0, "latest_eps_surprise_pct": -8.0,
            "fifty_two_week_high": 100.0, "forward_pe": 250.0,
        }),
        warnings=["stale valuation"],
    )

    strong_result = stock_health_diagnostic(
        strong,
        date(2026, 5, 12),
        {"spy_20d": 3.0, "qqq_20d": 5.0},
    )
    weak_result = stock_health_diagnostic(
        weak,
        date(2026, 5, 12),
        {"spy_20d": 3.0, "qqq_20d": 5.0},
    )

    assert strong_result["score"] >= 75
    assert strong_result["coverage"] == 5
    assert {"breakout", "squeeze", "fundamental", "unusual"}.issubset(strong_result["matches"])
    assert weak_result["score"] < strong_result["score"]
    assert weak_result["dimension_map"]["risk"]["score"] < 45
    assert "risk" in weak_result["matches"]


def test_stock_health_diagnostic_excludes_missing_fundamentals_from_average() -> None:
    from stock_daily_research.report import stock_health_diagnostic

    item = replace(
        _score_item({
            "last_close": 101.0, "previous_close": 100.0,
            "sma_20": 99.0, "sma_60": 95.0, "sma_120": 90.0,
            "sma_20_slope_5d": 0.5, "return_5d": 2.0,
            "return_20d": 6.0, "rsi_14": 55.0,
            "volume_vs_20d": 1.0, "atr_20_percent": 2.5,
        }),
        ticker=TickerConfig(
            symbol="0050.TW", company_name="ETF", market="twse",
            currency="TWD", has_fundamentals=False,
        ),
    )

    result = stock_health_diagnostic(item, date(2026, 5, 12), {"twii_20d": 2.0})

    assert result["score"] is not None
    assert result["dimension_map"]["fundamental"]["score"] is None
    assert result["coverage"] == 4


def test_stock_health_diagnostic_suspends_technical_dimensions_during_regime_reset() -> None:
    from stock_daily_research.report import stock_health_diagnostic

    item = _score_item({
        "last_close": 100.0, "previous_close": 99.0,
        "sma_20": 95.0, "sma_60": 90.0, "sma_120": 85.0,
        "price_regime_change_date": "2026-05-08",
        "price_regime_change_pct": -50.0,
        "price_history_sessions": 4,
    })

    result = stock_health_diagnostic(item, date(2026, 5, 12))

    assert result["status"] == "\u6307\u6a19\u91cd\u5efa\u4e2d"
    assert result["dimension_map"]["trend"]["score"] is None
    assert result["dimension_map"]["momentum"]["score"] is None
    assert "risk" in result["matches"]


def test_strategy_screener_keeps_market_rankings_separate() -> None:
    from stock_daily_research.report import strategy_screener

    metrics = {
        "last_close": 120.0, "previous_close": 115.0,
        "sma_20": 110.0, "sma_60": 100.0, "sma_120": 90.0,
        "sma_20_slope_5d": 1.2, "prior_20d_high": 118.0,
        "return_5d": 5.0, "return_20d": 12.0, "rsi_14": 60.0,
        "volume_vs_20d": 1.8, "atr_20_percent": 2.0,
        "fy1_eps_revision_30d": 4.0, "eps_growth_pct": 20.0,
    }
    us = replace(_score_item(metrics), ticker=TickerConfig("NVDA", "NVIDIA", market="us"))
    tw = replace(
        _score_item(metrics),
        ticker=TickerConfig("2330.TW", "TSMC", market="twse", currency="TWD"),
    )
    crypto = replace(
        _score_item({key: value for key, value in metrics.items() if key not in {"fy1_eps_revision_30d", "eps_growth_pct"}}),
        ticker=TickerConfig("BTC-USD", "Bitcoin", market="crypto", has_fundamentals=False),
    )
    report = DailyReport(
        report_date=date(2026, 5, 12),
        generated_at=datetime(2026, 5, 12, tzinfo=timezone.utc),
        ticker_reports=[us, tw, crypto],
    )

    result = strategy_screener(report, limit_per_market=1)
    overall = next(strategy for strategy in result["strategies"] if strategy["key"] == "overall")
    breakout = next(strategy for strategy in result["strategies"] if strategy["key"] == "breakout")

    assert [row["market"] for row in overall["rows"]] == ["us", "taiwan", "crypto"]
    assert [row["rank"] for row in overall["rows"]] == [1, 1, 1]
    assert {row["ticker"] for row in breakout["rows"]} == {"NVDA", "2330.TW", "BTC-USD"}


def _score_trend_point(
    report_date: date,
    data_date: date,
    *,
    health_score: float | None = None,
    right_side_score: float | None = None,
    health_version: str = "health-v1",
    right_side_version: str = "right-side-v1",
) -> TickerHistoryPoint:
    return TickerHistoryPoint(
        report_date=report_date,
        generated_at=datetime.combine(report_date, datetime.min.time(), tzinfo=timezone.utc),
        ticker="NVDA",
        score_data_date=data_date,
        health_score=health_score,
        health_rule_version=health_version,
        right_side_score=right_side_score,
        right_side_rule_version=right_side_version,
    )


def test_score_trend_uses_distinct_data_dates_and_ignores_weekend_duplicates() -> None:
    from stock_daily_research.report import score_trend

    report = DailyReport(
        report_date=date(2026, 7, 20),
        generated_at=datetime(2026, 7, 20, tzinfo=timezone.utc),
        ticker_reports=[],
        ticker_history={
            "NVDA": [
                _score_trend_point(date(2026, 7, 20), date(2026, 7, 17), health_score=71),
                _score_trend_point(date(2026, 7, 19), date(2026, 7, 17), health_score=70),
                _score_trend_point(date(2026, 7, 18), date(2026, 7, 17), health_score=69),
                _score_trend_point(date(2026, 7, 16), date(2026, 7, 16), health_score=68),
                _score_trend_point(date(2026, 7, 15), date(2026, 7, 15), health_score=65),
            ]
        },
    )

    trend = score_trend(report, "NVDA", "health")

    assert trend is not None
    assert trend["direction"] == "up"
    assert trend["delta"] == 6.0
    assert trend["observations"] == 3
    assert trend["start_date"] == date(2026, 7, 15)
    assert trend["end_date"] == date(2026, 7, 17)


def test_score_trend_requires_three_observations_from_the_same_rule_version() -> None:
    from stock_daily_research.report import score_trend

    report = DailyReport(
        report_date=date(2026, 7, 20),
        generated_at=datetime(2026, 7, 20, tzinfo=timezone.utc),
        ticker_reports=[],
        ticker_history={
            "NVDA": [
                _score_trend_point(
                    date(2026, 7, 20),
                    date(2026, 7, 18),
                    health_score=72,
                    health_version="health-v2",
                ),
                _score_trend_point(date(2026, 7, 17), date(2026, 7, 17), health_score=68),
                _score_trend_point(date(2026, 7, 16), date(2026, 7, 16), health_score=65),
            ]
        },
    )

    assert score_trend(report, "NVDA", "health") is None


def test_score_trend_does_not_show_stale_history_when_current_score_is_missing() -> None:
    from stock_daily_research.report import score_trend

    report = DailyReport(
        report_date=date(2026, 7, 20),
        generated_at=datetime(2026, 7, 20, tzinfo=timezone.utc),
        ticker_reports=[],
        ticker_history={
            "NVDA": [
                _score_trend_point(date(2026, 7, 20), date(2026, 7, 20)),
                _score_trend_point(date(2026, 7, 17), date(2026, 7, 17), health_score=70),
                _score_trend_point(date(2026, 7, 16), date(2026, 7, 16), health_score=66),
                _score_trend_point(date(2026, 7, 15), date(2026, 7, 15), health_score=62),
            ]
        },
    )

    assert score_trend(report, "NVDA", "health") is None

def test_score_trend_handles_flat_health_and_rising_right_side_scores() -> None:
    from stock_daily_research.report import score_trend

    report = DailyReport(
        report_date=date(2026, 7, 18),
        generated_at=datetime(2026, 7, 18, tzinfo=timezone.utc),
        ticker_reports=[],
        ticker_history={
            "NVDA": [
                _score_trend_point(
                    date(2026, 7, 18),
                    date(2026, 7, 18),
                    health_score=62,
                    right_side_score=68,
                ),
                _score_trend_point(
                    date(2026, 7, 17),
                    date(2026, 7, 17),
                    health_score=61,
                    right_side_score=64,
                ),
                _score_trend_point(
                    date(2026, 7, 16),
                    date(2026, 7, 16),
                    health_score=60,
                    right_side_score=60,
                ),
            ]
        },
    )

    health = score_trend(report, "NVDA", "health")
    right_side = score_trend(report, "NVDA", "right_side")

    assert health is not None
    assert health["direction"] == "flat"
    assert health["delta_label"] == "+2"
    assert right_side is not None
    assert right_side["direction"] == "up"
    assert right_side["delta_label"] == "+8"


def test_score_history_snapshot_records_dimensions_and_rule_versions() -> None:
    from stock_daily_research.report import score_history_snapshot

    item = _score_item({
        "last_close": 120.0,
        "previous_close": 116.0,
        "sma_20": 110.0,
        "sma_60": 100.0,
        "sma_120": 90.0,
        "return_5d": 4.0,
        "return_20d": 12.0,
        "rsi_14": 60.0,
        "volume_vs_20d": 1.6,
        "atr_20_percent": 2.0,
        "fy1_eps_revision_30d": 4.0,
        "eps_growth_pct": 20.0,
        "chart_dates_60": ["2026-05-08", "2026-05-09"],
    })

    snapshot = score_history_snapshot(item, date(2026, 5, 12), {"spy_20d": 3.0})

    assert snapshot["data_date"] == date(2026, 5, 9)
    assert snapshot["health_score"] is not None
    assert snapshot["health_trend_score"] is not None
    assert snapshot["health_coverage"] >= 3
    assert snapshot["health_rule_version"] == "health-v1"
    assert snapshot["right_side_score"] is not None
    assert snapshot["right_side_rule_version"] == "right-side-v1"


def test_html_report_renders_health_and_right_side_score_trends() -> None:
    report = replace(
        _sample_report(),
        ticker_history={
            "NVDA": [
                _score_trend_point(
                    date(2026, 4, 28),
                    date(2026, 4, 28),
                    health_score=72,
                    right_side_score=75,
                ),
                _score_trend_point(
                    date(2026, 4, 27),
                    date(2026, 4, 27),
                    health_score=68,
                    right_side_score=70,
                ),
                _score_trend_point(
                    date(2026, 4, 26),
                    date(2026, 4, 26),
                    health_score=62,
                    right_side_score=65,
                ),
            ]
        },
    )

    output = render_html_report(report)

    assert "近 3 個有效資料日" in output
    assert "score-trend score-trend-up" in output
    assert "↑ +10" in output

def test_html_report_renders_free_strategy_screener_and_health_diagnostic() -> None:
    output = render_html_report(_sample_report())

    assert 'id="strategy-screener"' in output
    assert 'id="strategy-screen-select"' in output
    assert 'stock-daily-screener-strategy' in output
    assert 'class="health-diagnostic"' in output
    assert 'data-health-score=' in output
    assert 'class="strategy-screen-row" data-market="us"' in output

def test_stock_health_diagnostic_does_not_overrate_negative_eps_growth() -> None:
    from stock_daily_research.report import stock_health_diagnostic

    item = _score_item({
        "last_close": 20.0, "previous_close": 19.0,
        "sma_20": 18.0, "sma_60": 17.0, "sma_120": 16.0,
        "ttm_eps": -1.0, "eps_growth_pct": 120.0,
        "fy1_eps_revision_30d": 4.0, "revenue_growth_pct": 30.0,
        "latest_eps_surprise_pct": 12.0,
    })

    result = stock_health_diagnostic(item, date(2026, 5, 12))
    fundamental = result["dimension_map"]["fundamental"]

    assert fundamental["score"] < 100
    assert any("EPS" in evidence for evidence in fundamental["evidence"])

def test_taiwan_margin_maintenance_is_market_scoped_and_decision_oriented() -> None:
    from stock_daily_research.models import TaiwanMarketOverview
    from stock_daily_research.report import taiwan_margin_maintenance_view

    us_item = TickerReport(
        ticker=TickerConfig(symbol="NVDA", company_name="NVIDIA"),
        articles=[],
        x_signals=[],
        valuation=None,
        earnings=None,
    )
    tw_item = TickerReport(
        ticker=TickerConfig(
            symbol="2330.TW",
            company_name="TSMC",
            market="twse",
            currency="TWD",
        ),
        articles=[],
        x_signals=[],
        valuation=None,
        earnings=None,
    )
    overview = TaiwanMarketOverview(
        as_of_date=date(2026, 7, 28),
        margin_maintenance_ratio_estimate=163.08,
        collateral_value_thousand_twd=889_641_682.48,
        financing_balance_thousand_twd=545_534_811.0,
        previous_financing_balance_thousand_twd=568_663_408.0,
        priced_margin_units=9_094_733.0,
        total_margin_units=9_096_008.0,
        price_coverage_pct=99.99,
        priced_security_count=1_218,
        margin_security_count=1_223,
        source="TWSE MI_MARGN / MI_INDEX",
        retrieved_at=datetime(2026, 7, 29, 1, tzinfo=timezone.utc),
    )
    report = DailyReport(
        report_date=date(2026, 7, 29),
        generated_at=datetime(2026, 7, 29, 1, tzinfo=timezone.utc),
        ticker_reports=[us_item, tw_item],
        taiwan_market_overview=overview,
    )

    view = taiwan_margin_maintenance_view(report)
    html = render_html_report(report)
    markdown = render_markdown_report(report)

    assert view["ratio_label"] == "163.1%"
    assert view["status"] == "\u4e2d\u6027\u5340\u9593"
    assert view["balance_label"] == "\u878d\u8cc7\u9918\u984d 5,455.3 \u5104\u5143"
    assert view["balance_change_label"] == "\u8f03\u524d\u65e5 -4.07%"
    assert view["coverage_label"] == "\u6536\u76e4\u50f9\u8986\u84cb 99.99%"
    assert view["source_label"] == "\u8b49\u4ea4\u6240\u76e4\u5f8c\u8cc7\u6599 \u00b7 \u8cc7\u6599\u65e5 2026-07-28"
    assert 'id="taiwan-margin-context"' in html
    assert 'data-market-context="taiwan" hidden' in html
    assert "\u4e0a\u5e02\u5927\u76e4\u878d\u8cc7\u7dad\u6301\u7387\uff08\u4f30\u7b97\uff09" in html
    assert "context.hidden = context.dataset.marketContext !== activeMarket;" in html
    assert "\u4e0a\u5e02\u5927\u76e4\u878d\u8cc7\u7dad\u6301\u7387\uff08\u4f30\u7b97\uff09\uff1a163.1% \u00b7 \u4e2d\u6027\u5340\u9593" in markdown
    assert "\u4e0d\u7b49\u540c\u500b\u5225\u4fe1\u7528\u5e33\u6236\u7684\u6b63\u5f0f\u6574\u6236\u7dad\u6301\u7387" in markdown
    assert "-4.07%\n- " in markdown
    assert "99.99%\n- " in markdown

    us_only = replace(report, ticker_reports=[us_item])
    assert taiwan_margin_maintenance_view(us_only)["visible"] is False
    assert 'id="taiwan-margin-context"' not in render_html_report(us_only)
