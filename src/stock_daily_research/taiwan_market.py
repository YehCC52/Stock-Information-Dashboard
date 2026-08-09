from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

import requests

from .models import (
    TaiwanInstitutionalMarketSnapshot,
    TaiwanMarketOverview,
    TaiwanMarketPulseSnapshot,
    TaiwanMarketSnapshot,
    TaiwanMarketStockSnapshot,
    TickerConfig,
)


TWSE_MONTHLY_REVENUE_URL = "https://openapi.twse.com.tw/v1/opendata/t187ap05_L"
TWSE_DIVIDEND_URL = "https://openapi.twse.com.tw/v1/opendata/t187ap45_L"
TWSE_INSTITUTIONAL_URL = "https://www.twse.com.tw/rwd/zh/fund/T86"
TWSE_INSTITUTIONAL_SUMMARY_URL = "https://www.twse.com.tw/rwd/zh/fund/BFI82U"
TPEX_MONTHLY_REVENUE_URL = "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap05_O"
TPEX_DIVIDEND_URL = "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap39_O"
TPEX_INSTITUTIONAL_URL = "https://www.tpex.org.tw/openapi/v1/tpex_3insti_daily_trading"
TPEX_INSTITUTIONAL_SUMMARY_URL = "https://www.tpex.org.tw/openapi/v1/tpex_3insti_summary"
TWSE_MARGIN_URL = "https://www.twse.com.tw/rwd/zh/marginTrading/MI_MARGN"
TWSE_DAILY_CLOSE_URL = "https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX"
TWSE_COMPANY_PROFILE_URL = "https://openapi.twse.com.tw/v1/opendata/t187ap03_L"
TPEX_COMPANY_PROFILE_URL = "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_O"
TPEX_DAILY_CLOSE_URL = "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_daily_close_quotes"
TPEX_MARKET_HIGHLIGHT_URL = "https://www.tpex.org.tw/openapi/v1/tpex_mainborad_highlight"
_MARKET_HISTORY_SESSIONS = 6
_INDUSTRY_NAMES = {
    "01": "\u6c34\u6ce5\u5de5\u696d",
    "02": "\u98df\u54c1\u5de5\u696d",
    "03": "\u5851\u81a0\u5de5\u696d",
    "04": "\u7d21\u7e54\u7e96\u7dad",
    "05": "\u96fb\u6a5f\u6a5f\u68b0",
    "06": "\u96fb\u5668\u96fb\u7e9c",
    "08": "\u73bb\u7483\u9676\u74f7",
    "09": "\u9020\u7d19\u5de5\u696d",
    "10": "\u92fc\u9435\u5de5\u696d",
    "11": "\u6a61\u81a0\u5de5\u696d",
    "12": "\u6c7d\u8eca\u5de5\u696d",
    "14": "\u5efa\u6750\u71df\u9020",
    "15": "\u822a\u904b\u696d",
    "16": "\u89c0\u5149\u9910\u65c5",
    "17": "\u91d1\u878d\u4fdd\u96aa",
    "18": "\u8cbf\u6613\u767e\u8ca8",
    "20": "\u5176\u4ed6",
    "21": "\u5316\u5b78\u5de5\u696d",
    "22": "\u751f\u6280\u91ab\u7642",
    "23": "\u6cb9\u96fb\u71c3\u6c23",
    "24": "\u534a\u5c0e\u9ad4",
    "25": "\u96fb\u8166\u53ca\u9031\u908a\u8a2d\u5099",
    "26": "\u5149\u96fb",
    "27": "\u901a\u4fe1\u7db2\u8def",
    "28": "\u96fb\u5b50\u96f6\u7d44\u4ef6",
    "29": "\u96fb\u5b50\u901a\u8def",
    "30": "\u8cc7\u8a0a\u670d\u52d9",
    "31": "\u5176\u4ed6\u96fb\u5b50",
    "32": "\u6587\u5316\u5275\u610f",
    "33": "\u8fb2\u696d\u79d1\u6280",
    "35": "\u7da0\u80fd\u74b0\u4fdd",
    "36": "\u6578\u4f4d\u96f2\u7aef",
    "37": "\u904b\u52d5\u4f11\u9592",
    "38": "\u5c45\u5bb6\u751f\u6d3b",
    "80": "\u7ba1\u7406\u80a1\u7968",
}
_REQUEST_TIMEOUT_SECONDS = 12
_MIN_MARGIN_PRICE_COVERAGE_PCT = 95.0


@dataclass(frozen=True)
class TaiwanMarketFetchResult:
    snapshots: dict[str, TaiwanMarketSnapshot]
    overview: TaiwanMarketOverview | None
    warnings: list[str]
    institutional_market: list[TaiwanInstitutionalMarketSnapshot] = field(default_factory=list)
    market_pulse: list[TaiwanMarketPulseSnapshot] = field(default_factory=list)
    market_stocks: list[TaiwanMarketStockSnapshot] = field(default_factory=list)


class TaiwanMarketDataProvider:
    """Official TWSE and TPEx disclosures for Taiwan watchlist securities."""

    def __init__(
        self,
        timeout_seconds: int = _REQUEST_TIMEOUT_SECONDS,
        *,
        include_market_overview: bool = True,
        include_institutional_market: bool | None = None,
        include_market_pulse: bool | None = None,
    ) -> None:
        self.timeout_seconds = timeout_seconds
        self.include_market_overview = include_market_overview
        self.include_institutional_market = (
            include_market_overview
            if include_institutional_market is None
            else include_institutional_market
        )
        self.include_market_pulse = (
            include_market_overview
            if include_market_pulse is None
            else include_market_pulse
        )

    def fetch(self, tickers: list[TickerConfig], report_date: date) -> TaiwanMarketFetchResult:
        twse_tickers = [ticker for ticker in tickers if ticker.market == "twse"]
        tpex_tickers = [ticker for ticker in tickers if ticker.market == "tpex"]
        taiwan_tickers = [*twse_tickers, *tpex_tickers]
        if not taiwan_tickers:
            return TaiwanMarketFetchResult(snapshots={}, overview=None, warnings=[])

        warnings: list[str] = []
        retrieved_at = datetime.now(timezone.utc)
        overview = (
            self._margin_maintenance_overview(report_date, retrieved_at, warnings)
            if self.include_market_overview
            else None
        )
        institutional_market = (
            self._institutional_market_overview(report_date, retrieved_at, warnings)
            if self.include_institutional_market
            else []
        )
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
            flow_by_symbol.update(self._tpex_institutional_flow(report_date, warnings))

        market_pulse: list[TaiwanMarketPulseSnapshot] = []
        market_stocks: list[TaiwanMarketStockSnapshot] = []
        if self.include_market_pulse:
            market_pulse, market_stocks = self._market_history(
                report_date,
                retrieved_at,
                warnings,
                include_twse=bool(twse_tickers),
                include_tpex=bool(tpex_tickers),
                flow_by_symbol=flow_by_symbol,
            )

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
                institutional_net_shares=flow.get("total"),
                foreign_net_shares_5d=flow.get("foreign_5d"),
                investment_trust_net_shares_5d=flow.get("trust_5d"),
                dealer_net_shares_5d=flow.get("dealer_5d"),
                institutional_net_shares_5d=flow.get("total_5d"),
                institutional_net_buy_days_5d=flow.get("net_buy_days"),
                institutional_flow_days=int(flow.get("flow_days", 0) or 0),
                institutional_as_of=flow.get("as_of"),
                source="TWSE OpenAPI / T86" if ticker.market == "twse" else "TPEx OpenAPI",
                retrieved_at=retrieved_at,
            )
        return TaiwanMarketFetchResult(
            snapshots=snapshots,
            overview=overview,
            warnings=warnings,
            institutional_market=institutional_market,
            market_pulse=market_pulse,
            market_stocks=market_stocks,
        )

    def _margin_maintenance_overview(
        self,
        report_date: date,
        retrieved_at: datetime,
        warnings: list[str],
    ) -> TaiwanMarketOverview | None:
        low_coverage_pct: float | None = None
        for offset in range(10):
            candidate = report_date - timedelta(days=offset)
            if candidate.weekday() >= 5:
                continue
            try:
                margin_payload = self._get_json(
                    TWSE_MARGIN_URL,
                    params={"date": candidate.strftime("%Y%m%d"), "selectType": "ALL", "response": "json"},
                )
            except requests.RequestException:
                continue
            if _payload_date(margin_payload) is None:
                continue
            try:
                close_payload = self._get_json(
                    TWSE_DAILY_CLOSE_URL,
                    params={"date": candidate.strftime("%Y%m%d"), "type": "ALLBUT0999", "response": "json"},
                )
            except requests.RequestException:
                continue
            overview = _margin_maintenance_snapshot(margin_payload, close_payload, retrieved_at)
            if overview is None:
                continue
            if overview.price_coverage_pct < _MIN_MARGIN_PRICE_COVERAGE_PCT:
                low_coverage_pct = overview.price_coverage_pct
                continue
            return overview

        if low_coverage_pct is not None:
            warnings.append(
                f"TWSE margin maintenance estimate unavailable: close-price coverage was {low_coverage_pct:.2f}%."
            )
        else:
            warnings.append(
                "TWSE margin maintenance estimate unavailable for recent trading days."
            )
        return None

    def _institutional_market_overview(
        self,
        report_date: date,
        retrieved_at: datetime,
        warnings: list[str],
    ) -> list[TaiwanInstitutionalMarketSnapshot]:
        snapshots: list[TaiwanInstitutionalMarketSnapshot] = []
        for offset in range(10):
            candidate = report_date - timedelta(days=offset)
            if candidate.weekday() >= 5:
                continue
            try:
                payload = self._get_json(
                    TWSE_INSTITUTIONAL_SUMMARY_URL,
                    params={
                        "date": candidate.strftime("%Y%m%d"),
                        "response": "json",
                    },
                )
            except requests.RequestException:
                continue
            snapshot = _twse_institutional_market_snapshot(payload, retrieved_at)
            if (
                snapshot is not None
                and snapshot.as_of_date <= report_date
                and (report_date - snapshot.as_of_date).days <= 10
            ):
                snapshots.append(snapshot)
                break

        try:
            tpex_payload = self._get_json(TPEX_INSTITUTIONAL_SUMMARY_URL)
        except requests.RequestException:
            tpex_payload = None
        tpex_snapshot = _tpex_institutional_market_snapshot(
            tpex_payload,
            retrieved_at,
        )
        if (
            tpex_snapshot is not None
            and tpex_snapshot.as_of_date <= report_date
            and (report_date - tpex_snapshot.as_of_date).days <= 10
        ):
            snapshots.append(tpex_snapshot)

        if not snapshots:
            warnings.append(
                "Taiwan institutional market totals unavailable for recent trading days."
            )
        return snapshots

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

    def _tpex_institutional_flow(
        self,
        report_date: date,
        warnings: list[str],
    ) -> dict[str, dict[str, object]]:
        try:
            payload = self._get_json(TPEX_INSTITUTIONAL_URL)
        except requests.RequestException as exc:
            warnings.append(f"TPEx institutional-flow data unavailable: {exc}")
            return {}
        rows = _tpex_institutional_rows(payload, before_or_on=report_date)
        if not rows:
            warnings.append("TPEx institutional-flow data unavailable: unexpected payload.")
        return rows
    def _market_history(
        self,
        report_date: date,
        retrieved_at: datetime,
        warnings: list[str],
        *,
        include_twse: bool,
        include_tpex: bool,
        flow_by_symbol: dict[str, dict[str, object]],
    ) -> tuple[list[TaiwanMarketPulseSnapshot], list[TaiwanMarketStockSnapshot]]:
        pulses: list[TaiwanMarketPulseSnapshot] = []
        stocks: list[TaiwanMarketStockSnapshot] = []

        if include_twse:
            profiles = self._company_profiles(
                TWSE_COMPANY_PROFILE_URL,
                "TWSE",
                warnings,
            )
            seen_dates: set[date] = set()
            for offset in range(18):
                candidate = report_date - timedelta(days=offset)
                if candidate.weekday() >= 5:
                    continue
                try:
                    payload = self._get_json(
                        TWSE_DAILY_CLOSE_URL,
                        params={
                            "date": candidate.strftime("%Y%m%d"),
                            "type": "ALLBUT0999",
                            "response": "json",
                        },
                    )
                except requests.RequestException:
                    continue
                session = _twse_market_session(
                    payload,
                    profiles,
                    flow_by_symbol,
                    retrieved_at,
                )
                if session is None:
                    continue
                pulse, session_stocks = session
                if pulse.as_of_date > report_date or pulse.as_of_date in seen_dates:
                    continue
                seen_dates.add(pulse.as_of_date)
                pulses.append(pulse)
                stocks.extend(session_stocks)
                if len(seen_dates) >= _MARKET_HISTORY_SESSIONS:
                    break
            if not seen_dates:
                warnings.append("TWSE whole-market close and breadth data unavailable.")

        if include_tpex:
            profiles = self._company_profiles(
                TPEX_COMPANY_PROFILE_URL,
                "TPEx",
                warnings,
            )
            try:
                close_payload = self._get_json(TPEX_DAILY_CLOSE_URL)
            except requests.RequestException as exc:
                warnings.append(f"TPEx whole-market close data unavailable: {exc}")
                close_payload = None
            tpex_pulses, tpex_stocks = _tpex_market_sessions(
                close_payload,
                profiles,
                flow_by_symbol,
                retrieved_at,
                report_date,
                session_limit=_MARKET_HISTORY_SESSIONS,
            )
            pulses.extend(tpex_pulses)
            stocks.extend(tpex_stocks)

            try:
                highlight_payload = self._get_json(TPEX_MARKET_HIGHLIGHT_URL)
            except requests.RequestException as exc:
                warnings.append(f"TPEx market highlight unavailable: {exc}")
                highlight_payload = None
            official_pulse = _tpex_market_highlight_snapshot(
                highlight_payload,
                retrieved_at,
                report_date,
            )
            if official_pulse is not None:
                pulses = [
                    pulse
                    for pulse in pulses
                    if not (
                        pulse.market == "tpex"
                        and pulse.as_of_date == official_pulse.as_of_date
                    )
                ]
                pulses.append(official_pulse)
            if not tpex_stocks:
                warnings.append("TPEx whole-market stock data unavailable.")

        pulses.sort(key=lambda item: (item.as_of_date, item.market), reverse=True)
        stocks.sort(
            key=lambda item: (item.as_of_date, item.market, item.symbol),
            reverse=True,
        )
        return pulses, stocks

    def _company_profiles(
        self,
        url: str,
        source: str,
        warnings: list[str],
    ) -> dict[str, dict[str, str]]:
        try:
            payload = self._get_json(url)
        except requests.RequestException as exc:
            warnings.append(f"{source} company classification unavailable: {exc}")
            return {}
        profiles = _company_profile_rows(payload, source.lower())
        if not profiles:
            warnings.append(
                f"{source} company classification unavailable: unexpected payload."
            )
        return profiles

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


def _company_profile_rows(
    payload: object,
    market: str,
) -> dict[str, dict[str, str]]:
    if not isinstance(payload, list):
        return {}
    output: dict[str, dict[str, str]] = {}
    for row in payload:
        if not isinstance(row, dict):
            continue
        if market == "twse":
            code = _text(
                row,
                "\u516c\u53f8\u4ee3\u865f",
                "\u8b49\u5238\u4ee3\u865f",
            )
            name = _text(
                row,
                "\u516c\u53f8\u7c21\u7a31",
                "\u516c\u53f8\u540d\u7a31",
            )
            industry_code = _text(row, "\u7522\u696d\u5225")
        else:
            code = _text(row, "SecuritiesCompanyCode", "CompanyCode")
            name = _text(
                row,
                "CompanyAbbreviation",
                "CompanyName",
                "SecuritiesCompanyName",
            )
            industry_code = _text(
                row,
                "SecuritiesIndustryCode",
                "IndustryCode",
            )
        code = code.strip()
        industry_code = industry_code.strip().zfill(2) if industry_code else ""
        if not code:
            continue
        output[code] = {
            "name": name.strip() or code,
            "industry_code": industry_code,
            "industry_name": _INDUSTRY_NAMES.get(
                industry_code,
                "\u672a\u5206\u985e",
            ),
        }
    return output


def _twse_market_session(
    payload: object,
    profiles: dict[str, dict[str, str]],
    flow_by_symbol: dict[str, dict[str, object]],
    retrieved_at: datetime,
) -> tuple[TaiwanMarketPulseSnapshot, list[TaiwanMarketStockSnapshot]] | None:
    as_of = _payload_date(payload)
    if as_of is None:
        return None
    close_table = _table_with_fields(
        payload,
        ("\u8b49\u5238\u4ee3\u865f", "\u6536\u76e4\u50f9"),
    )
    stocks: list[TaiwanMarketStockSnapshot] = []
    if close_table is not None:
        fields = [str(value) for value in close_table["fields"]]
        indexes = {
            "code": _field_index(fields, ("\u8b49\u5238\u4ee3\u865f",)),
            "name": _field_index(fields, ("\u8b49\u5238\u540d\u7a31",)),
            "shares": _field_index(fields, ("\u6210\u4ea4\u80a1\u6578",)),
            "amount": _field_index(fields, ("\u6210\u4ea4\u91d1\u984d",)),
            "close": _field_index(fields, ("\u6536\u76e4\u50f9",)),
            "sign": _field_index(fields, ("\u6f32\u8dcc(+/-)",)),
            "change": _field_index(fields, ("\u6f32\u8dcc\u50f9\u5dee",)),
        }
        for raw in close_table["data"]:
            if not isinstance(raw, list):
                continue
            code = _row_value(raw, indexes["code"])
            profile = profiles.get(code)
            if profiles and profile is None:
                continue
            if profile is None and not (len(code) == 4 and code.isdigit()):
                continue
            close = _number_value(_row_value(raw, indexes["close"]))
            if close is None or close <= 0:
                continue
            change = _number_value(_row_value(raw, indexes["change"])) or 0.0
            signed_change = _signed_change(
                _row_value(raw, indexes["sign"]),
                change,
            )
            change_pct = _close_change_pct(close, signed_change)
            flow = _flow_for_session(flow_by_symbol.get(code, {}), as_of)
            industry_code = profile.get("industry_code", "") if profile else ""
            stocks.append(
                TaiwanMarketStockSnapshot(
                    as_of_date=as_of,
                    market="twse",
                    symbol=f"{code}.TW",
                    company_name=(
                        profile.get("name", code)
                        if profile
                        else _row_value(raw, indexes["name"]) or code
                    ),
                    industry_code=industry_code,
                    industry_name=(
                        profile.get("industry_name", "\u672a\u5206\u985e")
                        if profile
                        else "\u672a\u5206\u985e"
                    ),
                    close=close,
                    change_pct=round(change_pct, 4),
                    trading_shares=_number_value(
                        _row_value(raw, indexes["shares"])
                    ) or 0.0,
                    turnover_twd=_number_value(
                        _row_value(raw, indexes["amount"])
                    ) or 0.0,
                    foreign_net_shares=flow.get("foreign"),
                    investment_trust_net_shares=flow.get("trust"),
                    dealer_net_shares=flow.get("dealer"),
                    institutional_net_shares=flow.get("total"),
                    source="TWSE MI_INDEX / company profile / T86",
                    retrieved_at=retrieved_at,
                )
            )

    pulse = _twse_market_pulse_snapshot(
        payload,
        stocks,
        retrieved_at,
    )
    if pulse is None:
        return None
    return pulse, stocks


def _twse_market_pulse_snapshot(
    payload: object,
    stocks: list[TaiwanMarketStockSnapshot],
    retrieved_at: datetime,
) -> TaiwanMarketPulseSnapshot | None:
    as_of = _payload_date(payload)
    if as_of is None:
        return None
    index_close: float | None = None
    index_change_pct: float | None = None
    index_table = _table_with_fields(
        payload,
        ("\u6307\u6578", "\u6536\u76e4\u6307\u6578"),
    )
    if index_table is not None:
        fields = [str(value) for value in index_table["fields"]]
        label_index = _field_index(fields, ("\u6307\u6578",))
        close_index = _field_index(fields, ("\u6536\u76e4\u6307\u6578",))
        pct_index = _field_index(
            fields,
            (
                "\u6f32\u8dcc\u767e\u5206\u6bd4(%)",
                "\u6f32\u8dcc\u5e45\u5ea6(%)",
            ),
        )
        for raw in index_table["data"]:
            if not isinstance(raw, list):
                continue
            label = _row_value(raw, label_index)
            if "\u767c\u884c\u91cf\u52a0\u6b0a\u80a1\u50f9\u6307\u6578" not in label:
                continue
            index_close = _number_value(_row_value(raw, close_index))
            index_change_pct = _number_value(_row_value(raw, pct_index))
            break

    advancers = sum(1 for item in stocks if item.change_pct > 0)
    decliners = sum(1 for item in stocks if item.change_pct < 0)
    unchanged = len(stocks) - advancers - decliners
    limit_up = sum(1 for item in stocks if item.change_pct >= 9.5)
    limit_down = sum(1 for item in stocks if item.change_pct <= -9.5)
    breadth_table = _table_with_fields(
        payload,
        ("\u985e\u578b", "\u6574\u9ad4\u5e02\u5834", "\u80a1\u7968"),
    )
    if breadth_table is not None:
        fields = [str(value) for value in breadth_table["fields"]]
        label_index = _field_index(fields, ("\u985e\u578b",))
        stock_index = _field_index(fields, ("\u80a1\u7968",))
        for raw in breadth_table["data"]:
            if not isinstance(raw, list):
                continue
            label = _row_value(raw, label_index).replace(" ", "")
            count, limit_count = _market_count_parts(
                _row_value(raw, stock_index)
            )
            if label.startswith("\u4e0a\u6f32"):
                advancers, limit_up = count, limit_count
            elif label.startswith("\u4e0b\u8dcc"):
                decliners, limit_down = count, limit_count
            elif label.startswith("\u6301\u5e73"):
                unchanged = count

    turnover = sum(item.turnover_twd for item in stocks)
    stats_table = _table_with_fields(
        payload,
        ("\u6210\u4ea4\u7d71\u8a08", "\u6210\u4ea4\u91d1\u984d(\u5143)"),
    )
    if stats_table is not None:
        fields = [str(value) for value in stats_table["fields"]]
        label_index = _field_index(fields, ("\u6210\u4ea4\u7d71\u8a08",))
        amount_index = _field_index(fields, ("\u6210\u4ea4\u91d1\u984d(\u5143)",))
        for raw in stats_table["data"]:
            if not isinstance(raw, list):
                continue
            label = _row_value(raw, label_index).replace(" ", "")
            if label.startswith("1.\u4e00\u822c\u80a1\u7968"):
                turnover = _number_value(
                    _row_value(raw, amount_index)
                ) or turnover
                break

    return TaiwanMarketPulseSnapshot(
        as_of_date=as_of,
        market="twse",
        index_name="\u52a0\u6b0a\u6307\u6578",
        index_close=index_close,
        index_change_pct=index_change_pct,
        turnover_twd=turnover,
        advancers=advancers,
        decliners=decliners,
        unchanged=unchanged,
        limit_up=limit_up,
        limit_down=limit_down,
        source="TWSE MI_INDEX",
        retrieved_at=retrieved_at,
    )


def _tpex_market_sessions(
    payload: object,
    profiles: dict[str, dict[str, str]],
    flow_by_symbol: dict[str, dict[str, object]],
    retrieved_at: datetime,
    before_or_on: date,
    *,
    session_limit: int,
) -> tuple[list[TaiwanMarketPulseSnapshot], list[TaiwanMarketStockSnapshot]]:
    if not isinstance(payload, list):
        return [], []
    rows_by_date: dict[date, list[dict[str, object]]] = {}
    for row in payload:
        if not isinstance(row, dict):
            continue
        as_of = _taiwan_date(_text(row, "Date"))
        if as_of is None or as_of > before_or_on:
            continue
        rows_by_date.setdefault(as_of, []).append(row)

    pulses: list[TaiwanMarketPulseSnapshot] = []
    stocks: list[TaiwanMarketStockSnapshot] = []
    for as_of in sorted(rows_by_date, reverse=True)[:max(1, session_limit)]:
        session_stocks: list[TaiwanMarketStockSnapshot] = []
        for row in rows_by_date[as_of]:
            code = _text(row, "SecuritiesCompanyCode")
            profile = profiles.get(code)
            if profiles and profile is None:
                continue
            if profile is None and not (len(code) == 4 and code.isdigit()):
                continue
            close = _number(row, "Close")
            if close is None or close <= 0:
                continue
            signed_change = _number(row, "Change") or 0.0
            flow = _flow_for_session(flow_by_symbol.get(code, {}), as_of)
            industry_code = profile.get("industry_code", "") if profile else ""
            session_stocks.append(
                TaiwanMarketStockSnapshot(
                    as_of_date=as_of,
                    market="tpex",
                    symbol=f"{code}.TWO",
                    company_name=(
                        profile.get("name", code)
                        if profile
                        else _text(row, "CompanyName") or code
                    ),
                    industry_code=industry_code,
                    industry_name=(
                        profile.get("industry_name", "\u672a\u5206\u985e")
                        if profile
                        else "\u672a\u5206\u985e"
                    ),
                    close=close,
                    change_pct=round(
                        _close_change_pct(close, signed_change),
                        4,
                    ),
                    trading_shares=_number(row, "TradingShares") or 0.0,
                    turnover_twd=_number(row, "TransactionAmount") or 0.0,
                    foreign_net_shares=flow.get("foreign"),
                    investment_trust_net_shares=flow.get("trust"),
                    dealer_net_shares=flow.get("dealer"),
                    institutional_net_shares=flow.get("total"),
                    source="TPEx daily close / company profile / 3insti",
                    retrieved_at=retrieved_at,
                )
            )
        if not session_stocks:
            continue
        stocks.extend(session_stocks)
        advancers = sum(1 for item in session_stocks if item.change_pct > 0)
        decliners = sum(1 for item in session_stocks if item.change_pct < 0)
        pulses.append(
            TaiwanMarketPulseSnapshot(
                as_of_date=as_of,
                market="tpex",
                index_name="\u6ac3\u8cb7\u6307\u6578",
                index_close=None,
                index_change_pct=None,
                turnover_twd=sum(item.turnover_twd for item in session_stocks),
                advancers=advancers,
                decliners=decliners,
                unchanged=len(session_stocks) - advancers - decliners,
                limit_up=sum(
                    1 for item in session_stocks if item.change_pct >= 9.5
                ),
                limit_down=sum(
                    1 for item in session_stocks if item.change_pct <= -9.5
                ),
                source="TPEx daily close",
                retrieved_at=retrieved_at,
            )
        )
    return pulses, stocks


def _tpex_market_highlight_snapshot(
    payload: object,
    retrieved_at: datetime,
    before_or_on: date,
) -> TaiwanMarketPulseSnapshot | None:
    if not isinstance(payload, list):
        return None
    candidates: list[tuple[date, dict[str, object]]] = []
    for row in payload:
        if not isinstance(row, dict):
            continue
        as_of = _taiwan_date(_text(row, "Date"))
        if as_of is not None and as_of <= before_or_on:
            candidates.append((as_of, row))
    if not candidates:
        return None
    as_of, row = max(candidates, key=lambda item: item[0])
    index_close = _number(row, "CloseIndex")
    index_change = _number(row, "IndexChange")
    index_change_pct = (
        _close_change_pct(index_close, index_change)
        if index_close is not None and index_change is not None
        else None
    )
    return TaiwanMarketPulseSnapshot(
        as_of_date=as_of,
        market="tpex",
        index_name="\u6ac3\u8cb7\u6307\u6578",
        index_close=index_close,
        index_change_pct=index_change_pct,
        turnover_twd=(_number(row, "DailyTradingValue") or 0.0) * 1_000_000,
        advancers=int(_number(row, "PriceRiseCompanyNumbers") or 0),
        decliners=int(_number(row, "PriceDeclineCompanyNumbers") or 0),
        unchanged=int(_number(row, "PriceFlatCompanyNumbers") or 0),
        limit_up=int(_number(row, "LimitUpCompanyNumbers") or 0),
        limit_down=int(_number(row, "LimitDownCompanyNumbers") or 0),
        source="TPEx market highlight",
        retrieved_at=retrieved_at,
    )


def _flow_for_session(
    flow: dict[str, object],
    as_of: date,
) -> dict[str, float | None]:
    if flow.get("as_of") != as_of:
        return {
            "foreign": None,
            "trust": None,
            "dealer": None,
            "total": None,
        }
    return {
        "foreign": _optional_float(flow.get("foreign")),
        "trust": _optional_float(flow.get("trust")),
        "dealer": _optional_float(flow.get("dealer")),
        "total": _optional_float(flow.get("total")),
    }


def _optional_float(value: object) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _signed_change(sign: str, value: float) -> float:
    normalized = sign.lower()
    if "-" in normalized or "green" in normalized or "\u2212" in normalized:
        return -abs(value)
    if "+" in normalized or "red" in normalized:
        return abs(value)
    return value


def _close_change_pct(close: float, signed_change: float) -> float:
    previous = close - signed_change
    if previous <= 0:
        return 0.0
    return signed_change / previous * 100.0


def _market_count_parts(value: str) -> tuple[int, int]:
    normalized = value.replace(",", "").replace(" ", "")
    head, _, tail = normalized.partition("(")
    count = int(float(head)) if head else 0
    limit_text = tail.rstrip(")")
    limit_count = int(float(limit_text)) if limit_text else 0
    return count, limit_count


def _taiwan_date(value: str) -> date | None:
    normalized = value.strip().replace("/", "").replace("-", "")
    if len(normalized) == 7 and normalized.isdigit():
        return _roc_date(normalized)
    if len(normalized) == 8 and normalized.isdigit():
        try:
            return date(
                int(normalized[:4]),
                int(normalized[4:6]),
                int(normalized[6:]),
            )
        except ValueError:
            return None
    return None


def _margin_maintenance_snapshot(
    margin_payload: object,
    close_payload: object,
    retrieved_at: datetime,
) -> TaiwanMarketOverview | None:
    """Estimate listed-market financing maintenance from same-day TWSE data."""
    margin_date = _payload_date(margin_payload)
    close_date = _payload_date(close_payload)
    if margin_date is None or close_date != margin_date:
        return None

    summary = _table_with_fields(
        margin_payload,
        ("\u9805\u76ee", "\u524d\u65e5\u9918\u984d", "\u4eca\u65e5\u9918\u984d"),
    )
    balances = _table_with_fields(
        margin_payload,
        ("\u4ee3\u865f", "\u524d\u65e5\u9918\u984d", "\u4eca\u65e5\u9918\u984d"),
    )
    closes = _table_with_fields(
        close_payload,
        ("\u8b49\u5238\u4ee3\u865f", "\u6536\u76e4\u50f9"),
    )
    if summary is None or balances is None or closes is None:
        return None

    summary_fields = [str(value) for value in summary["fields"]]
    item_index = summary_fields.index("\u9805\u76ee")
    previous_index = summary_fields.index("\u524d\u65e5\u9918\u984d")
    current_index = summary_fields.index("\u4eca\u65e5\u9918\u984d")
    financing_balance: float | None = None
    previous_financing_balance: float | None = None
    total_margin_units: float | None = None
    for row in summary["data"]:
        if not isinstance(row, list):
            continue
        label = _row_value(row, item_index).replace(" ", "")
        if label.startswith("\u878d\u8cc7\u91d1\u984d"):
            financing_balance = _number_value(_row_value(row, current_index))
            previous_financing_balance = _number_value(_row_value(row, previous_index))
        elif label.startswith("\u878d\u8cc7("):
            total_margin_units = _number_value(_row_value(row, current_index))

    if financing_balance is None or financing_balance <= 0:
        return None

    close_fields = [str(value) for value in closes["fields"]]
    close_code_index = close_fields.index("\u8b49\u5238\u4ee3\u865f")
    close_price_index = close_fields.index("\u6536\u76e4\u50f9")
    prices: dict[str, float] = {}
    for row in closes["data"]:
        if not isinstance(row, list):
            continue
        code = _row_value(row, close_code_index)
        price = _number_value(_row_value(row, close_price_index))
        if code and price is not None and price > 0:
            prices[code] = price

    balance_fields = [str(value) for value in balances["fields"]]
    balance_code_index = balance_fields.index("\u4ee3\u865f")
    balance_index = balance_fields.index("\u4eca\u65e5\u9918\u984d")
    collateral_value = 0.0
    priced_margin_units = 0.0
    detail_margin_units = 0.0
    priced_security_count = 0
    margin_security_count = 0
    for row in balances["data"]:
        if not isinstance(row, list):
            continue
        code = _row_value(row, balance_code_index)
        units = _number_value(_row_value(row, balance_index))
        if not code or units is None or units <= 0:
            continue
        margin_security_count += 1
        detail_margin_units += units
        price = prices.get(code)
        if price is None:
            continue
        priced_security_count += 1
        priced_margin_units += units
        # One trading unit is normally 1,000 shares; TWD and thousand-TWD cancel.
        collateral_value += price * units

    coverage_denominator = total_margin_units or detail_margin_units
    if collateral_value <= 0 or coverage_denominator <= 0:
        return None
    coverage = min(100.0, priced_margin_units / coverage_denominator * 100.0)
    ratio = collateral_value / financing_balance * 100.0
    return TaiwanMarketOverview(
        as_of_date=margin_date,
        margin_maintenance_ratio_estimate=round(ratio, 2),
        collateral_value_thousand_twd=round(collateral_value, 2),
        financing_balance_thousand_twd=round(financing_balance, 2),
        previous_financing_balance_thousand_twd=(
            round(previous_financing_balance, 2)
            if previous_financing_balance is not None
            else None
        ),
        priced_margin_units=round(priced_margin_units, 2),
        total_margin_units=round(coverage_denominator, 2),
        price_coverage_pct=round(coverage, 2),
        priced_security_count=priced_security_count,
        margin_security_count=margin_security_count,
        source="TWSE MI_MARGN / MI_INDEX",
        retrieved_at=retrieved_at,
    )


def _twse_institutional_market_snapshot(
    payload: object,
    retrieved_at: datetime,
) -> TaiwanInstitutionalMarketSnapshot | None:
    as_of = _payload_date(payload)
    if as_of is None or not isinstance(payload, dict):
        return None
    fields = payload.get("fields")
    rows = payload.get("data")
    if not isinstance(fields, list) or not isinstance(rows, list):
        return None
    field_names = [str(value) for value in fields]
    name_index = _field_index(
        field_names,
        ("\u55ae\u4f4d\u540d\u7a31",),
    )
    net_index = _field_index(
        field_names,
        ("\u8cb7\u8ce3\u5dee\u984d", "\u8cb7\u8ce3\u8d85"),
    )
    if name_index is None or net_index is None:
        return None

    foreign: float | None = None
    trust: float | None = None
    total: float | None = None
    dealer_parts: list[float] = []
    for row in rows:
        if not isinstance(row, list):
            continue
        label = _row_value(row, name_index).replace(" ", "")
        value = _number_value(_row_value(row, net_index))
        if value is None:
            continue
        if label.startswith("\u5916\u8cc7\u53ca\u9678\u8cc7(") and "\u4e0d\u542b" in label:
            foreign = value
        elif label == "\u6295\u4fe1":
            trust = value
        elif label.startswith("\u81ea\u71df\u5546("):
            dealer_parts.append(value)
        elif label == "\u5408\u8a08":
            total = value

    dealer = sum(dealer_parts) if dealer_parts else None
    if any(value is None for value in (foreign, trust, dealer)):
        return None
    calculated_total = float(foreign) + float(trust) + float(dealer)
    return TaiwanInstitutionalMarketSnapshot(
        as_of_date=as_of,
        market="twse",
        foreign_net_twd=float(foreign),
        investment_trust_net_twd=float(trust),
        dealer_net_twd=float(dealer),
        total_net_twd=float(total) if total is not None else calculated_total,
        source="TWSE BFI82U",
        retrieved_at=retrieved_at,
    )


def _tpex_institutional_market_snapshot(
    payload: object,
    retrieved_at: datetime,
) -> TaiwanInstitutionalMarketSnapshot | None:
    if not isinstance(payload, list):
        return None
    as_of: date | None = None
    foreign: float | None = None
    foreign_fallback: float | None = None
    trust: float | None = None
    dealer: float | None = None
    total: float | None = None
    for row in payload:
        if not isinstance(row, dict):
            continue
        row_date = _roc_date(_text(row, "Date"))
        if row_date is None:
            continue
        if as_of is None:
            as_of = row_date
        if row_date != as_of:
            continue
        label = _text(row, "Investor").replace(" ", "")
        value = _number(row, "Net")
        if value is None:
            continue
        if label.startswith("\u5916\u8cc7\u53ca\u9678\u8cc7") and "\u4e0d\u542b\u81ea\u71df\u5546" in label:
            foreign = value
        elif label == "\u5916\u8cc7\u53ca\u9678\u8cc7\u5408\u8a08":
            foreign_fallback = value
        elif label == "\u6295\u4fe1":
            trust = value
        elif label == "\u81ea\u71df\u5546\u5408\u8a08":
            dealer = value
        elif label.rstrip("*") == "\u4e09\u5927\u6cd5\u4eba\u5408\u8a08":
            total = value

    foreign = foreign if foreign is not None else foreign_fallback
    if as_of is None or any(value is None for value in (foreign, trust, dealer)):
        return None
    calculated_total = float(foreign) + float(trust) + float(dealer)
    return TaiwanInstitutionalMarketSnapshot(
        as_of_date=as_of,
        market="tpex",
        foreign_net_twd=float(foreign),
        investment_trust_net_twd=float(trust),
        dealer_net_twd=float(dealer),
        total_net_twd=float(total) if total is not None else calculated_total,
        source="TPEx OpenAPI / tpex_3insti_summary",
        retrieved_at=retrieved_at,
    )


def _payload_date(payload: object) -> date | None:
    if not isinstance(payload, dict) or payload.get("stat") != "OK":
        return None
    value = str(payload.get("date", "")).strip()
    if len(value) != 8 or not value.isdigit():
        return None
    try:
        return date(int(value[:4]), int(value[4:6]), int(value[6:]))
    except ValueError:
        return None


def _table_with_fields(
    payload: object,
    required_fields: tuple[str, ...],
) -> dict[str, list[object]] | None:
    if not isinstance(payload, dict):
        return None
    tables = payload.get("tables")
    if not isinstance(tables, list):
        return None
    for table in tables:
        if not isinstance(table, dict):
            continue
        fields = table.get("fields")
        rows = table.get("data")
        if not isinstance(fields, list) or not isinstance(rows, list):
            continue
        field_names = {str(field) for field in fields}
        if all(field in field_names for field in required_fields):
            return {"fields": fields, "data": rows}
    return None


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
        dealer = [float(value) for row in records if (value := row.get("dealer")) is not None]
        total = [float(value) for row in records if (value := row.get("total")) is not None]
        net_buy_days = sum(
            1
            for row in records
            if float(row.get("total") or 0.0) > 0
        )
        latest.update({
            "foreign_5d": sum(foreign) if foreign else None,
            "trust_5d": sum(trust) if trust else None,
            "dealer_5d": sum(dealer) if dealer else None,
            "total_5d": sum(total) if total else None,
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
        "total": _field_index(field_names, (_u("4e09", "5927", "6cd5", "4eba", "8cb7", "8ce3", "8d85", "80a1", "6578"),)),
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
        foreign = _number_value(_row_value(raw, indexes["foreign"]))
        trust = _number_value(_row_value(raw, indexes["trust"]))
        dealer = _number_value(_row_value(raw, indexes["dealer"]))
        total = _number_value(_row_value(raw, indexes["total"]))
        output[code] = {
            "foreign": foreign,
            "trust": trust,
            "dealer": dealer,
            "total": total if total is not None else _sum_available(foreign, trust, dealer),
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

def _tpex_institutional_rows(
    payload: object,
    *,
    before_or_on: date | None = None,
) -> dict[str, dict[str, object]]:
    if not isinstance(payload, list):
        return {}
    dated_rows: list[tuple[date, dict[str, object]]] = []
    for row in payload:
        if not isinstance(row, dict):
            continue
        as_of = _taiwan_date(_text(row, "Date"))
        if as_of is None or (before_or_on is not None and as_of > before_or_on):
            continue
        dated_rows.append((as_of, row))
    if not dated_rows:
        return {}

    latest_date = max(item[0] for item in dated_rows)
    output: dict[str, dict[str, object]] = {}
    for as_of, row in dated_rows:
        if as_of != latest_date:
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
            "total": _number(row, "TotalDifference"),
            "flow_days": 1,
            "as_of": as_of,
        }
        if output[code]["total"] is None:
            output[code]["total"] = _sum_available(
                output[code]["foreign"],
                output[code]["trust"],
                output[code]["dealer"],
            )
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


def _sum_available(*values: object) -> float | None:
    numbers = [float(value) for value in values if isinstance(value, (int, float))]
    if not numbers:
        return None
    return sum(numbers)


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