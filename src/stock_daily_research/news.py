from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from html import unescape
import re
from urllib.parse import quote_plus

import feedparser
import requests

from .models import NewsArticle, TickerConfig

logger = logging.getLogger(__name__)


# Event classifier: 7 conservative categories + "other".
# Each rule is a regex matched case-insensitively against title+summary.
# Patterns are intentionally multi-word / phrase-based to avoid greedy
# false positives like a single word "earnings" tagging unrelated articles.
# Order matters: more specific categories first; whichever matches wins.
EVENT_RULES: list[tuple[str, tuple[re.Pattern[str], ...], float]] = [
    ("earnings", (
        re.compile(r"\b(beats?|misses?|tops?|trails?)\s+(estimates|expectations|forecasts|consensus)\b", re.I),
        re.compile(r"\bquarterly\s+(results|earnings|profit|revenue)\b", re.I),
        re.compile(r"\bq[1-4]\s+(20\d{2}|earnings|results|revenue)\b", re.I),
        re.compile(r"\b(reports|posts|delivers)\s+(record\s+)?(revenue|earnings|profit|loss)\b", re.I),
        re.compile(r"\b(eps|earnings\s+per\s+share)\b", re.I),
        re.compile(r"\b(raises|cuts|lowers|reaffirms|withdraws)\s+(full[-\s]year\s+)?(guidance|outlook|forecast)\b", re.I),
        re.compile(r"\bprofit\s+warning\b", re.I),
    ), 1.0),
    ("regulation", (
        re.compile(r"\bantitrust\b", re.I),
        re.compile(r"\bmonopol(y|istic|ize)\b", re.I),
        re.compile(r"\b(doj|ftc|sec|european\s+commission|cma)\s+(sues|charges|fines|investigates|probes|opens)\b", re.I),
        re.compile(r"\b(sued|lawsuit|settlement|court\s+ruling|judge\s+(ruled|orders)|class\s+action)\b", re.I),
        re.compile(r"\b(regulator(s|y)?|regulation|enforcement|sanction|consent\s+decree)\b", re.I),
        re.compile(r"\b(competition\s+probe|antitrust\s+probe)\b", re.I),
    ), 0.85),
    ("deal", (
        re.compile(r"\b(acquir(es?|ed|ing|ition)|merger|merges?\s+with)\b", re.I),
        re.compile(r"\b(takeover|buyout|to\s+buy|agrees?\s+to\s+buy)\b", re.I),
        re.compile(r"\b(joint\s+venture|partnership\s+with|partners\s+with|strategic\s+partnership)\b", re.I),
        re.compile(r"\b(equity\s+investment|stake\s+in|invests?\s+\$?\d+)\b", re.I),
        re.compile(r"\bspin[-\s]?off\b", re.I),
    ), 0.85),
    ("ai", (
        re.compile(r"\b(generative\s+ai|artificial\s+intelligence)\b", re.I),
        re.compile(r"\b(open\s*ai|anthropic|deepmind|gemini|gpt-?\d*|claude|llama)\b", re.I),
        re.compile(r"\b(ai\s+(chips?|infrastructure|model|startup|race|copilot|agent))\b", re.I),
        re.compile(r"\b(llm|large\s+language\s+model|foundation\s+model)\b", re.I),
        re.compile(r"\bcopilot\b", re.I),
    ), 0.8),
    ("analyst", (
        re.compile(r"\b(upgrades?|downgrades?)\s+(to|from|stock|shares|rating)\b", re.I),
        re.compile(r"\bprice\s+target\s+(raised|cut|lowered|to|of)\b", re.I),
        re.compile(r"\b(initiates?\s+coverage|reiterates?\s+(buy|sell|hold))\b", re.I),
        re.compile(r"\b(overweight|underweight|outperform|underperform)\s+rating\b", re.I),
        re.compile(r"\banalysts?\s+(say|expect|cut|raise|see|forecast)\b", re.I),
    ), 0.7),
    ("product", (
        re.compile(r"\b(unveils?|launches?|debuts?|introduces?|announces?)\s+(new\s+)?[a-z]+\s+(chip|gpu|cpu|product|service|feature)", re.I),
        re.compile(r"\bnext[-\s]?gen(eration)?\s+(chip|gpu|cpu|platform|product)\b", re.I),
        re.compile(r"\brolls?\s+out\s+[a-z]+\s+(model|service)", re.I),
    ), 0.6),
    ("market", (
        re.compile(r"\b(s\s*&\s*p\s*500|nasdaq|dow\s+jones|russell\s+\d{4})\b", re.I),
        re.compile(r"\b(stocks?|markets?|equities)\s+(rise|fall|gain|drop|slip|surge|tumble|plunge|rally|sink|end\s+(higher|lower))\b", re.I),
        re.compile(r"\btreasury\s+yields?\b", re.I),
        re.compile(r"\b(fomc|federal\s+reserve|fed\s+(rate|decision|cut|hike|chair)|rate\s+(decision|cut|hike))\b", re.I),
        re.compile(r"\b(inflation|cpi|ppi|jobs\s+report|nonfarm|tariff)\b", re.I),
    ), 0.5),
]


EVENT_LABELS: dict[str, str] = {
    "earnings": "Earnings",
    "regulation": "Regulation",
    "deal": "Deal",
    "ai": "AI",
    "analyst": "Analyst",
    "product": "Product",
    "market": "Market",
    "other": "Other",
}

CORPORATE_SUFFIXES = {
    "ag",
    "co",
    "company",
    "corp",
    "corporation",
    "inc",
    "limited",
    "llc",
    "ltd",
    "nv",
    "plc",
    "sa",
}


# URL paths from publishers that are quote / ETF / "about" / profile pages, not real articles.
NOISE_URL_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"/(quote|quotes|symbols?|tickers?|markets?-data|stock-?prices?|etfs?)/", re.I),
    re.compile(r"/about(?:[-_/][a-z0-9]+)*(?:/|$)", re.I),
    re.compile(r"/(profile|biography|insiders?|officers?-and-directors)/", re.I),
    re.compile(r"/companies/[a-z0-9-]+/?$", re.I),
)

# Title patterns that indicate a quote / promotional / SEO / leveraged-product / bio page,
# not real reporting on the company.
NOISE_TITLE_PATTERNS: tuple[re.Pattern[str], ...] = (
    # Quote / price pages
    re.compile(r"\b(stock|share)\s+price\b", re.I),
    re.compile(r"\b(real[-\s]?time|live)\s+(quote|price)", re.I),
    # SEO listicle / how-to
    re.compile(r"\bwatch\s*list\b", re.I),
    re.compile(r"\bhow\s+to\s+(buy|sell|invest|trade)", re.I),
    re.compile(r"\b(should|will)\s+you\s+(buy|sell)\b", re.I),
    re.compile(r"\b(buy|sell)\s+rating\s+for\s+", re.I),
    # ETF / fund / leveraged-product profile pages
    re.compile(r"\babout\s+(the|this|yieldmax|direxion|proshares)\b", re.I),
    re.compile(r"\b(yieldmax|direxion\s+daily|proshares\s+ultra)\b", re.I),
    re.compile(r"\b(option\s+income|leveraged|inverse|bull\s+\d+x|bear\s+\d+x)\s+(strategy\s+)?(etf|fund|shares)\b", re.I),
    re.compile(r"\b(etf|fund)\s+(holdings|review|analysis|profile|dividend|distribution)\b", re.I),
    # Biography / profile pages
    re.compile(r":\s*profile\s+and\s+biography\b", re.I),
    re.compile(r"\b(profile|biography|net\s+worth)\s+of\b", re.I),
    re.compile(r"\b(officers|insiders|board\s+of\s+directors)\s+(of|and)\b", re.I),
)


def is_noise_article(title: str, url: str) -> bool:
    for pattern in NOISE_URL_PATTERNS:
        if pattern.search(url):
            return True
    for pattern in NOISE_TITLE_PATTERNS:
        if pattern.search(title):
            return True
    return False


class GoogleNewsRssProvider:
    """Free RSS-based news provider for MVP use."""

    def __init__(self, timeout_seconds: int = 20, max_retries: int = 2) -> None:
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries

    def fetch_for_ticker(
        self,
        ticker: TickerConfig,
        lookback_days: int,
        max_articles: int,
    ) -> tuple[list[NewsArticle], list[str]]:
        """Return (articles, per-domain warnings).

        A failure on one domain only drops that domain's results; other domains
        continue to be queried.
        """
        articles: list[NewsArticle] = []
        warnings: list[str] = []
        domains = ticker.trusted_news_domains or ticker.default_news_domains
        min_published_at = datetime.now(timezone.utc) - timedelta(days=lookback_days)
        for domain in domains:
            try:
                articles.extend(
                    self._fetch_for_domain(ticker, domain, lookback_days, min_published_at)
                )
            except Exception as exc:
                logger.warning("News fetch failed for %s (%s)", domain, ticker.symbol, exc_info=True)
                warnings.append(f"News fetch failed for {domain}: {exc}")

        return dedupe_articles(articles)[:max_articles], warnings

    def _fetch_for_domain(
        self,
        ticker: TickerConfig,
        domain: str,
        lookback_days: int,
        min_published_at: datetime,
    ) -> list[NewsArticle]:
        query = self._build_query(ticker, domain, lookback_days)
        url = (
            f"https://news.google.com/rss/search?q={quote_plus(query)}"
            f"&hl={quote_plus(ticker.news_language)}&gl={quote_plus(ticker.news_region)}"
            f"&ceid={quote_plus(ticker.news_edition)}"
        )
        response = self._request_with_retry(url)
        feed = feedparser.parse(response.content)
        articles: list[NewsArticle] = []
        for entry in feed.entries:
            article = self._entry_to_article(ticker, domain, entry, min_published_at)
            if article:
                articles.append(article)
        return articles

    def _request_with_retry(self, url: str) -> requests.Response:
        last_exc: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                response = requests.get(
                    url,
                    timeout=self.timeout_seconds,
                    headers={"User-Agent": "stock-daily-research/0.1"},
                )
                response.raise_for_status()
                return response
            except requests.RequestException as exc:
                last_exc = exc
                if attempt < self.max_retries:
                    time.sleep(2 ** attempt)
        assert last_exc is not None
        raise last_exc

    def _build_query(self, ticker: TickerConfig, domain: str, lookback_days: int) -> str:
        terms = [ticker.display_symbol, f'"{ticker.company_name}"', *[f'"{alias}"' for alias in ticker.aliases]]
        term_query = " OR ".join(terms)
        return f"({term_query}) site:{domain} when:{lookback_days}d"

    def _entry_to_article(
        self,
        ticker: TickerConfig,
        domain: str,
        entry: object,
        min_published_at: datetime,
    ) -> NewsArticle | None:
        title = unescape(str(getattr(entry, "title", "")).strip())
        url = str(getattr(entry, "link", "")).strip()
        if not title or not url:
            return None

        source = getattr(getattr(entry, "source", None), "title", None) or domain
        summary = unescape(str(getattr(entry, "summary", "")).strip())
        published_at = parse_feed_datetime(str(getattr(entry, "published", "") or getattr(entry, "updated", "")))
        # Drop undated/unparseable items rather than treating them as fresh — an
        # entry with no usable date must not slip past the lookback window.
        if published_at is None or published_at < min_published_at:
            return None
        if not is_relevant_article(ticker, title):
            return None
        if is_noise_article(title, url):
            return None
        event_type, event_score = classify_event(title, summary)
        recency_score = 0.2 if published_at else 0.0
        keyword_bonus = keyword_score(ticker, title, summary)
        importance_score = round(event_score + recency_score + keyword_bonus, 3)

        return NewsArticle(
            ticker=ticker.symbol,
            title=title,
            source=str(source),
            domain=domain,
            published_at=published_at,
            url=url,
            summary=summary,
            event_type=event_type,
            importance_score=importance_score,
        )


def parse_feed_datetime(value: str) -> datetime | None:
    if not value:
        return None
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def classify_event(title: str, summary: str = "") -> tuple[str, float]:
    """Conservative event classifier.

    Returns ("other", 0.3) when nothing matches confidently — better to leave
    a story unclassified than to mislabel it. Patterns require multi-word
    phrases so a stray "earnings" mention in an unrelated article doesn't
    hijack the category.
    """
    text = f"{title} {summary}"
    for event_type, patterns, score in EVENT_RULES:
        for pattern in patterns:
            if pattern.search(text):
                return event_type, score
    return "other", 0.3


def dedupe_articles(articles: list[NewsArticle]) -> list[NewsArticle]:
    sorted_articles = sorted(articles, key=lambda article: article.importance_score, reverse=True)
    seen_urls: set[str] = set()
    seen_titles: set[str] = set()
    result: list[NewsArticle] = []
    for article in sorted_articles:
        title_key = normalize_title(article.title)
        url_key = article.url.split("?")[0].lower()
        if url_key in seen_urls or title_key in seen_titles:
            continue
        seen_urls.add(url_key)
        seen_titles.add(title_key)
        result.append(article)
    return result


def normalize_title(title: str) -> str:
    """Normalize Latin and CJK headlines without discarding Chinese identity terms."""
    normalized = re.sub(r"[^\w\s]+", " ", title.lower(), flags=re.UNICODE)
    return " ".join(normalized.split())


def keyword_score(ticker: TickerConfig, title: str, summary: str = "") -> float:
    if not ticker.keywords:
        return 0.0
    haystack = normalize_title(f"{title} {summary}")
    for keyword in ticker.keywords:
        normalized = normalize_title(keyword)
        if normalized and normalized in haystack:
            return 0.1
    return 0.0


def is_relevant_article(ticker: TickerConfig, title: str, summary: str = "") -> bool:
    """Article counts as on-topic only when an identity term appears in the TITLE.

    Summary is intentionally ignored: it often lists peripheral mentions
    ("...stocks like Microsoft, Alphabet, Nvidia...") that pull non-subject
    articles into the wrong ticker. The title is the most reliable signal of
    what the article is actually about.

    Identity terms (company_name and aliases) shorter than 4 chars are dropped
    entirely — they collide with English words ("arm" the body part, "go", "ai")
    and other-exchange suffixes (".MU", ".AS").

    Symbol alone is only accepted when ≥5 chars (GOOGL, AVGO). Shorter symbols
    like MU / ARM / AMD always require an identity-term match.

    The `summary` parameter is kept for backward compatibility but is unused.
    """
    del summary
    haystack = normalize_title(title)
    candidate_terms = company_identity_terms(ticker.company_name)
    candidate_terms.extend(
        alias for alias in ticker.aliases if len(alias) >= 4 or any(ord(char) > 127 for char in alias)
    )

    for term in candidate_terms:
        normalized = normalize_title(term)
        if not normalized or (normalized.isascii() and len(normalized) < 4):
            continue
        if normalized.isascii() and len(normalized) <= 5:
            if re.search(rf"\b{re.escape(normalized)}\b", haystack):
                return True
        elif normalized in haystack:
            return True

    symbol = normalize_title(ticker.display_symbol)
    symbol_alone_ok = (
        len(symbol) >= 5
        or (ticker.market in {"twse", "tpex"} and symbol.isdigit() and len(symbol) == 4)
        # Crypto tickers (BTC, ETH, SOL) are unambiguous in headlines from
        # crypto-focused domains, unlike 3-letter stock symbols.
        or (ticker.market == "crypto" and len(symbol) >= 3)
    )
    if symbol_alone_ok:
        if symbol and re.search(rf"\b{re.escape(symbol)}\b", haystack):
            return True

    return False


def company_identity_terms(company_name: str) -> list[str]:
    normalized = normalize_title(company_name)
    if not normalized:
        return []

    terms = [normalized]
    parts = normalized.split()
    while len(parts) > 1 and parts[-1] in CORPORATE_SUFFIXES:
        parts = parts[:-1]
        stripped = " ".join(parts)
        if stripped and stripped not in terms:
            terms.append(stripped)
    return terms
