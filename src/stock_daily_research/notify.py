from __future__ import annotations

import os
import time
from dataclasses import dataclass
from datetime import date, datetime, time as datetime_time, timedelta, timezone
from zoneinfo import ZoneInfo

import requests

from .models import DailyReport, TickerReport
from .news import EVENT_LABELS
from .valuation import format_metric_value

TELEGRAM_MAX_MESSAGE_LENGTH = 4096


@dataclass(frozen=True)
class TelegramNotifier:
    bot_token: str
    chat_id: str
    timeout_seconds: int = 20
    disable_web_page_preview: bool = True
    max_retries: int = 2

    def send_message(self, text: str) -> None:
        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": truncate_for_telegram(text),
            "disable_web_page_preview": self.disable_web_page_preview,
        }
        last_exc: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                response = requests.post(url, json=payload, timeout=self.timeout_seconds)
                response.raise_for_status()
                body = response.json()
                if not body.get("ok"):
                    raise RuntimeError(body.get("description", "Unknown Telegram API error"))
                return
            except (requests.RequestException, RuntimeError) as exc:
                last_exc = exc
                if attempt < self.max_retries:
                    time.sleep(2 ** attempt)
        assert last_exc is not None
        # Redact the bot token: request exceptions embed the full URL, which the
        # caller logs into report warnings.
        raise RuntimeError(self._redact(str(last_exc))) from None

    def _redact(self, message: str) -> str:
        if self.bot_token and self.bot_token in message:
            return message.replace(self.bot_token, "***")
        return message


def build_telegram_notifier(disable_web_page_preview: bool = True) -> TelegramNotifier | None:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        return None
    return TelegramNotifier(
        bot_token=token,
        chat_id=chat_id,
        disable_web_page_preview=disable_web_page_preview,
    )


def build_daily_summary(report: DailyReport, report_path: str | None = None) -> str:
    macro_items = _macro_focus(report)
    earnings_items = _earnings_soon(report)
    overnight_news = _us_overnight_news(report)
    news_items = _important_news(report)
    valuation_alerts = _valuation_alerts(report)
    warning_items = _warning_items(report)
    tickers_with_news = sum(1 for item in report.ticker_reports if item.articles)
    high_news_count = len(news_items)

    lines = [
        f"Daily Stock Brief - {report.report_date.isoformat()}",
        f"{len(report.ticker_reports)} tickers | {tickers_with_news} with news | {len(earnings_items)} earnings <=7d | {high_news_count} high-priority news | {len(macro_items)} macro",
        "",
    ]

    if report.market_sentiment:
        lines.append("Market sentiment")
        lines.append(f"- {report.market_sentiment.score}/100 {report.market_sentiment.label} ({report.market_sentiment.source})")
        lines.append("")

    if macro_items:
        lines.append("Macro")
        for event in macro_items[:3]:
            when = _relative_datetime(event.event_datetime, report.report_date)
            note = f" - {_compact_text(event.notes, 170)}" if event.notes else ""
            lines.append(f"- {when}: {event.name} ({event.source}){note}")
        if len(macro_items) > 3:
            lines.append(f"- +{len(macro_items) - 3} more in report")
        lines.append("")

    if overnight_news:
        lines.append("US overnight")
        for item, article in overnight_news[:5]:
            event_label = EVENT_LABELS.get(str(article.event_type), str(article.event_type).replace("_", " ").title())
            title = _compact_text(article.title, 115)
            timestamp = _article_time_label(article)
            lines.append(f"- {item.ticker.symbol}: {title} ({article.source}, {event_label}{timestamp})")
        if len(overnight_news) > 5:
            lines.append(f"- +{len(overnight_news) - 5} more in report")
        lines.append("")

    if earnings_items:
        lines.append("Earnings <=7d")
        for item in earnings_items[:5]:
            assert item.earnings is not None
            earnings_date = item.earnings.earnings_date
            lines.append(f"- {item.ticker.symbol}: {earnings_date.isoformat()} ({_days_until(earnings_date, report.report_date)})")
        if len(earnings_items) > 5:
            lines.append(f"- +{len(earnings_items) - 5} more in report")
        lines.append("")

    if news_items:
        lines.append("Top news")
        for item, article in news_items[:5]:
            event_label = EVENT_LABELS.get(str(article.event_type), str(article.event_type).replace("_", " ").title())
            title = _compact_text(article.title, 115)
            lines.append(f"- {item.ticker.symbol}: {title} ({article.source}, {event_label})")
        if len(news_items) > 5:
            lines.append(f"- +{len(news_items) - 5} more in report")
        lines.append("")

    if valuation_alerts:
        lines.append("Valuation / data flags")
        for alert in valuation_alerts[:5]:
            lines.append(f"- {alert}")
        if len(valuation_alerts) > 5:
            lines.append(f"- +{len(valuation_alerts) - 5} more in report")
        lines.append("")

    data_quality = _data_quality_summary(report, warning_items)
    if data_quality:
        lines.append("Data quality")
        lines.append(f"- {data_quality}")
        lines.append("")

    if not macro_items and not earnings_items and not news_items and not valuation_alerts:
        lines.append("No urgent market-moving items found. Full report is ready.")
        lines.append("")

    if report_path:
        lines.append(f"Report: {report_path}")

    return truncate_for_telegram("\n".join(lines).strip())


def _macro_focus(report: DailyReport, days: int = 14) -> list[object]:
    events = []
    for event in report.economic_events:
        delta = (event.event_datetime.date() - report.report_date).days
        if -1 <= delta <= days:
            events.append(event)
    return sorted(events, key=lambda event: event.event_datetime)


def _earnings_soon(report: DailyReport, days: int = 7) -> list[TickerReport]:
    result: list[TickerReport] = []
    for item in report.ticker_reports:
        if not item.earnings or not item.earnings.earnings_date:
            continue
        delta = (item.earnings.earnings_date - report.report_date).days
        if 0 <= delta <= days:
            result.append(item)
    return sorted(result, key=lambda item: item.earnings.earnings_date if item.earnings else date.max)


def _important_news(report: DailyReport) -> list[tuple[TickerReport, object]]:
    pairs = [
        (item, article)
        for item in report.ticker_reports
        for article in item.articles
        if article.importance_score >= 0.8
    ]
    return sorted(pairs, key=lambda pair: pair[1].importance_score, reverse=True)


def _us_overnight_news(report: DailyReport) -> list[tuple[TickerReport, object]]:
    start = latest_us_regular_close_before(report.generated_at)
    end = ensure_aware_utc(report.generated_at)
    pairs = [
        (item, article)
        for item in report.ticker_reports
        for article in item.articles
        if article.published_at
        and article.importance_score >= 0.8
        and start <= ensure_aware_utc(article.published_at) <= end
    ]
    return sorted(
        pairs,
        key=lambda pair: (pair[1].importance_score, ensure_aware_utc(pair[1].published_at)),
        reverse=True,
    )


def latest_us_regular_close_before(value: datetime) -> datetime:
    ny_tz = ZoneInfo("America/New_York")
    current = ensure_aware_utc(value).astimezone(ny_tz)
    close = datetime.combine(current.date(), datetime_time(16, 0), tzinfo=ny_tz)
    if current < close:
        close -= timedelta(days=1)
    while close.weekday() >= 5:
        close -= timedelta(days=1)
    return close.astimezone(timezone.utc)


def ensure_aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _valuation_alerts(report: DailyReport) -> list[str]:
    alerts: list[str] = []
    for item in report.ticker_reports:
        fallback_warning = next(
            (warning for warning in item.warnings if "Valuation fallback used" in warning),
            None,
        )
        if fallback_warning:
            alerts.append(f"{item.ticker.symbol}: using last valuation snapshot ({item.valuation.as_of_date.isoformat() if item.valuation else 'date unknown'})")

        if not item.valuation:
            continue

        metrics = item.valuation.metrics
        for key, label, threshold in (
            ("trailing_pe", "Trailing P/E", 100),
            ("forward_pe", "Forward P/E", 100),
            ("ev_to_ebitda", "EV/EBITDA", 80),
        ):
            value = metrics.get(key)
            if isinstance(value, (int, float)) and value == value and value >= threshold:
                alerts.append(f"{item.ticker.symbol}: {label} {format_metric_value(value)}")
                break

        for key, label in (("trailing_pe", "Trailing P/E"), ("forward_pe", "Forward P/E")):
            value = metrics.get(key)
            if isinstance(value, (int, float)) and value == value and value < 0:
                alerts.append(f"{item.ticker.symbol}: negative {label} {format_metric_value(value)}")
                break

        rsi = metrics.get("rsi_14")
        if isinstance(rsi, (int, float)) and rsi == rsi:
            if rsi >= 70:
                alerts.append(f"{item.ticker.symbol}: RSI 14 overbought {format_metric_value(rsi)}")
            elif rsi <= 30:
                alerts.append(f"{item.ticker.symbol}: RSI 14 oversold {format_metric_value(rsi)}")

    return alerts


def _warning_items(report: DailyReport) -> list[tuple[str, str]]:
    return [
        (item.ticker.symbol, warning)
        for item in report.ticker_reports
        for warning in item.warnings
    ]


def _data_quality_summary(report: DailyReport, warning_items: list[tuple[str, str]]) -> str:
    parts: list[str] = []
    if warning_items:
        tickers = sorted({ticker for ticker, _warning in warning_items})
        sample = ", ".join(tickers[:6])
        more = f", +{len(tickers) - 6} more" if len(tickers) > 6 else ""
        parts.append(f"{len(warning_items)} ticker warnings across {len(tickers)} tickers ({sample}{more})")
    if report.warnings:
        parts.append(f"{len(report.warnings)} global warnings")
    return "; ".join(parts)


def _days_until(value: date, anchor: date) -> str:
    delta = (value - anchor).days
    if delta == 0:
        return "today"
    if delta == 1:
        return "tomorrow"
    return f"in {delta}d"


def _relative_datetime(value: object, anchor: date) -> str:
    if not hasattr(value, "date") or not hasattr(value, "strftime"):
        return str(value)
    delta = (value.date() - anchor).days
    if delta == 0:
        prefix = "today"
    elif delta == 1:
        prefix = "tomorrow"
    elif delta == -1:
        prefix = "yesterday"
    elif delta < -1:
        prefix = f"{abs(delta)}d ago"
    else:
        prefix = f"in {delta}d"
    return f"{prefix} {value.strftime('%m-%d %H:%M %Z')}"


def _article_time_label(article: object) -> str:
    published_at = getattr(article, "published_at", None)
    if not isinstance(published_at, datetime):
        return ""
    taipei = ensure_aware_utc(published_at).astimezone(ZoneInfo("Asia/Taipei"))
    return f", {taipei.strftime('%H:%M')} TPE"


def _compact_text(value: str, max_length: int) -> str:
    text = " ".join(value.split())
    if len(text) <= max_length:
        return text
    return text[: max_length - 3].rstrip() + "..."


def truncate_for_telegram(text: str) -> str:
    if len(text) <= TELEGRAM_MAX_MESSAGE_LENGTH:
        return text
    suffix = "\n\n[truncated]"
    return text[: TELEGRAM_MAX_MESSAGE_LENGTH - len(suffix)] + suffix
