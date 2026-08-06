from datetime import date, datetime, timezone

from stock_daily_research.taifex import (
    TaifexInstitutionalProvider,
    _taifex_api_positions,
    _taifex_html_positions,
)


def _api_row(
    *,
    on: str = "20260805",
    institution: str = "\u5916\u8cc7\u53ca\u9678\u8cc7",
    contract: str = "\u81fa\u80a1\u671f\u8ca8",
    open_net: str = "-87199",
) -> dict[str, str]:
    return {
        "Date": on,
        "ContractCode": contract,
        "Item": institution,
        "TradingVolume(Long)": "65578",
        "TradingValue(Long)(Thousands)": "582083199",
        "TradingVolume(Short)": "66149",
        "TradingValue(Short)(Thousands)": "586998256",
        "TradingVolume(Net)": "-571",
        "TradingValue(Net)(Thousands)": "-4915057",
        "OpenInterest(Long)": "9180",
        "ContractValueofOpenInterest(Long)(Thousands)": "81821890",
        "OpenInterest(Short)": "96379",
        "ContractValueofOpenInterest(Short)(Thousands)": "858631264",
        "OpenInterest(Net)": open_net,
        "ContractValueofOpenInterest(Net)(Thousands)": "-776809374",
    }


def _history_html(on: date, open_net: int = -80_000) -> str:
    long_open = 10_000
    short_open = long_open - open_net
    values = [
        "1,000",
        "10,000",
        "1,100",
        "11,000",
        "-100",
        "-1,000",
        f"{long_open:,}",
        "100,000",
        f"{short_open:,}",
        "900,000",
        f"{open_net:,}",
        "-800,000",
    ]
    cells = "".join(f"<td>{value}</td>" for value in values)
    return (
        "<html><span>\u65e5\u671f"
        f"{on:%Y/%m/%d}</span><table>"
        "<tr><td>1</td><td rowspan='3'>&#x81FA;&#x80A1;&#x671F;&#x8CA8;</td>"
        f"<td>&#x81EA;&#x71DF;&#x5546;</td>{cells}</tr>"
        f"<tr><td>&#x6295;&#x4FE1;</td>{cells}</tr>"
        f"<tr><td>&#x5916;&#x8CC7;&#x53CA;&#x9678;&#x8CC7;</td>{cells}</tr>"
        "</table></html>"
    )


def test_taifex_api_normalizes_tx_positions() -> None:
    retrieved_at = datetime(2026, 8, 6, tzinfo=timezone.utc)
    payload = [
        _api_row(),
        _api_row(
            institution="\u6295\u4fe1",
            open_net="84575",
        ),
        _api_row(
            contract="\u96fb\u5b50\u671f\u8ca8",
            open_net="-223",
        ),
    ]

    positions = _taifex_api_positions(payload, retrieved_at)

    assert len(positions) == 2
    foreign = next(item for item in positions if item.institution == "foreign")
    assert foreign.as_of_date == date(2026, 8, 5)
    assert foreign.trading_net == -571
    assert foreign.open_interest_long == 9_180
    assert foreign.open_interest_short == 96_379
    assert foreign.open_interest_net == -87_199
    assert foreign.source == "TAIFEX OpenAPI"


def test_taifex_history_html_extracts_named_contract_rows() -> None:
    retrieved_at = datetime(2026, 8, 6, tzinfo=timezone.utc)
    expected_date = date(2026, 8, 4)

    positions = _taifex_html_positions(
        _history_html(expected_date),
        expected_date=expected_date,
        retrieved_at=retrieved_at,
    )

    assert {item.institution for item in positions} == {
        "dealer",
        "investment_trust",
        "foreign",
    }
    foreign = next(item for item in positions if item.institution == "foreign")
    assert foreign.open_interest_long == 10_000
    assert foreign.open_interest_short == 90_000
    assert foreign.open_interest_net == -80_000
    assert foreign.source == "TAIFEX futContractsDate"


def test_taifex_provider_bootstraps_five_sessions(monkeypatch) -> None:
    provider = TaifexInstitutionalProvider()
    report_date = date(2026, 8, 5)
    monkeypatch.setattr(
        provider,
        "_get_json",
        lambda _url: [
            _api_row(),
            _api_row(
                institution="\u6295\u4fe1",
                open_net="84575",
            ),
        ],
    )

    def fake_get_text(_url: str, *, params: dict[str, str]) -> str:
        requested = datetime.strptime(params["queryDate"], "%Y/%m/%d").date()
        days_back = (report_date - requested).days
        return _history_html(requested, open_net=-87_199 + days_back * 1_000)

    monkeypatch.setattr(provider, "_get_text", fake_get_text)

    result = provider.fetch(report_date, history_sessions=5)

    foreign = [
        item for item in result.positions
        if item.institution == "foreign"
    ]
    assert len({item.as_of_date for item in foreign}) == 5
    assert max(item.as_of_date for item in foreign) == date(2026, 8, 5)
    assert result.warnings == []


def test_taifex_history_rejects_wrong_disclosure_date() -> None:
    positions = _taifex_html_positions(
        _history_html(date(2026, 8, 4)),
        expected_date=date(2026, 8, 5),
        retrieved_at=datetime(2026, 8, 6, tzinfo=timezone.utc),
    )

    assert positions == []
