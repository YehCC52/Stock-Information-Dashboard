from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

import requests

from .models import TaiwanMarketSnapshot, TickerConfig


TWSE_MONTHLY_REVENUE_URL = "https://openapi.twse.com.tw/v1/opendata/t187ap05_L"
TWSE_DIVIDEND_URL = "https://openapi.twse.com.tw/v1/opendata/t187ap45_L"
TWSE_INSTITUTIONAL_URL = "https://www.twse.com.tw/rwd/zh/fund/T86"
TPEX_MONTHLY_REVENUE_URL = "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap05_O"
TPEX_DIVIDEND_URL = "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap39_O"
TPEX_INSTITUTIONAL_URL = "https://www.tpex.org.tw/openapi/v1/tpex_3insti_daily_trading"
_REQUEST_TIMEOUT_SECONDS = 12


@dataclass(frozen=True)
class TaiwanMarketFetchResult:
    snapshots: dict[str, TaiwanMarketSnapshot]
    warnings: list[str]


class TaiwanMarketDataProvider:
    """Official TWSE and TPEx disclosures for Taiwan watchlist securities."""

    def __init__(self, timeout_seconds: int = _REQUEST_TIMEOUT_SECONDS) -> None:
        self.timeout_seconds = timeout_seconds

    def fetch(self, tickers: list[TickerConfig], report_date: date) -> TaiwanMarketFetchResult:
        twse_tickers = [ticker for ticker in tickers if ticker.market == "twse"]
        tpex_tickers = [ticker for ticker in tickers if ticker.market == "tpex"]
        taiwan_tickers = [*twse_tickers, *tpex_tickers]
        if not taiwan_tickers:
            return TaiwanMarketFetchResult(snapshots={}, warnings=[])

        warnings: list[str] = []
        revenue_by_symbol: dict[str, dict[str, object]] = {}
        dividend_by_symbol: dict[str, dict[str, object]] = {}
        flow_by_symbol: dict[str, dict[str, object]] = {}
        if twse_tickers:
            revenue_by_symbol.update(self._monthly_revenue(TWSE_MONTHLY_REVENUE_URL, "TWSE", warnings))
            dividend_by_symbol.update(self._cash_dividends(TWSE_DIVIDEND_URL, "TWSE", warnings))
            flow_by_symbol.update(self._institutional_flow(report_date, warnings))
        if tpex_tickers:
            revenue_by_symbol.update(self._monthly_revenue(TPEX_MONTHLY_REVENUE_URL, "TPEx", warnings))
            dividend_by_symbol.update(self._cash_dividends(TPEX_DIVIDEND_URL, "TPEx", warnings))
            flow_by_symbol.update(self._tpex_institutional_flow(warnings))

        retrieved_at = datetime.now(timezone.utc)
        snapshots: dict[str, TaiwanMarketSnapshot] = {}
        for ticker in taiwan_tickers:
            code = ticker.display_symbol
            revenue = revenue_by_symbol.get(code, {})
            dividend = dividend_by_symbol.get(code, {})
            if not _has_recent_dividend(dividend, report_date):
                dividend = {}
            flow = flow_by_symbol.get(code, {})
            visible_values = (
                revenue.get("amount"), revenue.get("mom_pct"), revenue.get("yoy_pct"),
                dividend.get("cash_per_share"),
                flow.get("foreign"), flow.get("trust"), flow.get("dealer"),
            )
            if all(value is None for value in visible_values):
                continue
            snapshots[ticker.symbol] = TaiwanMarketSnapshot(
                ticker=ticker.symbol,
                revenue_month=str(revenue.get("month", "")),
                monthly_revenue=revenue.get("amount"),
                monthly_revenue_mom_pct=revenue.get("mom_pct"),
                monthly_revenue_yoy_pct=revenue.get("yoy_pct"),
                cash_dividend_per_share=dividend.get("cash_per_share"),
                dividend_year=str(dividend.get("year", "")),
                foreign_net_shares=flow.get("foreign"),
                investment_trust_net_shares=flow.get("trust"),
                dealer_net_shares=flow.get("dealer"),
                foreign_net_shares_5d=flow.get("foreign_5d"),
                investment_trust_net_shares_5d=flow.get("trust_5d"),
                institutional_net_buy_days_5d=flow.get("net_buy_days"),
                institutional_flow_days=int(flow.get("flow_days", 0) or 0),
                institutional_as_of=flow.get("as_of"),
                source="TWSE OpenAPI / T86" if ticker.market == "twse" else "TPEx OpenAPI",
                retrieved_at=retrieved_at,
            )
        return TaiwanMarketFetchResult(snapshots=snapshots, warnings=warnings)
    def _monthly_revenue(self, url: str, source: str, warnings: list[str]) -> dict[str, dict[str, object]]:
        try:
            payload = self._get_json(url)
        except requests.RequestException as exc:
            warnings.append(f"{source} monthly revenue unavailable: {exc}")
            return {}
        if not isinstance(payload, list):
            warnings.append(f"{source} monthly revenue unavailable: unexpected payload.")
            return {}

        result: dict[str, dict[str, object]] = {}
        for row in payload:
            if not isinstance(row, dict):
                continue
            code = _text(row, _u("516c", "53f8", "4ee3", "865f"), _u("8b49", "5238", "4ee3", "865f"))
            if not code:
                continue
            result[code] = {
                "month": _text(row, _u("8cc7", "6599", "5e74", "6708"), _u("5e74", "6708")),
                "amount": _number(row, _u("71df", "696d", "6536", "5165", "002d", "7576", "6708", "71df", "6536"), _u("7576", "6708", "71df", "6536")),
                "mom_pct": _number(row, _u("71df", "696d", "6536", "5165", "002d", "4e0a", "6708", "6bd4", "8f03", "589e", "6e1b", "0028", "0025", "0029"), _u("4e0a", "6708", "6bd4", "8f03", "589e", "6e1b", "0028", "0025", "0029"), _u("524d", "671f", "6bd4", "8f03", "589e", "6e1b", "0028", "0025", "0029")),
                "yoy_pct": _number(row, _u("71df", "696d", "6536", "5165", "002d", "53bb", "5e74", "540c", "6708", "589e", "6e1b", "0028", "0025", "0029"), _u("53bb", "5e74", "540c", "6708", "589e", "6e1b", "0028", "0025", "0029"), _u("53bb", "5e74", "540c", "671f", "589e", "6e1b", "0028", "0025", "0029")),
            }
        return result

    def _cash_dividends(self, url: str, source: str, warnings: list[str]) -> dict[str, dict[str, object]]:
        try:
            payload = self._get_json(url)
        except requests.RequestException as exc:
            warnings.append(f"{source} dividend data unavailable: {exc}")
            return {}
        if not isinstance(payload, list):
            warnings.append(f"{source} dividend data unavailable: unexpected payload.")
            return {}

        result: dict[str, dict[str, object]] = {}
        for row in payload:
            if not isinstance(row, dict):
                continue
            code = _text(row, _u("516c", "53f8", "4ee3", "865f"), _u("8b49", "5238", "4ee3", "865f"))
            if not code:
                continue
            year = _text(row, _u("80a1", "5229", "6240", "5c6c", "5e74", "5ea6"), _u("5e74", "5ea6"), _u("80a1", "5229", "5e74", "5ea6"))
            cash_components = [
                _number(row, _u("80a1", "6771", "914d", "767c", "002d", "76c8", "9918", "5206", "914d", "4e4b", "73fe", "91d1", "80a1", "5229", "0028", "5143", "002f", "80a1", "0029")),
                _number(row, _u("80a1", "6771", "914d", "767c", "002d", "6cd5", "5b9a", "76c8", "9918", "516c", "7a4d", "767c", "653e", "4e4b", "73fe", "91d1", "0028", "5143", "002f", "80a1", "0029")),
                _number(row, _u("80a1", "6771", "914d", "767c", "002d", "8cc7", "672c", "516c", "7a4d", "767c", "653e", "4e4b", "73fe", "91d1", "0028", "5143", "002f", "80a1", "0029")),
                _number(row, _u("80a1", "6771", "914d", "767c", "5167", "5bb9", "002d", "76c8", "9918", "5206", "914d", "4e4b", "73fe", "91d1", "80a1", "5229", "0028", "5143", "002f", "80a1", "0029")),
                _number(row, _u("80a1", "6771", "914d", "767c", "5167", "5bb9", "002d", "6cd5", "5b9a", "76c8", "9918", "516c", "7a4d", "767c", "653e", "4e4b", "73fe", "91d1", "0028", "5143", "002f", "80a1", "0029")),
            ]
            values = [value for value in cash_components if value is not None]
            cash = sum(values) if values else _number(
                row,
                _u("666e", "901a", "80a1", "6bcf", "80a1", "73fe", "91d1", "80a1", "5229", "0028", "5143", "0029"),
                _u("6bcf", "80a1", "73fe", "91d1", "80a1", "5229", "0028", "5143", "0029"),
                _u("73fe", "91d1", "80a1", "5229"),
            )
            if cash is None:
                continue
            previous = result.get(code)
            if previous is None or str(year) >= str(previous.get("year", "")):
                result[code] = {"year": year, "cash_per_share": cash}
        return result
    def _institutional_flow(self, report_date: date, warnings: list[str]) -> dict[str, dict[str, object]]:
        daily_rows: list[dict[str, dict[str, object]]] = []
        for offset in range(21):
            candidate = report_date - timedelta(days=offset)
            if candidate.weekday() >= 5:
                continue
            try:
                payload = self._get_json(
                    TWSE_INSTITUTIONAL_URL,
                    params={"date": candidate.strftime("%Y%m%d"), "selectType": "ALL", "response": "json"},
                )
            except requests.RequestException:
                continue
            rows = _institutional_rows(payload, candidate)
            if not rows:
                continue
            daily_rows.append(rows)
            if len(daily_rows) == 5:
                break
        if not daily_rows:
            warnings.append("Taiwan institutional-flow data unavailable for recent trading days.")
            return {}
        return _summarize_institutional_history(daily_rows)

    def _tpex_institutional_flow(self, warnings: list[str]) -> dict[str, dict[str, object]]:
        try:
            payload = self._get_json(TPEX_INSTITUTIONAL_URL)
        except requests.RequestException as exc:
            warnings.append(f"TPEx institutional-flow data unavailable: {exc}")
            return {}
        rows = _tpex_institutional_rows(payload)
        if not rows:
            warnings.append("TPEx institutional-flow data unavailable: unexpected payload.")
        return rows
    def _get_json(self, url: str, params: dict[str, str] | None = None) -> object:
        last_error: requests.RequestException | None = None
        for attempt in range(2):
            try:
                response = requests.get(url, params=params, timeout=self.timeout_seconds)
                response.raise_for_status()
                return response.json()
            except requests.RequestException as exc:
                last_error = exc
                if attempt == 0:
                    time.sleep(1)
        assert last_error is not None
        raise last_error

def _summarize_institutional_history(
    daily_rows: list[dict[str, dict[str, object]]],
) -> dict[str, dict[str, object]]:
    """Keep the newest disclosure and derive only the days actually retrieved."""
    codes = {code for rows in daily_rows for code in rows}
    output: dict[str, dict[str, object]] = {}
    for code in codes:
        records = [rows[code] for rows in daily_rows if code in rows]
        latest = dict(records[0])
        foreign = [float(value) for row in records if (value := row.get("foreign")) is not None]
        trust = [float(value) for row in records if (value := row.get("trust")) is not None]
        net_buy_days = sum(
            1
            for row in records
            if sum(float(row.get(key) or 0.0) for key in ("foreign", "trust", "dealer")) > 0
        )
        latest.update({
            "foreign_5d": sum(foreign) if foreign else None,
            "trust_5d": sum(trust) if trust else None,
            "net_buy_days": net_buy_days,
            "flow_days": len(records),
        })
        output[code] = latest
    return output

def _institutional_rows(payload: object, as_of: date) -> dict[str, dict[str, object]]:
    if not isinstance(payload, dict):
        return {}
    fields = payload.get("fields")
    rows = payload.get("data")
    if not isinstance(fields, list) or not isinstance(rows, list):
        return {}
    field_names = [str(field) for field in fields]
    indexes = {
        "code": _field_index(field_names, (_u("8b49", "5238", "4ee3", "865f"), _u("80a1", "7968", "4ee3", "865f"))),
        "foreign": _field_index(field_names, (_u("5916", "9678", "8cc7", "8cb7", "8ce3", "8d85", "80a1", "6578", "0028", "4e0d", "542b", "5916", "8cc7", "81ea", "71df", "5546", "0029"), _u("5916", "9678", "8cc7", "8cb7", "8ce3", "8d85", "80a1", "6578"), _u("5916", "8cc7", "53ca", "9678", "8cc7", "8ce3", "8ce3", "8d85", "80a1", "6578"))),
        "trust": _field_index(field_names, (_u("6295", "4fe1", "8cb7", "8ce3", "8d85", "80a1", "6578"),)),
        "dealer": _field_index(field_names, (_u("81ea", "71df", "5546", "8cb7", "8ce3", "8d85", "80a1", "6578"),)),
    }
    if indexes["code"] is None:
        return {}

    output: dict[str, dict[str, object]] = {}
    for raw in rows:
        if not isinstance(raw, list):
            continue
        code = _row_value(raw, indexes["code"])
        if not code:
            continue
        output[code] = {
            "foreign": _number_value(_row_value(raw, indexes["foreign"])),
            "trust": _number_value(_row_value(raw, indexes["trust"])),
            "dealer": _number_value(_row_value(raw, indexes["dealer"])),
            "as_of": as_of,
        }
    return output


def _has_recent_dividend(dividend: dict[str, object], report_date: date) -> bool:
    """Only surface an annual dividend if it belongs to the current or prior fiscal year."""
    if dividend.get("cash_per_share") is None:
        return False
    try:
        year = int(str(dividend.get("year", "")))
    except (TypeError, ValueError):
        return False
    current_year = report_date.year if year >= 1900 else report_date.year - 1911
    return year >= current_year - 1

def _tpex_institutional_rows(payload: object) -> dict[str, dict[str, object]]:
    if not isinstance(payload, list):
        return {}
    output: dict[str, dict[str, object]] = {}
    for row in payload:
        if not isinstance(row, dict):
            continue
        code = _text(row, "SecuritiesCompanyCode")
        if not code:
            continue
        output[code] = {
            "foreign": _number(
                row,
                "Foreign Investors include Mainland Area Investors (Foreign Dealers excluded)-Difference",
                "ForeignInvestorsInclude MainlandAreaInvestors-Difference",
                "ForeignInvestorsIncludeMainlandAreaInvestors-Difference",
            ),
            "trust": _number(row, "SecuritiesInvestmentTrustCompanies-Difference"),
            "dealer": _number(row, "Dealers-Difference"),
            "flow_days": 1,
            "as_of": _roc_date(_text(row, "Date")),
        }
    return output


def _roc_date(value: str) -> date | None:
    text = value.strip()
    if len(text) != 7 or not text.isdigit():
        return None
    try:
        return date(int(text[:3]) + 1911, int(text[3:5]), int(text[5:]))
    except ValueError:
        return None

def _field_index(fields: list[str], choices: tuple[str, ...]) -> int | None:
    for choice in choices:
        if choice in fields:
            return fields.index(choice)
    return None


def _row_value(row: list[object], index: int | None) -> str:
    if index is None or index >= len(row):
        return ""
    return str(row[index]).strip()


def _text(row: dict[str, object], *keys: str) -> str:
    for key in keys:
        value = row.get(key)
        if value not in (None, ""):
            return str(value).strip()
    return ""


def _number(row: dict[str, object], *keys: str) -> float | None:
    for key in keys:
        value = _number_value(row.get(key))
        if value is not None:
            return value
    return None


def _number_value(value: object) -> float | None:
    if value in (None, "", "--"):
        return None
    text = str(value).replace(",", "").replace("%", "").strip()
    try:
        return float(text)
    except ValueError:
        return None


def _u(*codepoints: str) -> str:
    return "".join(chr(int(codepoint, 16)) for codepoint in codepoints)