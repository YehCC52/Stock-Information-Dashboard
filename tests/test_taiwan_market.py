from datetime import date

from stock_daily_research.models import TickerConfig
from stock_daily_research.taiwan_market import (
    TPEX_DIVIDEND_URL,
    TPEX_INSTITUTIONAL_URL,
    TPEX_MONTHLY_REVENUE_URL,
    TWSE_DIVIDEND_URL,
    TWSE_INSTITUTIONAL_URL,
    TWSE_MONTHLY_REVENUE_URL,
    TaiwanMarketDataProvider,
)


def _u(*points: str) -> str:
    return "".join(chr(int(point, 16)) for point in points)


def test_provider_normalizes_official_taiwan_disclosures(monkeypatch) -> None:
    provider = TaiwanMarketDataProvider()
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
    assert snapshot.institutional_net_buy_days_5d == 5
    assert snapshot.institutional_flow_days == 5
    assert result.warnings == []


def test_provider_skips_non_taiwan_tickers_without_network(monkeypatch) -> None:
    provider = TaiwanMarketDataProvider()
    monkeypatch.setattr(provider, "_get_json", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("unexpected fetch")))

    result = provider.fetch(
        [TickerConfig(symbol="BTC-USD", company_name="Bitcoin", market="crypto", currency="USD")],
        date(2026, 7, 14),
    )

    assert result.snapshots == {}
    assert result.warnings == []

def test_provider_normalizes_tpex_disclosures(monkeypatch) -> None:
    provider = TaiwanMarketDataProvider()
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
    assert snapshot.institutional_as_of == date(2026, 7, 14)
    assert snapshot.source == "TPEx OpenAPI"

def test_provider_hides_stale_dividend_disclosures(monkeypatch) -> None:
    provider = TaiwanMarketDataProvider()
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