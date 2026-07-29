from datetime import date, datetime, timedelta, timezone

import pandas as pd
import pytest

from stock_daily_research.models import (
    AppSettings,
    DailyReport,
    MarketContext,
    PortfolioSettings,
    PositionConfig,
    TickerConfig,
    TickerHistoryPoint,
    TickerReport,
    TradeFill,
    TradeJournalEntry,
    ValuationSnapshot,
)
from stock_daily_research.report import (
    portfolio_risk_overview,
    price_structure_chart,
    render_html_report,
    right_side_execution_plan,
    right_side_signal_validation,
    trade_journal_summary,
)
from stock_daily_research.storage import (
    export_research_state_payload,
    import_research_state_payload,
    init_db,
    load_latest_valuation_snapshot,
    load_trade_journal_entries,
    save_valuation,
    upsert_trade_journal_entry,
)
from stock_daily_research.valuation import compute_price_chart_metrics


def _item(
    symbol: str = "NVDA",
    *,
    market: str = "us",
    currency: str = "USD",
    closes: list[float] | None = None,
    position: PositionConfig | None = None,
) -> TickerReport:
    closes = closes or [80.0 + index * 0.4 for index in range(60)]
    start = date(2026, 4, 1)
    dates = [(start + timedelta(days=index)).isoformat() for index in range(len(closes))]
    metrics = {
        "last_close": closes[-1],
        "previous_close": closes[-2],
        "market_cap": 100_000_000_000,
        "forward_pe": 30.0,
        "return_20d": 15.0,
        "return_60d": 25.0,
        "return_120d": 35.0,
        "sma_20": closes[-1] - 2.0,
        "sma_60": closes[-1] - 5.0,
        "sma_120": closes[-1] - 8.0,
        "atr_contraction_ratio": 0.7,
        "bb_width_20_percentile": 15.0,
        "volume_5d_vs_20d": 0.7,
        "breakout_days_ago": 1.0,
        "breakout_pivot": closes[-1] - 3.0,
        "breakout_hold_pct": 3.0,
        "breakout_volume_vs_20d": 1.5,
        "prior_20d_high": closes[-1] - 3.0,
        "prior_20d_low": closes[-1] - 4.0,
        "atr_20": 2.0,
        "avg_dollar_volume_20d": 100_000_000.0,
        "chart_dates_60": dates,
        "chart_close_60": closes,
        "chart_high_60": [value + 1.0 for value in closes],
        "chart_low_60": [value - 1.0 for value in closes],
        "chart_volume_60": [1_000_000.0 for _ in closes],
        "chart_sma20_60": [value - 1.0 for value in closes],
        "chart_sma60_60": [value - 2.0 for value in closes],
        "sector": "Semiconductors",
        "industry": "Semiconductors",
    }
    ticker = TickerConfig(
        symbol=symbol,
        company_name=symbol,
        market=market,
        currency=currency,
        keywords=["semiconductor", "foundry"],
        position=position or PositionConfig(),
    )
    return TickerReport(
        ticker=ticker,
        articles=[],
        x_signals=[],
        valuation=ValuationSnapshot(
            ticker=symbol,
            as_of_date=date(2026, 7, 16),
            source="test",
            metrics=metrics,
            retrieved_at=datetime(2026, 7, 16, tzinfo=timezone.utc),
        ),
        earnings=None,
    )


def _report(items: list[TickerReport], **kwargs) -> DailyReport:
    return DailyReport(
        report_date=date(2026, 7, 16),
        generated_at=datetime(2026, 7, 16, 8, tzinfo=timezone.utc),
        ticker_reports=items,
        **kwargs,
    )


def test_price_chart_metrics_are_aligned_and_include_liquidity() -> None:
    index = pd.date_range("2026-01-01", periods=80, freq="D")
    frame = pd.DataFrame(
        {
            "Open": [100.0 + index for index in range(80)],
            "High": [101.0 + index for index in range(80)],
            "Low": [99.0 + index for index in range(80)],
            "Close": [100.0 + index for index in range(80)],
            "Volume": [1_000_000.0 for _ in range(80)],
        },
        index=index,
    )

    metrics = compute_price_chart_metrics(frame)

    assert len(metrics["chart_dates_60"]) == 60
    assert len(metrics["chart_close_60"]) == len(metrics["chart_sma20_60"]) == 60
    assert metrics["chart_dates_60"][0] == "2026-01-21"
    assert metrics["avg_volume_20d"] == 1_000_000.0
    assert metrics["avg_dollar_volume_20d"] == pytest.approx(169_500_000.0)


def test_trade_journal_and_chart_metrics_roundtrip_sqlite(tmp_path) -> None:
    first_db = tmp_path / "first.sqlite3"
    second_db = tmp_path / "second.sqlite3"
    trade = TradeJournalEntry(
        trade_id="nvda-1",
        ticker="NVDA",
        entry_date=date(2026, 7, 1),
        entry_price=100.0,
        shares=10.0,
        current_stop=97.0,
        initial_risk=50.0,
        fx_rate_to_base=31.5,
        fills=[TradeFill("nvda-1-buy", "buy", date(2026, 7, 1), 100.0, 10.0, 1.0)],
        initial_stop=95.0,
        setup="breakout",
        updated_at=datetime(2026, 7, 1, 8, tzinfo=timezone.utc),
    )
    snapshot = _item().valuation
    assert snapshot is not None

    with init_db(first_db) as conn:
        upsert_trade_journal_entry(conn, trade)
        save_valuation(conn, snapshot)
        payload = export_research_state_payload(conn)
        loaded_snapshot = load_latest_valuation_snapshot(conn, "NVDA", before_or_on=date(2026, 7, 16))

    assert payload["version"] == 2
    assert payload["trades"][0]["trade_id"] == "nvda-1"
    assert loaded_snapshot is not None
    assert isinstance(loaded_snapshot.metrics["chart_close_60"], list)
    assert len(loaded_snapshot.metrics["chart_close_60"]) == 60

    with init_db(second_db) as conn:
        import_research_state_payload(conn, payload)
        imported = load_trade_journal_entries(conn)

    assert imported == [trade]


def test_execution_plan_requires_all_hard_gates_and_sizes_by_risk_budget() -> None:
    item = _item()
    report = _report(
        [item],
        market_context=MarketContext(
            benchmark_returns={
                "spy_20d": 5.0,
                "qqq_20d": 6.0,
                "spy_60d": 10.0,
                "qqq_60d": 11.0,
                "spy_120d": 15.0,
                "qqq_120d": 16.0,
            }
        ),
        settings=AppSettings(
            portfolio=PortfolioSettings(risk_budget_by_currency={"USD": 1_000.0})
        ),
    )

    plan = right_side_execution_plan(report, item)

    assert plan is not None
    assert plan["status"] == "ready"
    assert plan["display_mode"] == "plan"
    assert plan["has_price_plan"] is True
    assert plan["invalidation"] == pytest.approx(item.valuation.metrics["prior_20d_low"])
    assert plan["target_2r"] > plan["entry_reference"]
    assert plan["max_units"] == int(1_000 // plan["risk_per_unit"])
    assert all(gate["passed"] for gate in plan["gates"] if gate["required"])
    group_gate = next(gate for gate in plan["gates"] if gate["key"] == "group")
    assert group_gate["required"] is False

    peer = _item("AVGO")
    peer.valuation.metrics["return_20d"] = 20.0
    lagging = right_side_execution_plan(
        _report(
            [item, peer],
            market_context=report.market_context,
            settings=report.settings,
        ),
        item,
    )
    lagging_group = next(gate for gate in lagging["gates"] if gate["key"] == "group")
    assert lagging_group["required"] is True
    assert lagging_group["passed"] is False
    assert lagging["status"] == "watch"


def test_execution_plan_keeps_missing_setup_as_watch_not_blocked() -> None:
    item = _item()
    metrics = item.valuation.metrics
    metrics.update({
        "last_close": 90.0,
        "previous_close": 95.0,
        "sma_20": 100.0,
        "sma_60": 105.0,
        "sma_120": 110.0,
        "prior_20d_high": 120.0,
        "prior_20d_low": 70.0,
        "atr_20": 10.0,
        "atr_contraction_ratio": 1.2,
        "bb_width_20_percentile": 60.0,
        "volume_5d_vs_20d": 1.2,
    })
    for key in (
        "breakout_days_ago",
        "breakout_pivot",
        "breakout_hold_pct",
        "breakout_volume_vs_20d",
    ):
        metrics.pop(key, None)

    plan = right_side_execution_plan(_report([item]), item)

    assert plan is not None
    assert plan["status"] == "watch"
    assert plan["status_label"] == "Trend weak, stay out"
    assert plan["display_mode"] == "waiting"
    assert plan["has_price_plan"] is False
    assert plan["waiting_title"] == "目前沒有可執行交易計畫"
    assert "趨勢尚未轉強" in plan["waiting_detail"]
    assert plan["watch_references"] == [
        {"label": "站回 MA20", "value": 100.0, "distance_pct": 11.11},
        {"label": "突破前 20 日高點", "value": 120.0, "distance_pct": 33.33},
    ]
    assert plan["entry_trigger"] is None
    assert plan["invalidation"] is None
    assert plan["target_2r"] is None
    assert plan["risk_pct"] is None
    structure = next(gate for gate in plan["gates"] if gate["key"] == "structure")
    risk = next(gate for gate in plan["gates"] if gate["key"] == "risk")
    assert structure["passed"] is False
    assert risk["passed"] is False
    assert risk["required"] is False
    assert plan["failed_count"] == 1

    html = render_html_report(_report([item]))
    start = html.index('<div class="execution-plan')
    end = html.index('<details class="card-secondary position-details">', start)
    execution_html = html[start:end]
    assert 'class="execution-waiting"' in execution_html
    assert "目前沒有可執行交易計畫" in execution_html
    assert "站回 MA20" in execution_html
    assert '<div class="execution-plan-grid">' not in execution_html
    assert "N/A" not in execution_html


def test_execution_plan_can_use_pullback_path_and_blocks_only_real_risk() -> None:
    market_context = MarketContext(
        benchmark_returns={
            "spy_20d": 2.0,
            "qqq_20d": 3.0,
            "spy_60d": 5.0,
            "qqq_60d": 6.0,
            "spy_120d": 8.0,
            "qqq_120d": 9.0,
        }
    )
    settings = AppSettings(
        portfolio=PortfolioSettings(risk_budget_by_currency={"USD": 1_000.0})
    )

    item = _item()
    metrics = item.valuation.metrics
    metrics.update({
        "sma_20": metrics["last_close"] - 1.0,
        "sma_60": metrics["last_close"] - 5.0,
        "sma_120": metrics["last_close"] - 9.0,
        "rsi_14": 55.0,
        "volume_vs_20d": 0.8,
        "atr_contraction_ratio": 1.0,
        "bb_width_20_percentile": 55.0,
        "volume_5d_vs_20d": 1.0,
        "prior_20d_low": metrics["last_close"] - 3.0,
        "atr_20": 2.0,
    })
    for key in (
        "breakout_days_ago",
        "breakout_pivot",
        "breakout_hold_pct",
        "breakout_volume_vs_20d",
    ):
        metrics.pop(key, None)

    ready = right_side_execution_plan(
        _report([item], market_context=market_context, settings=settings),
        item,
    )

    assert ready is not None
    assert ready["status"] == "ready"
    assert ready["status_label"] == "Review pullback pilot"
    assert ready["setup_key"] == "pullback"
    assert ready["entry_trigger"] == pytest.approx(metrics["last_close"])
    assert ready["risk_pct"] < 8.0

    wide_item = _item("AMD")
    wide_metrics = wide_item.valuation.metrics
    wide_metrics.update({
        "sma_20": wide_metrics["last_close"] - 1.0,
        "sma_60": wide_metrics["last_close"] - 5.0,
        "sma_120": wide_metrics["last_close"] - 9.0,
        "rsi_14": 55.0,
        "volume_vs_20d": 0.8,
        "atr_contraction_ratio": 1.0,
        "bb_width_20_percentile": 55.0,
        "volume_5d_vs_20d": 1.0,
        "prior_20d_low": wide_metrics["last_close"] - 25.0,
        "atr_20": 10.0,
    })
    for key in (
        "breakout_days_ago",
        "breakout_pivot",
        "breakout_hold_pct",
        "breakout_volume_vs_20d",
    ):
        wide_metrics.pop(key, None)

    blocked = right_side_execution_plan(
        _report([wide_item], market_context=market_context, settings=settings),
        wide_item,
    )

    assert blocked is not None
    assert blocked["status"] == "blocked"
    assert blocked["status_label"] == "Setup ready, entry paused"
    risk = next(gate for gate in blocked["gates"] if gate["key"] == "risk")
    assert risk["required"] is True
    assert risk["passed"] is False

def test_trade_journal_summary_calculates_net_r_mfe_and_mae() -> None:
    item = _item(closes=[100.0, 102.0, 108.0, 110.0])
    item.valuation.metrics.update({
        "chart_dates_60": ["2026-07-01", "2026-07-02", "2026-07-03", "2026-07-04"],
        "chart_high_60": [102.0, 105.0, 112.0, 111.0],
        "chart_low_60": [96.0, 99.0, 103.0, 108.0],
        "chart_close_60": [100.0, 102.0, 108.0, 110.0],
    })
    trade = TradeJournalEntry(
        trade_id="nvda-closed",
        ticker="NVDA",
        status="closed",
        entry_date=date(2026, 7, 1),
        entry_price=100.0,
        shares=10.0,
        initial_stop=95.0,
        exit_date=date(2026, 7, 4),
        exit_price=110.0,
        fees=10.0,
    )
    summary = trade_journal_summary(_report([item], trade_journal=[trade]))
    row = summary["rows"][0]

    assert row["net_pl"] == 90.0
    assert row["planned_risk"] == 50.0
    assert row["r_multiple"] == 1.8
    assert row["mfe_r"] == 2.4
    assert row["mae_r"] == -0.8
    assert summary["win_rate"] == 100.0
    assert summary["reliable"] is False


def test_trade_journal_supports_partial_fills_moving_stop_fees_and_fx() -> None:
    item = _item(closes=[100.0, 103.0, 108.0, 110.0])
    item.valuation.metrics.update({
        "chart_dates_60": ["2026-07-01", "2026-07-02", "2026-07-03", "2026-07-04"],
        "chart_high_60": [102.0, 105.0, 112.0, 111.0],
        "chart_low_60": [96.0, 99.0, 103.0, 108.0],
        "chart_close_60": [100.0, 103.0, 108.0, 110.0],
    })
    trade = TradeJournalEntry(
        trade_id="nvda-partial",
        ticker="NVDA",
        status="open",
        entry_date=date(2026, 7, 1),
        entry_price=102.5,
        shares=10.0,
        initial_stop=95.0,
        current_stop=104.0,
        initial_risk=75.0,
        fees=2.0,
        fx_rate_to_base=31.5,
        fills=[
            TradeFill("buy-1", "buy", date(2026, 7, 1), 100.0, 5.0, 1.0),
            TradeFill("buy-2", "buy", date(2026, 7, 2), 105.0, 5.0, 1.0),
            TradeFill("sell-1", "sell", date(2026, 7, 4), 110.0, 4.0, 1.0),
        ],
    )

    summary = trade_journal_summary(_report([item], trade_journal=[trade]))
    row = summary["rows"][0]

    assert row["average_entry"] == 102.5
    assert row["sold_shares"] == 4.0
    assert row["remaining_shares"] == 6.0
    assert row["fill_count"] == 3
    assert row["planned_risk"] == 75.0
    assert row["current_risk"] == 36.0
    assert row["net_pl"] == 70.0
    assert row["net_pl_base"] == 2205.0
    assert row["r_multiple"] == 0.93
    assert summary["open_count"] == 1


def test_portfolio_risk_keeps_markets_separate_and_finds_correlation() -> None:
    closes = [100.0 + index for index in range(60)]
    first = _item(
        "NVDA",
        closes=closes,
        position=PositionConfig(status="holding", shares=10, stop_loss=150, portfolio_weight=8),
    )
    second = _item(
        "AMD",
        closes=[value * 2 for value in closes],
        position=PositionConfig(status="holding", shares=5, stop_loss=300, portfolio_weight=6),
    )
    taiwan = _item(
        "2330.TW",
        market="twse",
        currency="TWD",
        closes=closes,
        position=PositionConfig(status="holding", shares=100, stop_loss=150, portfolio_weight=5),
    )

    risk = portfolio_risk_overview(_report([first, second, taiwan]))

    assert {(row["market"], row["currency"]) for row in risk["currencies"]} == {
        ("us", "USD"),
        ("taiwan", "TWD"),
    }
    assert risk["correlated_pairs"][0]["left"] == "NVDA"
    assert risk["correlated_pairs"][0]["right"] == "AMD"
    assert risk["correlated_pairs"][0]["correlation"] == 1.0
    assert all("2330.TW" not in (row["left"], row["right"]) for row in risk["correlated_pairs"])


def test_portfolio_risk_reserves_planned_orders_before_entry() -> None:
    item = _item()
    trade = TradeJournalEntry(
        trade_id="nvda-plan",
        ticker="NVDA",
        status="planned",
        entry_date=date(2026, 7, 17),
        entry_price=100.0,
        shares=10.0,
        initial_stop=95.0,
        initial_risk=50.0,
    )
    report = _report(
        [item],
        trade_journal=[trade],
        settings=AppSettings(
            portfolio=PortfolioSettings(
                base_currency="USD",
                risk_budget_by_currency={"USD": 100.0},
            )
        ),
    )

    risk = portfolio_risk_overview(report)
    row = risk["currencies"][0]

    assert row["pending_risk"] == 50.0
    assert row["open_risk"] == 0.0
    assert row["remaining_budget"] == 50.0
    assert row["budget_usage_pct"] == 50.0
    assert risk["consolidated"]["pending_risk"] == 50.0
    assert risk["planned_count"] == 1


def test_portfolio_risk_builds_market_specific_summaries() -> None:
    us = _item(
        "NVDA",
        position=PositionConfig(status="holding", shares=10, stop_loss=100),
    )
    taiwan = _item(
        "2330.TW",
        market="twse",
        currency="TWD",
        position=PositionConfig(status="holding", shares=100, stop_loss=100),
    )
    report = _report(
        [us, taiwan],
        market_context=MarketContext(fx_rates={"USD/TWD": 32.0}),
        settings=AppSettings(
            portfolio=PortfolioSettings(base_currency="TWD"),
        ),
    )

    risk = portfolio_risk_overview(report)

    assert set(risk["market_summaries"]) == {"us", "taiwan"}
    assert risk["market_summaries"]["us"]["open_risk"] == 1152.0
    assert risk["market_summaries"]["taiwan"]["open_risk"] == 360.0
    assert risk["market_summaries"]["us"]["risk_pct"] == 3.47
    assert risk["market_summaries"]["taiwan"]["missing_stops"] == 0
    assert risk["market_summaries"]["taiwan"]["planned_count"] == 0

def test_signal_validation_splits_markets_and_enforces_sample_floor() -> None:
    generated = datetime(2026, 7, 1, tzinfo=timezone.utc)

    def points(symbol: str) -> list[TickerHistoryPoint]:
        rows = []
        for index in range(10):
            rows.append(TickerHistoryPoint(
                report_date=date(2026, 7, 1) + timedelta(days=index),
                generated_at=generated + timedelta(days=index),
                ticker=symbol,
                last_close=100.0 + index,
                right_side_status="Right-side ready" if index in {0, 2} else "",
                signal_entry=100.0 + index,
                signal_stop=95.0 + index,
                signal_risk_pct=5.0,
            ))
        return rows

    items = [_item("NVDA"), _item("2330.TW", market="twse", currency="TWD")]
    session_dates = [
        value.date().isoformat()
        for value in pd.bdate_range("2026-07-01", periods=15)
    ]
    session_closes = [100.0 + index for index in range(15)]
    for item in items:
        item.valuation.metrics["chart_dates_60"] = session_dates
        item.valuation.metrics["chart_close_60"] = session_closes

    report = _report(
        items,
        ticker_history={"NVDA": points("NVDA"), "2330.TW": points("2330.TW")},
    )
    validation = right_side_signal_validation(report, horizons=(5,), minimum_sample=2)

    assert validation["signals_recorded"] == 4
    assert [market["key"] for market in validation["markets"]] == ["us", "taiwan"]
    assert all(market["horizons"][0]["sample_size"] == 2 for market in validation["markets"])
    assert all(market["horizons"][0]["reliable"] for market in validation["markets"])
    assert all(market["horizons"][0]["r_sample_size"] == 2 for market in validation["markets"])


def test_signal_validation_keeps_zero_sample_market_rows_visible() -> None:
    report = _report([
        _item("NVDA"),
        _item("2330.TW", market="twse", currency="TWD"),
        _item("BTC-USD", market="crypto", currency="USD"),
    ])

    validation = right_side_signal_validation(report, horizons=(5,))

    assert [market["key"] for market in validation["markets"]] == ["us", "taiwan", "crypto"]
    assert all(market["horizons"][0]["sample_size"] == 0 for market in validation["markets"])
    assert all(market["horizons"][0]["reliable"] is False for market in validation["markets"])


def test_price_chart_svg_and_html_workflow_are_rendered() -> None:
    item = _item()
    trade = TradeJournalEntry(
        trade_id="nvda-html",
        ticker="NVDA",
        entry_date=date(2026, 7, 1),
        entry_price=100.0,
        shares=10.0,
        initial_stop=95.0,
        current_stop=97.0,
        initial_risk=50.0,
        fills=[TradeFill("nvda-html-buy", "buy", date(2026, 7, 1), 100.0, 10.0)],
    )
    report = _report([item], trade_journal=[trade])

    chart = price_structure_chart(item)
    html = render_html_report(report)

    assert 'class="price-structure-svg"' in chart
    assert 'class="price-line-close"' in chart
    assert 'id="trade-journal"' in html
    assert 'class="execution-plan' in html
    assert 'class="price-structure-svg"' in html
    assert 'stock-daily-trade-journal' in html
    assert 'version: 2' in html
    assert '"fill_id": "nvda-html-buy"' in html
    assert '"current_stop": 97.0' in html
