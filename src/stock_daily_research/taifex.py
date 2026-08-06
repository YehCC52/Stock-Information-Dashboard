from __future__ import annotations

import re
import time
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from html.parser import HTMLParser

import requests

from .models import TaiwanFuturesPosition


TAIFEX_INSTITUTIONAL_API_URL = (
    "https://openapi.taifex.com.tw/v1/"
    "MarketDataOfMajorInstitutionalTradersDetailsOfFuturesContractsBytheDate"
)
TAIFEX_INSTITUTIONAL_HISTORY_URL = (
    "https://www.taifex.com.tw/cht/3/futContractsDate"
)
_REQUEST_TIMEOUT_SECONDS = 12
_TAIWAN_FUTURES_NAME = "\u81fa\u80a1\u671f\u8ca8"


@dataclass(frozen=True)
class TaifexFetchResult:
    positions: list[TaiwanFuturesPosition]
    warnings: list[str]


class TaifexInstitutionalProvider:
    """Official TAIFEX day-session institutional positions for TX futures."""

    def __init__(self, timeout_seconds: int = _REQUEST_TIMEOUT_SECONDS) -> None:
        self.timeout_seconds = timeout_seconds

    def fetch(
        self,
        report_date: date,
        *,
        history_sessions: int = 5,
    ) -> TaifexFetchResult:
        retrieved_at = datetime.now(timezone.utc)
        target_sessions = min(10, max(2, history_sessions))
        positions: dict[tuple[date, str, str], TaiwanFuturesPosition] = {}

        try:
            payload = self._get_json(TAIFEX_INSTITUTIONAL_API_URL)
        except requests.RequestException:
            payload = None
        for position in _taifex_api_positions(payload, retrieved_at):
            if position.as_of_date <= report_date:
                positions[_position_key(position)] = position

        for offset in range(18):
            if len(_foreign_session_dates(positions.values())) >= target_sessions:
                break
            candidate = report_date - timedelta(days=offset)
            if candidate.weekday() >= 5:
                continue
            if candidate in _foreign_session_dates(positions.values()):
                continue
            try:
                html = self._get_text(
                    TAIFEX_INSTITUTIONAL_HISTORY_URL,
                    params={
                        "doQuery": "1",
                        "queryType": "1",
                        "queryDate": candidate.strftime("%Y/%m/%d"),
                        "commodityId": "TXF",
                    },
                )
            except requests.RequestException:
                continue
            for position in _taifex_html_positions(
                html,
                expected_date=candidate,
                retrieved_at=retrieved_at,
            ):
                positions.setdefault(_position_key(position), position)

        ordered = sorted(
            positions.values(),
            key=lambda item: (
                item.as_of_date,
                item.contract_code,
                item.institution,
            ),
            reverse=True,
        )
        warnings = []
        if not ordered:
            warnings.append(
                "TAIFEX institutional futures positions unavailable for recent trading days."
            )
        return TaifexFetchResult(positions=ordered, warnings=warnings)

    def _get_json(self, url: str) -> object:
        response = self._get_response(url)
        return response.json()

    def _get_text(
        self,
        url: str,
        *,
        params: dict[str, str],
    ) -> str:
        response = self._get_response(url, params=params)
        response.encoding = "utf-8"
        return response.text

    def _get_response(
        self,
        url: str,
        *,
        params: dict[str, str] | None = None,
    ) -> requests.Response:
        last_error: requests.RequestException | None = None
        for attempt in range(2):
            try:
                response = requests.get(
                    url,
                    params=params,
                    timeout=self.timeout_seconds,
                    headers={"User-Agent": "stock-daily-research/0.1"},
                )
                response.raise_for_status()
                return response
            except requests.HTTPError as exc:
                last_error = exc
                status = exc.response.status_code if exc.response is not None else None
                if status is not None and 400 <= status < 500 and status != 429:
                    raise
            except requests.RequestException as exc:
                last_error = exc
            if attempt == 0:
                time.sleep(1)
        assert last_error is not None
        raise last_error


def _taifex_api_positions(
    payload: object,
    retrieved_at: datetime,
) -> list[TaiwanFuturesPosition]:
    if not isinstance(payload, list):
        return []
    output: list[TaiwanFuturesPosition] = []
    for row in payload:
        if not isinstance(row, dict):
            continue
        as_of = _yyyymmdd_date(_text(row, "Date"))
        contract = _text(row, "ContractCode")
        institution = _institution_key(_text(row, "Item"))
        if as_of is None or contract != _TAIWAN_FUTURES_NAME or institution is None:
            continue
        position = _build_position(
            as_of=as_of,
            contract=contract,
            institution=institution,
            values=[
                row.get("TradingVolume(Long)"),
                row.get("TradingValue(Long)(Thousands)"),
                row.get("TradingVolume(Short)"),
                row.get("TradingValue(Short)(Thousands)"),
                row.get("TradingVolume(Net)"),
                row.get("TradingValue(Net)(Thousands)"),
                row.get("OpenInterest(Long)"),
                row.get("ContractValueofOpenInterest(Long)(Thousands)"),
                row.get("OpenInterest(Short)"),
                row.get("ContractValueofOpenInterest(Short)(Thousands)"),
                row.get("OpenInterest(Net)"),
                row.get("ContractValueofOpenInterest(Net)(Thousands)"),
            ],
            source="TAIFEX OpenAPI",
            retrieved_at=retrieved_at,
        )
        if position is not None:
            output.append(position)
    return output


def _taifex_html_positions(
    html: str,
    *,
    expected_date: date,
    retrieved_at: datetime,
) -> list[TaiwanFuturesPosition]:
    date_match = re.search(
        r"\u65e5\u671f\s*(\d{4})/(\d{2})/(\d{2})",
        html,
    )
    if date_match is None:
        return []
    try:
        disclosed_date = date(*(int(value) for value in date_match.groups()))
    except ValueError:
        return []
    if disclosed_date != expected_date:
        return []

    parser = _TableTextParser()
    parser.feed(html)
    output: list[TaiwanFuturesPosition] = []
    current_contract = ""
    for row in parser.rows:
        if len(row) >= 15 and row[0].replace(",", "").isdigit():
            current_contract = row[1]
            institution_label = row[2]
            values = row[3:15]
        elif len(row) >= 13 and current_contract:
            institution_label = row[0]
            values = row[1:13]
        else:
            continue
        if current_contract != _TAIWAN_FUTURES_NAME:
            continue
        institution = _institution_key(institution_label)
        if institution is None:
            continue
        position = _build_position(
            as_of=disclosed_date,
            contract=current_contract,
            institution=institution,
            values=values,
            source="TAIFEX futContractsDate",
            retrieved_at=retrieved_at,
        )
        if position is not None:
            output.append(position)
    return output


def _build_position(
    *,
    as_of: date,
    contract: str,
    institution: str,
    values: list[object],
    source: str,
    retrieved_at: datetime,
) -> TaiwanFuturesPosition | None:
    if len(values) < 12:
        return None
    trading_long = _int_value(values[0])
    trading_short = _int_value(values[2])
    trading_net = _int_value(values[4])
    open_long = _int_value(values[6])
    open_short = _int_value(values[8])
    open_net = _int_value(values[10])
    required = (
        trading_long,
        trading_short,
        open_long,
        open_short,
    )
    if any(value is None for value in required):
        return None
    return TaiwanFuturesPosition(
        as_of_date=as_of,
        contract_code=contract,
        institution=institution,
        trading_long=int(trading_long),
        trading_short=int(trading_short),
        trading_net=(
            int(trading_net)
            if trading_net is not None
            else int(trading_long) - int(trading_short)
        ),
        open_interest_long=int(open_long),
        open_interest_short=int(open_short),
        open_interest_net=(
            int(open_net)
            if open_net is not None
            else int(open_long) - int(open_short)
        ),
        source=source,
        retrieved_at=retrieved_at,
    )


class _TableTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.rows: list[list[str]] = []
        self._row: list[str] | None = None
        self._cell: list[str] | None = None

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        if tag == "tr":
            self._row = []
        elif tag in {"td", "th"} and self._row is not None:
            self._cell = []
        elif tag == "br" and self._cell is not None:
            self._cell.append(" ")

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag in {"td", "th"} and self._cell is not None and self._row is not None:
            value = re.sub(r"\s+", " ", "".join(self._cell)).strip()
            self._row.append(value)
            self._cell = None
        elif tag == "tr" and self._row is not None:
            if any(self._row):
                self.rows.append(self._row)
            self._row = None
            self._cell = None


def _position_key(position: TaiwanFuturesPosition) -> tuple[date, str, str]:
    return (
        position.as_of_date,
        position.contract_code,
        position.institution,
    )


def _foreign_session_dates(
    positions: Iterable[TaiwanFuturesPosition],
) -> set[date]:
    return {
        position.as_of_date
        for position in positions
        if isinstance(position, TaiwanFuturesPosition)
        and position.institution == "foreign"
    }


def _institution_key(value: str) -> str | None:
    compact = value.replace(" ", "")
    if "\u5916\u8cc7" in compact:
        return "foreign"
    if compact == "\u6295\u4fe1":
        return "investment_trust"
    if "\u81ea\u71df\u5546" in compact:
        return "dealer"
    return None


def _yyyymmdd_date(value: str) -> date | None:
    compact = value.strip()
    if len(compact) != 8 or not compact.isdigit():
        return None
    try:
        return date(int(compact[:4]), int(compact[4:6]), int(compact[6:]))
    except ValueError:
        return None


def _text(row: dict[str, object], key: str) -> str:
    value = row.get(key)
    return str(value).strip() if value is not None else ""


def _int_value(value: object) -> int | None:
    if value in (None, "", "--"):
        return None
    text = str(value).replace(",", "").strip()
    try:
        return int(float(text))
    except ValueError:
        return None
