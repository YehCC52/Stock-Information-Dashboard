from __future__ import annotations

import re
import json
from dataclasses import dataclass
from dataclasses import replace
from datetime import date, datetime, time
from html import unescape
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

from .models import EconomicEvent, ManualMacroEvent

BLS_EMPSIT_URL = "https://www.bls.gov/schedule/news_release/empsit.htm"
BLS_SELECTED_RELEASES_URL = "https://www.bls.gov/schedule/{year}/home.htm"
FED_FOMC_URL = "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm?os=f"
FED_PRESS_RELEASE_BASE_URL = "https://www.federalreserve.gov/newsevents/pressreleases"
NEW_YORK_TZ = ZoneInfo("America/New_York")
BLS_EMPSIT_FALLBACK_SCHEDULE = (
    ("November 2025", "Dec. 16, 2025", "08:30 AM"),
    ("December 2025", "Jan. 09, 2026", "08:30 AM"),
    ("January 2026", "Feb. 11, 2026", "08:30 AM"),
    ("February 2026", "Mar. 06, 2026", "08:30 AM"),
    ("March 2026", "Apr. 03, 2026", "08:30 AM"),
    ("April 2026", "May 08, 2026", "08:30 AM"),
    ("May 2026", "Jun. 05, 2026", "08:30 AM"),
    ("June 2026", "Jul. 02, 2026", "08:30 AM"),
    ("July 2026", "Aug. 07, 2026", "08:30 AM"),
    ("August 2026", "Sep. 04, 2026", "08:30 AM"),
    ("September 2026", "Oct. 02, 2026", "08:30 AM"),
    ("October 2026", "Nov. 06, 2026", "08:30 AM"),
    ("November 2026", "Dec. 04, 2026", "08:30 AM"),
)
FOMC_FALLBACK_SCHEDULE = (
    ("Jan. 28, 2026", False),
    ("Mar. 18, 2026", True),
    ("Apr. 29, 2026", False),
    ("Jun. 17, 2026", True),
    ("Jul. 29, 2026", False),
    ("Sep. 16, 2026", True),
    ("Oct. 28, 2026", False),
    ("Dec. 09, 2026", True),
)
CORE_BLS_RELEASES = {
    "Employment Situation": ("Nonfarm Payrolls / Employment Situation", "jobs", "high"),
    "Consumer Price Index": ("CPI / Consumer Price Index", "inflation", "high"),
    "Producer Price Index": ("PPI / Producer Price Index", "inflation", "medium"),
}
CPI_FALLBACK_SCHEDULE = (
    ("December 2025", "Jan. 13, 2026", "08:30 AM"),
    ("January 2026", "Feb. 13, 2026", "08:30 AM"),
    ("February 2026", "Mar. 11, 2026", "08:30 AM"),
    ("March 2026", "Apr. 10, 2026", "08:30 AM"),
    ("April 2026", "May. 12, 2026", "08:30 AM"),
    ("May 2026", "Jun. 10, 2026", "08:30 AM"),
    ("June 2026", "Jul. 14, 2026", "08:30 AM"),
    ("July 2026", "Aug. 12, 2026", "08:30 AM"),
    ("August 2026", "Sep. 11, 2026", "08:30 AM"),
    ("September 2026", "Oct. 14, 2026", "08:30 AM"),
    ("October 2026", "Nov. 10, 2026", "08:30 AM"),
)

MONTHS = {
    "January": 1,
    "February": 2,
    "March": 3,
    "April": 4,
    "May": 5,
    "June": 6,
    "July": 7,
    "August": 8,
    "September": 9,
    "October": 10,
    "November": 11,
    "December": 12,
}
MONTH_ABBR = {
    "Jan": 1,
    "Feb": 2,
    "Mar": 3,
    "Apr": 4,
    "May": 5,
    "Jun": 6,
    "Jul": 7,
    "Aug": 8,
    "Sep": 9,
    "Oct": 10,
    "Nov": 11,
    "Dec": 12,
}


@dataclass(frozen=True)
class MacroFetchResult:
    events: list[EconomicEvent]
    warnings: list[str]


class OfficialMacroCalendarProvider:
    def __init__(self, timeout_seconds: int = 20) -> None:
        self.timeout_seconds = timeout_seconds

    def fetch(
        self,
        *,
        report_date: date,
        timezone_name: str,
        days_back: int = 1,
        days_ahead: int,
        manual_events: list[ManualMacroEvent] | None = None,
        cache_path: str | Path | None = None,
    ) -> MacroFetchResult:
        warnings: list[str] = []
        events: list[EconomicEvent] = []
        if manual_events:
            events.extend(manual_macro_events(manual_events))

        bls_events: list[EconomicEvent] = []
        try:
            html = self._get(BLS_SELECTED_RELEASES_URL.format(year=report_date.year))
            bls_events = parse_bls_selected_releases(html, timezone_name, year=report_date.year)
        except Exception:
            try:
                html = self._get(BLS_EMPSIT_URL)
                bls_events = parse_bls_employment_situation(html, timezone_name)
            except Exception:
                bls_events = fallback_core_bls_calendar(timezone_name)
        if bls_events:
            events.extend(bls_events)
        else:
            warnings.append("Macro calendar BLS sources returned no usable core events; add manual macro events for CPI/NFP coverage.")

        try:
            html = self._get(FED_FOMC_URL)
            events.extend(parse_fomc_calendar(html, timezone_name, years=[report_date.year, report_date.year + 1]))
        except Exception as exc:
            fallback_events = fallback_fomc_calendar(timezone_name)
            fallback_window = filter_event_window(fallback_events, report_date, days_back, days_ahead, timezone_name)
            if fallback_window:
                events.extend(fallback_events)
            elif not fallback_events:
                warnings.append(f"Macro calendar fetch failed for FOMC calendar: {exc}")

        events = self._enrich_recent_fomc_events(
            events,
            report_date=report_date,
            timezone_name=timezone_name,
            days_back=days_back,
        )

        events = dedupe_events(events)
        filtered = filter_event_window(events, report_date, days_back, days_ahead, timezone_name)
        if not filtered and cache_path:
            cached = load_cached_macro_events(cache_path)
            cached_filtered = filter_event_window(cached, report_date, days_back, days_ahead, timezone_name)
            if cached_filtered:
                filtered = cached_filtered
                warnings = [w for w in warnings if "Macro calendar fetch failed" not in w]
                warnings.append("Macro calendar using cached events because live sources returned no events.")
        elif filtered and cache_path:
            save_cached_macro_events(cache_path, filtered)

        return MacroFetchResult(events=filtered, warnings=warnings)

    def _get(self, url: str) -> str:
        response = requests.get(
            url,
            timeout=self.timeout_seconds,
            headers={"User-Agent": "stock-daily-research/0.1 (+personal research calendar)"},
        )
        response.raise_for_status()
        return response.text

    def _enrich_recent_fomc_events(
        self,
        events: list[EconomicEvent],
        *,
        report_date: date,
        timezone_name: str,
        days_back: int,
    ) -> list[EconomicEvent]:
        tz = ZoneInfo(timezone_name)
        start = report_date.toordinal() - days_back
        result: list[EconomicEvent] = []
        for event in events:
            local_date = event.event_datetime.astimezone(tz).date()
            if event.category != "rates" or not (start <= local_date.toordinal() <= report_date.toordinal()):
                result.append(event)
                continue

            meeting_date = parse_source_date(event.source_time_label) or local_date
            statement_url = build_fomc_statement_url(meeting_date)
            try:
                statement_html = self._get(statement_url)
            except Exception:
                result.append(event)
                continue

            notes = parse_fomc_statement_highlights(statement_html)
            result.append(
                replace(
                    event,
                    source="Federal Reserve FOMC Statement",
                    source_url=statement_url,
                    notes=notes or event.notes,
                )
            )
        return result


def parse_bls_employment_situation(html: str, timezone_name: str) -> list[EconomicEvent]:
    text = normalize_html_text(html)
    pattern = re.compile(
        r"([A-Z][a-z]+ \d{4})\s+([A-Z][a-z]{2,}\.? \d{2}, \d{4})\s+(\d{2}:\d{2} [AP]M)"
    )
    events: list[EconomicEvent] = []
    for reference_month, release_date_text, release_time_text in pattern.findall(text):
        release_date = parse_bls_date(release_date_text)
        release_time = datetime.strptime(release_time_text, "%I:%M %p").time()
        local_dt = convert_from_new_york(release_date, release_time, timezone_name)
        events.append(
            EconomicEvent(
                name="Nonfarm Payrolls / Employment Situation",
                category="jobs",
                event_datetime=local_dt,
                source="BLS",
                source_url=BLS_EMPSIT_URL,
                importance="high",
                notes=f"Reference month: {reference_month}",
                source_time_label=f"{release_date.isoformat()} {release_time_text} ET",
            )
        )
    return events


def parse_bls_selected_releases(html: str, timezone_name: str, *, year: int) -> list[EconomicEvent]:
    text = normalize_html_text(html)
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    events: list[EconomicEvent] = []
    for idx, line in enumerate(lines):
        event_date = parse_bls_long_date(line)
        if event_date is None or event_date.year != year:
            continue
        if idx + 2 >= len(lines):
            continue
        release_time = parse_bls_time(lines[idx + 1])
        if release_time is None:
            continue
        release_name = lines[idx + 2]
        matched = next((name for name in CORE_BLS_RELEASES if release_name.startswith(name)), None)
        if not matched:
            continue
        normalized_name, category, importance = CORE_BLS_RELEASES[matched]
        local_dt = convert_from_new_york(event_date, release_time, timezone_name)
        reference = release_name.replace(matched, "").strip()
        notes = f"Reference period: {reference}" if reference else "Official BLS selected release calendar."
        events.append(
            EconomicEvent(
                name=normalized_name,
                category=category,
                event_datetime=local_dt,
                source="BLS selected releases",
                source_url=BLS_SELECTED_RELEASES_URL.format(year=year),
                importance=importance,
                notes=notes,
                source_time_label=f"{event_date.isoformat()} {lines[idx + 1]} ET",
            )
        )
    return events


def fallback_bls_employment_situation(timezone_name: str) -> list[EconomicEvent]:
    events: list[EconomicEvent] = []
    for reference_month, release_date_text, release_time_text in BLS_EMPSIT_FALLBACK_SCHEDULE:
        release_date = parse_bls_date(release_date_text)
        release_time = datetime.strptime(release_time_text, "%I:%M %p").time()
        local_dt = convert_from_new_york(release_date, release_time, timezone_name)
        events.append(
            EconomicEvent(
                name="Nonfarm Payrolls / Employment Situation",
                category="jobs",
                event_datetime=local_dt,
                source="BLS",
                source_url=BLS_EMPSIT_URL,
                importance="high",
                notes=f"Reference month: {reference_month}. Official 2026 BLS schedule fallback.",
                source_time_label=f"{release_date.isoformat()} {release_time_text} ET",
            )
        )
    return events


def fallback_core_bls_calendar(timezone_name: str) -> list[EconomicEvent]:
    events = fallback_bls_employment_situation(timezone_name)
    for reference_month, release_date_text, release_time_text in CPI_FALLBACK_SCHEDULE:
        release_date = parse_bls_date(release_date_text)
        release_time = datetime.strptime(release_time_text, "%I:%M %p").time()
        local_dt = convert_from_new_york(release_date, release_time, timezone_name)
        events.append(
            EconomicEvent(
                name="CPI / Consumer Price Index",
                category="inflation",
                event_datetime=local_dt,
                source="BLS fallback",
                source_url=BLS_SELECTED_RELEASES_URL.format(year=release_date.year),
                importance="high",
                notes=f"Reference month: {reference_month}. Built-in 2026 BLS selected-releases fallback.",
                source_time_label=f"{release_date.isoformat()} {release_time_text} ET",
            )
        )
    return events


def fallback_fomc_calendar(timezone_name: str) -> list[EconomicEvent]:
    events: list[EconomicEvent] = []
    for release_date_text, has_sep in FOMC_FALLBACK_SCHEDULE:
        meeting_date = parse_bls_date(release_date_text)
        local_dt = convert_from_new_york(meeting_date, time(14, 0), timezone_name)
        notes = "Built-in 2026 FOMC fallback; verify official Fed calendar when possible."
        if has_sep:
            notes += " Meeting associated with Summary of Economic Projections."
        events.append(
            EconomicEvent(
                name="FOMC Rate Decision",
                category="rates",
                event_datetime=local_dt,
                source="Federal Reserve fallback",
                source_url=FED_FOMC_URL,
                importance="high",
                notes=notes,
                source_time_label=f"{meeting_date.isoformat()} 02:00 PM ET",
            )
        )
    return events


def manual_macro_events(manual_events: list[ManualMacroEvent]) -> list[EconomicEvent]:
    return [
        EconomicEvent(
            name=event.name,
            category=event.category,
            event_datetime=event.event_datetime,
            source=event.source,
            source_url=event.source_url,
            importance=event.importance,
            notes=event.notes,
            source_time_label=event.event_datetime.isoformat(),
        )
        for event in manual_events
    ]


def save_cached_macro_events(path: str | Path, events: list[EconomicEvent]) -> None:
    cache_path = Path(path)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    payload = [
        {
            "name": event.name,
            "category": event.category,
            "event_datetime": event.event_datetime.isoformat(),
            "source": event.source,
            "source_url": event.source_url,
            "importance": event.importance,
            "notes": event.notes,
            "source_time_label": event.source_time_label,
        }
        for event in events
    ]
    cache_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def load_cached_macro_events(path: str | Path) -> list[EconomicEvent]:
    cache_path = Path(path)
    if not cache_path.exists():
        return []
    try:
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
    except Exception:
        return []
    events: list[EconomicEvent] = []
    for row in (payload if isinstance(payload, list) else []):
        try:
            events.append(
                EconomicEvent(
                    name=str(row["name"]),
                    category=str(row["category"]),
                    event_datetime=datetime.fromisoformat(str(row["event_datetime"])),
                    source=str(row.get("source", "cache")),
                    source_url=str(row.get("source_url", "")),
                    importance=str(row.get("importance", "high")),
                    notes=row.get("notes"),
                    source_time_label=row.get("source_time_label"),
                )
            )
        except Exception:
            continue
    return events


def parse_fomc_calendar(html: str, timezone_name: str, years: list[int]) -> list[EconomicEvent]:
    text = normalize_html_text(html)
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    events: list[EconomicEvent] = []

    for year in years:
        section = slice_fomc_year_section(lines, year)
        index = 0
        while index < len(section):
            month_label = section[index]
            if not is_month_label(month_label):
                index += 1
                continue
            date_line = next_date_line(section, index + 1)
            if not date_line:
                index += 1
                continue
            meeting_date, has_sep = parse_fomc_meeting_end_date(year, month_label, date_line)
            local_dt = convert_from_new_york(meeting_date, time(14, 0), timezone_name)
            notes = "Rate decision / statement expected at 2:00 PM ET; press conference normally 2:30 PM ET."
            if has_sep:
                notes += " Meeting associated with Summary of Economic Projections."
            events.append(
                EconomicEvent(
                    name="FOMC Rate Decision",
                    category="rates",
                    event_datetime=local_dt,
                    source="Federal Reserve",
                    source_url=FED_FOMC_URL,
                    importance="high",
                    notes=notes,
                    source_time_label=f"{meeting_date.isoformat()} 02:00 PM ET",
                )
            )
            index += 2

    return events


def parse_fomc_statement_highlights(html: str) -> str:
    text = normalize_html_text(html)
    compact = " ".join(text.split())
    sentences = split_sentences(compact)

    highlights: list[str] = []
    for pattern in (
        r"decided to .*?target range for the federal funds rate.*",
        r"Inflation .*",
        r"Job gains .*",
        r"Voting against .*",
    ):
        sentence = first_matching_sentence(sentences, pattern)
        if sentence:
            highlights.append(clean_statement_sentence(sentence))

    if not highlights:
        return ""
    return "Official statement: " + " | ".join(highlights[:4])


def split_sentences(text: str) -> list[str]:
    return [part.strip() for part in re.split(r"(?<=[.!?])\s+", text) if part.strip()]


def first_matching_sentence(sentences: list[str], pattern: str) -> str | None:
    regex = re.compile(pattern, re.I)
    for sentence in sentences:
        if regex.search(sentence):
            return sentence
    return None


def clean_statement_sentence(sentence: str, max_length: int = 180) -> str:
    sentence = re.sub(r"\s+", " ", sentence).strip()
    sentence = normalize_statement_punctuation(sentence)
    if len(sentence) <= max_length:
        return sentence
    return sentence[: max_length - 3].rstrip() + "..."


def normalize_statement_punctuation(value: str) -> str:
    return (
        value.replace("\u00e2\u0080\u0090", "-")
        .replace("\u00e2\u0080\u0091", "-")
        .replace("\u00e2\u0080\u0092", "-")
        .replace("\u00e2\u0080\u0093", "-")
        .replace("\u00e2\u0080\u0094", "-")
        .replace("\u00e2\u0080\u0098", "'")
        .replace("\u00e2\u0080\u0099", "'")
        .replace("\u00e2\u0080\u009c", '"')
        .replace("\u00e2\u0080\u009d", '"')
        .replace("\u2011", "-")
        .replace("\u2010", "-")
        .replace("\u2012", "-")
        .replace("\u2013", "-")
        .replace("\u2014", "-")
        .replace("\u2212", "-")
        .replace("\u2018", "'")
        .replace("\u2019", "'")
        .replace("\u201c", '"')
        .replace("\u201d", '"')
        .replace("\xa0", " ")
    )


def filter_upcoming_events(
    events: list[EconomicEvent],
    report_date: date,
    days_ahead: int,
    timezone_name: str,
) -> list[EconomicEvent]:
    return filter_event_window(events, report_date, 0, days_ahead, timezone_name)


def filter_event_window(
    events: list[EconomicEvent],
    report_date: date,
    days_back: int,
    days_ahead: int,
    timezone_name: str,
) -> list[EconomicEvent]:
    tz = ZoneInfo(timezone_name)
    start_ordinal = report_date.toordinal() - days_back
    max_date = report_date.toordinal() + days_ahead
    result = [
        event
        for event in events
        if start_ordinal <= event.event_datetime.astimezone(tz).date().toordinal() <= max_date
    ]
    return sorted(result, key=lambda event: event.event_datetime)


def dedupe_events(events: list[EconomicEvent]) -> list[EconomicEvent]:
    by_key: dict[tuple[str, datetime], EconomicEvent] = {}
    for event in events:
        key = (event.name, event.event_datetime)
        existing = by_key.get(key)
        if existing is None or source_priority(event.source) > source_priority(existing.source):
            by_key[key] = event
    return sorted(by_key.values(), key=lambda event: event.event_datetime)


def source_priority(source: str) -> int:
    if "selected releases" in source:
        return 4
    if source in {"BLS", "Federal Reserve", "Federal Reserve FOMC Statement"}:
        return 3
    if source == "manual":
        return 5
    if "fallback" in source:
        return 2
    if "cache" in source:
        return 1
    return 0


def normalize_html_text(html: str) -> str:
    text = re.sub(r"<[^>]+>", "\n", html)
    text = unescape(text)
    text = re.sub(r"[\r\t ]+", " ", text)
    return re.sub(r"\n+", "\n", text)


def parse_bls_date(value: str) -> date:
    cleaned = value.replace(".", "")
    for fmt in ("%b %d, %Y", "%B %d, %Y"):
        try:
            return datetime.strptime(cleaned, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"Could not parse BLS date: {value}")


def parse_bls_long_date(value: str) -> date | None:
    try:
        return datetime.strptime(value.strip(), "%A, %B %d, %Y").date()
    except ValueError:
        return None


def parse_bls_time(value: str) -> time | None:
    try:
        return datetime.strptime(value.strip(), "%I:%M %p").time()
    except ValueError:
        return None


def convert_from_new_york(event_date: date, event_time: time, timezone_name: str) -> datetime:
    source_dt = datetime.combine(event_date, event_time, tzinfo=NEW_YORK_TZ)
    return source_dt.astimezone(ZoneInfo(timezone_name))


def build_fomc_statement_url(meeting_date: date) -> str:
    return f"{FED_PRESS_RELEASE_BASE_URL}/monetary{meeting_date.strftime('%Y%m%d')}a.htm"


def parse_source_date(value: str | None) -> date | None:
    if not value:
        return None
    match = re.search(r"\d{4}-\d{2}-\d{2}", value)
    if not match:
        return None
    return date.fromisoformat(match.group(0))


def slice_fomc_year_section(lines: list[str], year: int) -> list[str]:
    heading = f"{year} FOMC Meetings"
    try:
        start = lines.index(heading) + 1
    except ValueError:
        return []
    end = len(lines)
    for idx in range(start, len(lines)):
        if re.fullmatch(r"\d{4} FOMC Meetings", lines[idx]):
            end = idx
            break
    return lines[start:end]


def is_month_label(value: str) -> bool:
    parts = value.split("/")
    return all(part in MONTHS or part in MONTH_ABBR for part in parts)


def next_date_line(lines: list[str], start: int) -> str | None:
    for line in lines[start : start + 8]:
        if re.fullmatch(r"\d{1,2}(?:-\d{1,2})?\*?", line):
            return line
    return None


def parse_fomc_meeting_end_date(year: int, month_label: str, date_line: str) -> tuple[date, bool]:
    has_sep = date_line.endswith("*")
    clean = date_line.rstrip("*")
    month_parts = month_label.split("/")
    start_month = month_number(month_parts[0])
    end_month = start_month

    if "-" in clean:
        start_day_text, end_day_text = clean.split("-", 1)
        start_day = int(start_day_text)
        end_day = int(end_day_text)
        if end_day < start_day:
            if len(month_parts) > 1:
                end_month = month_number(month_parts[1])
            else:
                end_month = start_month + 1
        return date(year, end_month, end_day), has_sep

    return date(year, start_month, int(clean)), has_sep


def month_number(value: str) -> int:
    if value in MONTHS:
        return MONTHS[value]
    return MONTH_ABBR[value]
