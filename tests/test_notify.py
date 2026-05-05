from datetime import date, datetime, timezone

import pytest

from stock_daily_research.models import DailyReport, EarningsDate, EconomicEvent, MarketSentiment, NewsArticle, TickerConfig, TickerReport, ValuationSnapshot
from stock_daily_research.notify import TelegramNotifier, build_daily_summary, truncate_for_telegram


def test_build_daily_summary_is_compact_digest() -> None:
    report = DailyReport(
        report_date=date(2026, 4, 28),
        generated_at=datetime(2026, 4, 28, 7, 0, tzinfo=timezone.utc),
        ticker_reports=[
            TickerReport(
                ticker=TickerConfig(symbol="NVDA", company_name="NVIDIA Corporation"),
                articles=[
                    NewsArticle(
                        ticker="NVDA",
                        title="Nvidia revenue beats estimates",
                        source="Reuters",
                        domain="reuters.com",
                        published_at=datetime(2026, 4, 28, 1, 0, tzinfo=timezone.utc),
                        url="https://reuters.com/nvda",
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
                        "forward_pe": 19.27,
                        "ev_to_ebitda": 39.12,
                        "rsi_14": 72.0,
                    },
                    retrieved_at=datetime(2026, 4, 28, 7, 0, tzinfo=timezone.utc),
                ),
                earnings=EarningsDate(
                    ticker="NVDA",
                    company_name="NVIDIA Corporation",
                    earnings_date=date(2026, 5, 1),
                    time_of_day="unknown",
                    fiscal_quarter=None,
                    fiscal_year=None,
                    eps_estimate=None,
                    revenue_estimate=None,
                    source="yfinance",
                    source_retrieved_at=datetime(2026, 4, 28, 7, 0, tzinfo=timezone.utc),
                ),
            )
        ],
        economic_events=[
            EconomicEvent(
                name="FOMC Rate Decision",
                category="rates",
                event_datetime=datetime(2026, 4, 30, 2, 0, tzinfo=timezone.utc),
                source="Federal Reserve",
                source_url="https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm",
                notes="Official statement: The Committee decided to maintain the target range.",
            )
        ],
        market_sentiment=MarketSentiment(
            score=68,
            label="Greed",
            source="yfinance proxy",
            retrieved_at=datetime(2026, 4, 28, 7, 0, tzinfo=timezone.utc),
        ),
    )

    summary = build_daily_summary(report, "reports/2026-04-28.html")

    assert "Daily Stock Brief - 2026-04-28" in summary
    assert "Market sentiment" in summary
    assert "68/100 Greed" in summary
    assert "Macro" in summary
    assert "FOMC Rate Decision" in summary
    assert "maintain the target range" in summary
    assert "US overnight" in summary
    assert "Earnings <=7d" in summary
    assert "NVDA: 2026-05-01 (in 3d)" in summary
    assert "Top news" in summary
    assert "Nvidia revenue beats estimates" in summary
    assert "Market Cap" not in summary
    assert "RSI 14 overbought 72.00" in summary
    assert "Report: reports/2026-04-28.html" in summary


def test_build_daily_summary_has_quiet_message() -> None:
    report = DailyReport(
        report_date=date(2026, 4, 28),
        generated_at=datetime(2026, 4, 28, 7, 0, tzinfo=timezone.utc),
        ticker_reports=[
            TickerReport(
                ticker=TickerConfig(symbol="MSFT", company_name="Microsoft Corporation"),
                articles=[],
                x_signals=[],
                valuation=None,
                earnings=None,
            )
        ],
    )

    summary = build_daily_summary(report, "reports/2026-04-28.html")

    assert "No urgent market-moving items found" in summary
    assert "MSFT - Microsoft Corporation" not in summary


def test_build_daily_summary_condenses_warnings_and_flags_valuation() -> None:
    report = DailyReport(
        report_date=date(2026, 4, 28),
        generated_at=datetime(2026, 4, 28, 7, 0, tzinfo=timezone.utc),
        ticker_reports=[
            TickerReport(
                ticker=TickerConfig(symbol="TSLA", company_name="Tesla, Inc."),
                articles=[],
                x_signals=[],
                valuation=ValuationSnapshot(
                    ticker="TSLA",
                    as_of_date=date(2026, 4, 27),
                    source="yfinance",
                    metrics={"forward_pe": 125.4},
                    retrieved_at=datetime(2026, 4, 28, 7, 0, tzinfo=timezone.utc),
                ),
                earnings=None,
                warnings=[
                    "Valuation fallback used: latest available 2026-04-27 from yfinance.",
                    "News fetch failed for reuters.com: timeout",
                ],
            )
        ],
        warnings=["Macro calendar fetch failed for CPI: unavailable"],
    )

    summary = build_daily_summary(report, "reports/2026-04-28.html")

    assert "Valuation / data flags" in summary
    assert "TSLA: using last valuation snapshot (2026-04-27)" in summary
    assert "TSLA: Forward P/E 125.40" in summary
    assert "Data quality" in summary
    assert "2 ticker warnings across 1 tickers" in summary
    assert "1 global warnings" in summary
    assert "News fetch failed for reuters.com" not in summary


def test_truncate_for_telegram_limits_message_size() -> None:
    text = "x" * 5000

    result = truncate_for_telegram(text)

    assert len(result) == 4096
    assert result.endswith("[truncated]")


def test_telegram_notifier_retries_then_succeeds(monkeypatch) -> None:
    import requests

    calls = {"n": 0}

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"ok": True}

    def fake_post(url, json, timeout):
        calls["n"] += 1
        if calls["n"] < 2:
            raise requests.ConnectionError("flap")
        return FakeResponse()

    monkeypatch.setattr("stock_daily_research.notify.requests.post", fake_post)
    monkeypatch.setattr("stock_daily_research.notify.time.sleep", lambda _: None)

    TelegramNotifier(bot_token="t", chat_id="c").send_message("hi")

    assert calls["n"] == 2


def test_telegram_notifier_raises_after_max_retries(monkeypatch) -> None:
    import requests

    def fake_post(url, json, timeout):
        raise requests.ConnectionError("nope")

    monkeypatch.setattr("stock_daily_research.notify.requests.post", fake_post)
    monkeypatch.setattr("stock_daily_research.notify.time.sleep", lambda _: None)

    with pytest.raises(requests.ConnectionError):
        TelegramNotifier(bot_token="t", chat_id="c").send_message("hi")
