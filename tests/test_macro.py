from datetime import date
from datetime import datetime
from datetime import timezone

from stock_daily_research.macro import (
    BLS_EMPSIT_URL,
    BLS_SELECTED_RELEASES_URL,
    FED_FOMC_URL,
    OfficialMacroCalendarProvider,
    build_fomc_statement_url,
    filter_event_window,
    filter_upcoming_events,
    fallback_bls_employment_situation,
    fallback_core_bls_calendar,
    fallback_fomc_calendar,
    load_cached_macro_events,
    manual_macro_events,
    parse_bls_employment_situation,
    parse_bls_selected_releases,
    parse_fomc_calendar,
    parse_fomc_statement_highlights,
    save_cached_macro_events,
)
from stock_daily_research.models import ManualMacroEvent


def test_parse_bls_employment_situation_converts_to_report_timezone() -> None:
    html = """
    Reference Month Release Date Release Time
    April 2026 May 08, 2026 08:30 AM
    """

    events = parse_bls_employment_situation(html, "Asia/Taipei")

    assert len(events) == 1
    event = events[0]
    assert event.name == "Nonfarm Payrolls / Employment Situation"
    assert event.category == "jobs"
    assert event.event_datetime.strftime("%Y-%m-%d %H:%M") == "2026-05-08 20:30"
    assert "April 2026" in event.notes


def test_parse_bls_selected_releases_keeps_core_macro_events() -> None:
    html = """
    Tuesday, May 12, 2026
    08:30 AM
    Employment Situation for April 2026
    Tuesday, May 12, 2026
    08:30 AM
    Consumer Price Index for April 2026
    Wednesday, May 13, 2026
    10:00 AM
    Minor Release for April 2026
    Thursday, May 14, 2026
    08:30 AM
    Producer Price Index for April 2026
    """

    events = parse_bls_selected_releases(html, "Asia/Taipei", year=2026)

    assert [event.name for event in events] == [
        "Nonfarm Payrolls / Employment Situation",
        "CPI / Consumer Price Index",
        "PPI / Producer Price Index",
    ]
    assert events[1].event_datetime.strftime("%Y-%m-%d %H:%M") == "2026-05-12 20:30"


def test_parse_fomc_calendar_uses_decision_day_and_time() -> None:
    html = """
    <h4>2026 FOMC Meetings</h4>
    April
    28-29
    June
    16-17*
    <h4>2025 FOMC Meetings</h4>
    """

    events = parse_fomc_calendar(html, "Asia/Taipei", years=[2026])

    assert len(events) == 2
    assert events[0].name == "FOMC Rate Decision"
    assert events[0].event_datetime.strftime("%Y-%m-%d %H:%M") == "2026-04-30 02:00"
    assert "2:00 PM ET" in events[0].notes
    assert "Summary of Economic Projections" in events[1].notes


def test_filter_upcoming_events_keeps_only_configured_window() -> None:
    bls_events = parse_bls_employment_situation(
        """
        April 2026 May 08, 2026 08:30 AM
        May 2026 Jun. 05, 2026 08:30 AM
        """,
        "Asia/Taipei",
    )

    events = filter_upcoming_events(
        bls_events,
        report_date=date(2026, 4, 29),
        days_ahead=14,
        timezone_name="Asia/Taipei",
    )

    assert [event.event_datetime.date().isoformat() for event in events] == ["2026-05-08"]


def test_filter_event_window_keeps_recent_past_and_future_events() -> None:
    events = parse_bls_employment_situation(
        """
        March 2026 Apr. 03, 2026 08:30 AM
        April 2026 May 08, 2026 08:30 AM
        May 2026 Jun. 05, 2026 08:30 AM
        """,
        "Asia/Taipei",
    )

    filtered = filter_event_window(
        events,
        report_date=date(2026, 5, 9),
        days_back=1,
        days_ahead=14,
        timezone_name="Asia/Taipei",
    )

    assert [event.event_datetime.date().isoformat() for event in filtered] == ["2026-05-08"]


def test_parse_fomc_statement_highlights_extracts_action_and_risks() -> None:
    html = """
    <p>Job gains have remained low, on average, and the unemployment rate has been little changed.</p>
    <p>Inflation is elevated.</p>
    <p>The Committee decided to maintain the target range for the federal funds rate at 3-1/2 to 3-3/4 percent.</p>
    <p>Voting against this action were two members.</p>
    """

    notes = parse_fomc_statement_highlights(html)

    assert notes.startswith("Official statement:")
    assert "maintain the target range" in notes
    assert "Inflation is elevated" in notes
    assert "Voting against" in notes


def test_fallback_bls_employment_situation_keeps_official_2026_schedule() -> None:
    events = fallback_bls_employment_situation("Asia/Taipei")

    april_release = next(event for event in events if "April 2026" in (event.notes or ""))
    assert april_release.event_datetime.strftime("%Y-%m-%d %H:%M") == "2026-05-08 20:30"
    assert april_release.source_url == BLS_EMPSIT_URL


def test_fallback_core_bls_calendar_includes_cpi() -> None:
    events = fallback_core_bls_calendar("Asia/Taipei")

    cpi = next(event for event in events if event.name == "CPI / Consumer Price Index" and "April 2026" in (event.notes or ""))
    assert cpi.event_datetime.strftime("%Y-%m-%d %H:%M") == "2026-05-12 20:30"


def test_fallback_fomc_calendar_keeps_2026_schedule() -> None:
    events = fallback_fomc_calendar("Asia/Taipei")

    april = next(event for event in events if event.source_time_label.startswith("2026-04-29"))
    assert april.event_datetime.strftime("%Y-%m-%d %H:%M") == "2026-04-30 02:00"
    assert april.source_url == FED_FOMC_URL


def test_manual_macro_events_convert_to_economic_events() -> None:
    events = manual_macro_events([
        ManualMacroEvent(
            name="CPI Release",
            category="inflation",
            event_datetime=datetime(2026, 5, 12, 20, 30, tzinfo=timezone.utc),
            notes="manual table",
        )
    ])

    assert events[0].name == "CPI Release"
    assert events[0].category == "inflation"
    assert events[0].source == "manual"


def test_provider_uses_bls_fallback_without_noisy_warning(monkeypatch) -> None:
    provider = OfficialMacroCalendarProvider()

    def fake_get(url: str) -> str:
        if url == BLS_SELECTED_RELEASES_URL.format(year=2026):
            raise RuntimeError("403 blocked")
        if url == BLS_EMPSIT_URL:
            raise RuntimeError("403 blocked")
        if url == FED_FOMC_URL:
            return """
            <h4>2026 FOMC Meetings</h4>
            April
            28-29
            <h4>2027 FOMC Meetings</h4>
            """
        raise AssertionError(f"Unexpected URL: {url}")

    monkeypatch.setattr(provider, "_get", fake_get)

    result = provider.fetch(
        report_date=date(2026, 4, 29),
        days_ahead=14,
        timezone_name="Asia/Taipei",
    )

    assert result.warnings == []
    assert "Macro calendar fetch failed" not in " ".join(result.warnings)
    assert "FOMC Rate Decision" in [event.name for event in result.events]
    assert "Nonfarm Payrolls / Employment Situation" in [event.name for event in result.events]


def test_provider_uses_fomc_fallback_when_fed_fetch_fails(monkeypatch) -> None:
    provider = OfficialMacroCalendarProvider()

    def fake_get(url: str) -> str:
        if url == BLS_SELECTED_RELEASES_URL.format(year=2026):
            raise RuntimeError("selected blocked")
        if url == BLS_EMPSIT_URL:
            return "April 2026 May 08, 2026 08:30 AM"
        if url == FED_FOMC_URL:
            raise RuntimeError("fed blocked")
        raise AssertionError(f"Unexpected URL: {url}")

    monkeypatch.setattr(provider, "_get", fake_get)

    result = provider.fetch(
        report_date=date(2026, 4, 29),
        days_ahead=2,
        timezone_name="Asia/Taipei",
    )

    assert result.warnings == []
    assert any(event.source == "Federal Reserve fallback" for event in result.events)


def test_macro_cache_roundtrip_and_provider_uses_cache_when_empty(tmp_path, monkeypatch) -> None:
    cached_event = manual_macro_events([
        ManualMacroEvent(
            name="CPI Release",
            category="inflation",
            event_datetime=datetime(2026, 5, 12, 20, 30, tzinfo=timezone.utc),
        )
    ])[0]
    cache_path = tmp_path / "macro_cache.json"
    save_cached_macro_events(cache_path, [cached_event])
    assert load_cached_macro_events(cache_path)[0].name == "CPI Release"

    provider = OfficialMacroCalendarProvider()
    monkeypatch.setattr(provider, "_get", lambda _url: (_ for _ in ()).throw(RuntimeError("offline")))
    monkeypatch.setattr("stock_daily_research.macro.fallback_bls_employment_situation", lambda _tz: [])
    monkeypatch.setattr("stock_daily_research.macro.fallback_core_bls_calendar", lambda _tz: [])
    monkeypatch.setattr("stock_daily_research.macro.fallback_fomc_calendar", lambda _tz: [])

    result = provider.fetch(
        report_date=date(2026, 5, 12),
        days_ahead=1,
        timezone_name="Asia/Taipei",
        cache_path=cache_path,
    )

    assert result.events[0].name == "CPI Release"
    assert any("cached events" in warning for warning in result.warnings)


def test_provider_enriches_recent_fomc_with_official_statement(monkeypatch) -> None:
    provider = OfficialMacroCalendarProvider()
    statement_url = build_fomc_statement_url(date(2026, 4, 29))

    def fake_get(url: str) -> str:
        if url == BLS_EMPSIT_URL:
            raise RuntimeError("403 blocked")
        if url == FED_FOMC_URL:
            return """
            <h4>2026 FOMC Meetings</h4>
            April
            28-29
            <h4>2027 FOMC Meetings</h4>
            """
        if url == statement_url:
            return """
            <p>Inflation is elevated.</p>
            <p>The Committee decided to maintain the target range for the federal funds rate at 3-1/2 to 3-3/4 percent.</p>
            """
        raise AssertionError(f"Unexpected URL: {url}")

    monkeypatch.setattr(provider, "_get", fake_get)

    result = provider.fetch(
        report_date=date(2026, 4, 30),
        days_back=1,
        days_ahead=14,
        timezone_name="Asia/Taipei",
    )

    fomc = next(event for event in result.events if event.name == "FOMC Rate Decision")
    assert fomc.source == "Federal Reserve FOMC Statement"
    assert fomc.source_url == statement_url
    assert fomc.notes is not None
    assert "maintain the target range" in fomc.notes
