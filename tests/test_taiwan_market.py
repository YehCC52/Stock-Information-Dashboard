from datetime import date, datetime, timezone

from stock_daily_research.models import TickerConfig
from stock_daily_research.taiwan_market import (
    TPEX_DIVIDEND_URL,
    TPEX_INSTITUTIONAL_SUMMARY_URL,
    TPEX_INSTITUTIONAL_URL,
    TPEX_MONTHLY_REVENUE_URL,
    TWSE_DAILY_CLOSE_URL,
    TWSE_DIVIDEND_URL,
    TWSE_INSTITUTIONAL_URL,
    TWSE_INSTITUTIONAL_SUMMARY_URL,
    TWSE_MARGIN_URL,
    TWSE_MONTHLY_REVENUE_URL,
    TaiwanMarketDataProvider,
    _margin_maintenance_snapshot,
    _tpex_institutional_market_snapshot,
    _twse_institutional_market_snapshot,
)


def _u(*points: str) -> str:
    return "".join(chr(int(point, 16)) for point in points)


def test_provider_normalizes_official_taiwan_disclosures(monkeypatch) -> None:
    provider = TaiwanMarketDataProvider(include_market_overview=False)
    code = _u("516c", "53f8", "4ee3", "865f")
    revenue_month = _u("8cc7", "6599", "5e74", "6708")
    revenue = _u("7576", "6708", "71df", "6536")
    mom = _u("4e0a", "6708", "6bd4", "8f03", "589e", "6e1b", "0028", "0025", "0029")
    yoy = _u("53bb", "5e74", "540c", "6708", "589e", "6e1b", "0028", "0025", "0029")
    dividend_year = _u("80a1", "5229", "6240", "5c6c", "5e74", "5ea6")
    cash_dividend = _u("80a1", "6771", "914d", "767c", "002d", "76c8", "9918", "5206", "914d", "4e4b", "73fe", "91d1", "80a1", "5229", "0028", "5143", "002f", "80a1", "0029")
    ticker_code = _u("8b49", "5238", "4ee3", "865f")
    foreign = _u("5916", "9678", "8cc7", "8cb7", "8ce3", "8d85", "80a1", "6578", "0028", "4e0d", "542b", "5916", "8cc7", "81ea", "71df", "5546", "0029")
    trust = _u("6295", "4fe1", "8cb7", "8ce3", "8d85", "80a1", "6578")
    dealer = _u("81ea", "71df", "5546", "8cb7", "8ce3", "8d85", "80a1", "6578")

    def fake_get_json(url: str, params=None):
        if url == TWSE_MONTHLY_REVENUE_URL:
            return [{code: "2330", revenue_month: "202606", revenue: "100,000", mom: "2.5", yoy: "18.7"}]
        if url == TWSE_DIVIDEND_URL:
            return [{code: "2330", dividend_year: "2025", cash_dividend: "5.0"}]
        assert url == TWSE_INSTITUTIONAL_URL
        return {"fields": [ticker_code, foreign, trust, dealer], "data": [["2330", "12,345", "-234", "50"]]}

    monkeypatch.setattr(provider, "_get_json", fake_get_json)
    result = provider.fetch(
        [TickerConfig(symbol="2330.TW", company_name="TSMC", market="twse", currency="TWD")],
        date(2026, 7, 14),
    )

    snapshot = result.snapshots["2330.TW"]
    assert snapshot.revenue_month == "202606"
    assert snapshot.monthly_revenue == 100000.0
    assert snapshot.monthly_revenue_mom_pct == 2.5
    assert snapshot.monthly_revenue_yoy_pct == 18.7
    assert snapshot.cash_dividend_per_share == 5.0
    assert snapshot.dividend_year == "2025"
    assert snapshot.foreign_net_shares == 12345.0
    assert snapshot.investment_trust_net_shares == -234.0
    assert snapshot.dealer_net_shares == 50.0
    assert snapshot.institutional_as_of == date(2026, 7, 14)
    assert snapshot.foreign_net_shares_5d == 61725.0
    assert snapshot.investment_trust_net_shares_5d == -1170.0
    assert snapshot.institutional_net_shares == 12161.0
    assert snapshot.institutional_net_shares_5d == 60805.0
    assert snapshot.institutional_net_buy_days_5d == 5
    assert snapshot.institutional_flow_days == 5
    assert result.warnings == []


def test_provider_skips_non_taiwan_tickers_without_network(monkeypatch) -> None:
    provider = TaiwanMarketDataProvider(include_market_overview=False)
    monkeypatch.setattr(provider, "_get_json", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("unexpected fetch")))

    result = provider.fetch(
        [TickerConfig(symbol="BTC-USD", company_name="Bitcoin", market="crypto", currency="USD")],
        date(2026, 7, 14),
    )

    assert result.snapshots == {}
    assert result.warnings == []

def test_provider_normalizes_tpex_disclosures(monkeypatch) -> None:
    provider = TaiwanMarketDataProvider(include_market_overview=False)
    code = _u("516c", "53f8", "4ee3", "865f")
    revenue_month = _u("8cc7", "6599", "5e74", "6708")
    revenue = _u("71df", "696d", "6536", "5165", "002d", "7576", "6708", "71df", "6536")
    yoy = _u("71df", "696d", "6536", "5165", "002d", "53bb", "5e74", "540c", "6708", "589e", "6e1b", "0028", "0025", "0029")
    dividend_year = _u("80a1", "5229", "5e74", "5ea6")
    cash_dividend = _u("80a1", "6771", "914d", "767c", "5167", "5bb9", "002d", "76c8", "9918", "5206", "914d", "4e4b", "73fe", "91d1", "80a1", "5229", "0028", "5143", "002f", "80a1", "0029")

    def fake_get_json(url: str, params=None):
        if url == TPEX_MONTHLY_REVENUE_URL:
            return [{code: "5425", revenue_month: "11506", revenue: "2,000,000", yoy: "12.5"}]
        if url == TPEX_DIVIDEND_URL:
            return [{code: "5425", dividend_year: "114", cash_dividend: "3.2"}]
        assert url == TPEX_INSTITUTIONAL_URL
        return [{
            "Date": "1150714", "SecuritiesCompanyCode": "5425",
            "Foreign Investors include Mainland Area Investors (Foreign Dealers excluded)-Difference": "12,000",
            "SecuritiesInvestmentTrustCompanies-Difference": "-400",
            "Dealers-Difference": "80",
        }]

    monkeypatch.setattr(provider, "_get_json", fake_get_json)
    result = provider.fetch(
        [TickerConfig(symbol="5425.TWO", company_name="Example", market="tpex", currency="TWD")],
        date(2026, 7, 14),
    )

    snapshot = result.snapshots["5425.TWO"]
    assert snapshot.monthly_revenue == 2_000_000.0
    assert snapshot.monthly_revenue_yoy_pct == 12.5
    assert snapshot.cash_dividend_per_share == 3.2
    assert snapshot.foreign_net_shares == 12_000.0
    assert snapshot.investment_trust_net_shares == -400.0
    assert snapshot.dealer_net_shares == 80.0
    assert snapshot.institutional_net_shares == 11_680.0
    assert snapshot.institutional_as_of == date(2026, 7, 14)
    assert snapshot.source == "TPEx OpenAPI"

def test_provider_hides_stale_dividend_disclosures(monkeypatch) -> None:
    provider = TaiwanMarketDataProvider(include_market_overview=False)
    code = _u("516c", "53f8", "4ee3", "865f")
    dividend_year = _u("80a1", "5229", "5e74", "5ea6")
    cash_dividend = _u("80a1", "6771", "914d", "767c", "5167", "5bb9", "002d", "76c8", "9918", "5206", "914d", "4e4b", "73fe", "91d1", "80a1", "5229", "0028", "5143", "002f", "80a1", "0029")

    def fake_get_json(url: str, params=None):
        if url == TPEX_MONTHLY_REVENUE_URL:
            return []
        if url == TPEX_DIVIDEND_URL:
            return [{code: "5425", dividend_year: "109", cash_dividend: "3.2"}]
        assert url == TPEX_INSTITUTIONAL_URL
        return []

    monkeypatch.setattr(provider, "_get_json", fake_get_json)
    result = provider.fetch(
        [TickerConfig(symbol="5425.TWO", company_name="Example", market="tpex", currency="TWD")],
        date(2026, 7, 14),
    )

    assert result.snapshots == {}


def test_twse_institutional_market_summary_uses_named_fields() -> None:
    retrieved_at = datetime(2026, 8, 6, tzinfo=timezone.utc)
    payload = {
        "stat": "OK",
        "date": "20260805",
        "fields": [
            "\u55ae\u4f4d\u540d\u7a31",
            "\u8cb7\u9032\u91d1\u984d",
            "\u8ce3\u51fa\u91d1\u984d",
            "\u8cb7\u8ce3\u5dee\u984d",
        ],
        "data": [
            ["\u81ea\u71df\u5546(\u81ea\u884c\u8cb7\u8ce3)", "0", "0", "-200"],
            ["\u81ea\u71df\u5546(\u907f\u96aa)", "0", "0", "500"],
            ["\u6295\u4fe1", "0", "0", "1,200"],
            ["\u5916\u8cc7\u53ca\u9678\u8cc7(\u4e0d\u542b\u5916\u8cc7\u81ea\u71df\u5546)", "0", "0", "3,000"],
            ["\u5408\u8a08", "0", "0", "4,500"],
        ],
    }

    snapshot = _twse_institutional_market_snapshot(payload, retrieved_at)

    assert snapshot is not None
    assert snapshot.as_of_date == date(2026, 8, 5)
    assert snapshot.market == "twse"
    assert snapshot.foreign_net_twd == 3_000.0
    assert snapshot.investment_trust_net_twd == 1_200.0
    assert snapshot.dealer_net_twd == 300.0
    assert snapshot.total_net_twd == 4_500.0


def test_tpex_institutional_market_summary_normalizes_roc_date() -> None:
    retrieved_at = datetime(2026, 8, 6, tzinfo=timezone.utc)
    payload = [
        {
            "Date": "1150805",
            "Investor": "\u3000\u5916\u8cc7\u53ca\u9678\u8cc7(\u4e0d\u542b\u81ea\u71df\u5546)",
            "Net": "-3,000",
        },
        {
            "Date": "1150805",
            "Investor": "\u6295\u4fe1",
            "Net": "1,000",
        },
        {
            "Date": "1150805",
            "Investor": "\u81ea\u71df\u5546\u5408\u8a08",
            "Net": "-500",
        },
        {
            "Date": "1150805",
            "Investor": "\u4e09\u5927\u6cd5\u4eba\u5408\u8a08*",
            "Net": "-2,500",
        },
    ]

    snapshot = _tpex_institutional_market_snapshot(payload, retrieved_at)

    assert snapshot is not None
    assert snapshot.as_of_date == date(2026, 8, 5)
    assert snapshot.market == "tpex"
    assert snapshot.foreign_net_twd == -3_000.0
    assert snapshot.investment_trust_net_twd == 1_000.0
    assert snapshot.dealer_net_twd == -500.0
    assert snapshot.total_net_twd == -2_500.0


def _margin_payload(on: str = "20260728") -> dict[str, object]:
    return {
        "stat": "OK",
        "date": on,
        "tables": [
            {
                "fields": ["\u9805\u76ee", "\u524d\u65e5\u9918\u984d", "\u4eca\u65e5\u9918\u984d"],
                "data": [
                    ["\u878d\u8cc7(\u4ea4\u6613\u55ae\u4f4d)", "32", "31"],
                    ["\u878d\u8cc7\u91d1\u984d(\u4edf\u5143)", "1,100", "1,000"],
                ],
            },
            {
                "fields": ["\u4ee3\u865f", "\u524d\u65e5\u9918\u984d", "\u4eca\u65e5\u9918\u984d"],
                "data": [
                    ["A", "12", "10"],
                    ["B", "18", "20"],
                    ["C", "2", "1"],
                ],
            },
        ],
    }


def _close_payload(on: str = "20260728") -> dict[str, object]:
    return {
        "stat": "OK",
        "date": on,
        "tables": [
            {
                "fields": ["\u8b49\u5238\u4ee3\u865f", "\u6536\u76e4\u50f9"],
                "data": [["A", "100"], ["B", "50"], ["C", "--"]],
            }
        ],
    }


def test_margin_maintenance_snapshot_uses_same_day_market_value() -> None:
    retrieved_at = datetime(2026, 7, 29, 1, tzinfo=timezone.utc)

    overview = _margin_maintenance_snapshot(
        _margin_payload(),
        _close_payload(),
        retrieved_at,
    )

    assert overview is not None
    assert overview.as_of_date == date(2026, 7, 28)
    assert overview.margin_maintenance_ratio_estimate == 200.0
    assert overview.collateral_value_thousand_twd == 2_000.0
    assert overview.financing_balance_thousand_twd == 1_000.0
    assert overview.previous_financing_balance_thousand_twd == 1_100.0
    assert overview.price_coverage_pct == 96.77
    assert overview.priced_security_count == 2
    assert overview.margin_security_count == 3
    assert overview.source == "TWSE MI_MARGN / MI_INDEX"


def test_margin_maintenance_overview_scans_back_to_latest_trading_day(monkeypatch) -> None:
    provider = TaiwanMarketDataProvider()
    calls: list[tuple[str, str]] = []

    def fake_get_json(url: str, params=None):
        assert params is not None
        requested_date = params["date"]
        calls.append((url, requested_date))
        if url == TWSE_MARGIN_URL:
            if requested_date == "20260729":
                return {"stat": "No data"}
            assert requested_date == "20260728"
            return _margin_payload(requested_date)
        assert url == TWSE_DAILY_CLOSE_URL
        return _close_payload(requested_date)

    monkeypatch.setattr(provider, "_get_json", fake_get_json)
    warnings: list[str] = []

    overview = provider._margin_maintenance_overview(
        date(2026, 7, 29),
        datetime(2026, 7, 29, 1, tzinfo=timezone.utc),
        warnings,
    )

    assert overview is not None
    assert overview.as_of_date == date(2026, 7, 28)
    assert warnings == []
    assert calls == [
        (TWSE_MARGIN_URL, "20260729"),
        (TWSE_MARGIN_URL, "20260728"),
        (TWSE_DAILY_CLOSE_URL, "20260728"),
    ]


def test_institutional_market_overview_rejects_future_disclosures(monkeypatch) -> None:
    provider = TaiwanMarketDataProvider()
    retrieved_at = datetime(2026, 8, 6, tzinfo=timezone.utc)
    twse_payload = {
        "stat": "OK",
        "date": "20260807",
        "fields": ["\u55ae\u4f4d\u540d\u7a31", "\u8cb7\u8ce3\u5dee\u984d"],
        "data": [
            ["\u5916\u8cc7\u53ca\u9678\u8cc7(\u4e0d\u542b\u5916\u8cc7\u81ea\u71df\u5546)", "3,000"],
            ["\u6295\u4fe1", "1,200"],
            ["\u81ea\u71df\u5546(\u81ea\u884c\u8cb7\u8ce3)", "300"],
            ["\u5408\u8a08", "4,500"],
        ],
    }
    tpex_payload = [
        {"Date": "1150807", "Investor": "\u5916\u8cc7\u53ca\u9678\u8cc7(\u4e0d\u542b\u81ea\u71df\u5546)", "Net": "-3,000"},
        {"Date": "1150807", "Investor": "\u6295\u4fe1", "Net": "1,000"},
        {"Date": "1150807", "Investor": "\u81ea\u71df\u5546\u5408\u8a08", "Net": "-500"},
        {"Date": "1150807", "Investor": "\u4e09\u5927\u6cd5\u4eba\u5408\u8a08*", "Net": "-2,500"},
    ]

    def fake_get_json(url: str, params=None):
        if url == TWSE_INSTITUTIONAL_SUMMARY_URL:
            return twse_payload
        assert url == TPEX_INSTITUTIONAL_SUMMARY_URL
        return tpex_payload

    monkeypatch.setattr(provider, "_get_json", fake_get_json)
    warnings: list[str] = []

    snapshots = provider._institutional_market_overview(
        date(2026, 8, 6),
        retrieved_at,
        warnings,
    )

    assert snapshots == []
    assert warnings == [
        "Taiwan institutional market totals unavailable for recent trading days."
    ]
