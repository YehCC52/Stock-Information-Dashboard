---
name: stock-watchlist
description: "Manage the watchlist for the stock-daily-research project — add/remove tickers, edit aliases/keywords/trusted domains/X accounts, validate `watchlist.yaml`. Use when the user says 「加 NVDA」、「把 TSLA 拿掉」、「改某檔的 trusted news domains」、「加一個 trusted X account」、「watchlist.yaml 報錯」."
---

# Stock Watchlist

## When to use

CRUD on [watchlist.yaml](watchlist.yaml) — the central config that drives every per-ticker fetch. Don't use this skill for:
- Adding a new **data source** → `stock-pipeline-provider`
- Changing the **dashboard layout** → `stock-dashboard-design`

## Schema (enforced by [config.py](src/stock_daily_research/config.py))

```yaml
settings:
  report_timezone: Asia/Taipei      # any IANA zone; validated via ZoneInfo
  news:
    lookback_days: 3                # > 0
    max_articles_per_ticker: 8      # > 0
    provider: google_news_rss
  x_signals:
    mode: manual                    # only "manual" or "api" allowed
    manual_file: data/x_posts.yaml
  valuation:
    provider: yfinance
  earnings:
    provider_order:
      - yfinance
  macro:
    enabled: true
    days_ahead: 14                  # > 0
  notifications:
    telegram:
      enabled: false
      disable_web_page_preview: true

tickers:
  - symbol: TICKER                  # required, uppercased automatically
    company_name: Full Legal Name   # required
    aliases: [Common Name, Variant]
    keywords: [product, segment]
    trusted_news_domains: [reuters.com, cnbc.com]
    trusted_x_accounts:
      - handle: example_handle      # required, leading @ stripped
        category: industry_expert   # required, see categories below
        display_name: Optional Display Name
```

## Field semantics

| Field | Effect |
| --- | --- |
| `symbol` | yfinance lookup + DB key + report headers; uppercased |
| `company_name` | Used in news search query AND the relevance gate; must be findable in news titles |
| `aliases` | Widens the news query AND relevance gate (e.g. "Nvidia" matches "NVIDIA Corporation") |
| `keywords` | Boosts `importance_score` by +0.1 when an article mentions them; does **not** widen the search query |
| `trusted_news_domains` | Each one becomes a separate Google News query (`site:domain`). Defaults to `[reuters.com, cnbc.com]` if empty. **Each domain = one HTTP request** — keep ≤ 5 per ticker |
| `trusted_x_accounts` | Whitelists who counts as a trusted X poster. Categories drive credibility score (`x_signals.score_category`) |

## X account categories (from [x_signals.py](src/stock_daily_research/x_signals.py))

```
company_official      1.00
investor_relations    1.00
executive             0.95
sell_side_analyst     0.80
buy_side_researcher   0.75
industry_expert       0.70
data_provider         0.65
journalist            0.60
(anything else)       0.40
```

## Adding a ticker — recipe

```yaml
  - symbol: TICKER
    company_name: Full Legal Name
    aliases:
      - Common Name
    keywords:
      - product / segment 1
      - product / segment 2
    trusted_news_domains:
      - reuters.com
      - cnbc.com
      - wsj.com
      - ft.com
      - bloomberg.com
    trusted_x_accounts: []
```

Then verify in three steps:

```powershell
# 1. Config validates
python -c "from stock_daily_research.config import load_config; load_config('watchlist.yaml')"

# 2. Fast smoke (no network) — confirms the ticker shows up
python run_daily.py --no-news --no-valuation --no-macro

# 3. Full run — confirms yfinance has data and Google News finds articles
python run_daily.py
```

If the new ticker shows `Valuation fetch failed:` in the report, the symbol may not be on Yahoo (recent IPO, OTC, foreign exchange suffix needed e.g. `2330.TW` for TSMC's Taiwan listing instead of `TSM` ADR). Try the alternate symbol or accept missing valuation data.

## Removing a ticker

Just delete the YAML block. Existing rows in `data/stock_daily.sqlite3` stay (history) — that's fine. To purge: `sqlite3 data/stock_daily.sqlite3 "DELETE FROM news_articles WHERE ticker='OLD'; DELETE FROM valuation_snapshots WHERE ticker='OLD'; ..."` — usually unnecessary.

## Common errors and fixes

| Error | Cause | Fix |
| --- | --- | --- |
| `tickers[N].symbol is required` | Missing or empty `symbol` field | Add it; quote if it has special chars |
| `tickers[N].trusted_x_accounts[M].handle is required` | Empty `handle` in an X account block | Either fill it or remove the entry |
| `Invalid x_signals.mode 'foo'` | Typo in `mode` | Only `manual` or `api` |
| `Invalid report_timezone 'X'` | Bad IANA zone | Use canonical name like `Asia/Taipei`, `America/New_York` |
| `news.lookback_days must be > 0` | Set to 0 or negative | Use 1+ (typical: 1–7) |
| `No tickers configured in <path>` | `tickers:` is `[]` or absent | Add at least one ticker |

## Performance budget

The runner uses `ThreadPoolExecutor(max_workers=6)`. Per-ticker cost (with all sources on):

- News: 1 HTTP request × N domains, ~2s per domain in serial within a worker
- Valuation: 1 yfinance call, ~2–4s
- Earnings: 1 yfinance call, ~2–4s

So **per-ticker wall time** ≈ `N_domains × 2s + 6s`. With 5 domains: ~16s per ticker if serial; with 6 parallel workers, total run = `ceil(N_tickers / 6) × 16s`.

For an 18-ticker watchlist with 5 domains each: ~3 batches × 16s ≈ **45s realistic, ~15s with cache hits**. Already measured.

If a watchlist grows past ~30 tickers and runs feel slow, the lever is **fewer trusted domains per ticker** (each is a separate HTTP request), not more workers — Google News and Yahoo will throttle aggressive concurrency.

## Tests covering watchlist behavior

- [tests/test_config.py](tests/test_config.py) — schema validation, error messages
- [tests/test_news.py](tests/test_news.py) — `is_relevant_article` (alias/symbol matching), `keyword_score` (keyword boost)
- [tests/test_x_signals.py](tests/test_x_signals.py) — trusted account whitelist
