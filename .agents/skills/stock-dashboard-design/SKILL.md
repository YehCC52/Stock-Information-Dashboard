---
name: stock-dashboard-design
description: "Iterate on the daily HTML dashboard for the stock-daily-research project. Use when the user wants to change layout, density, color scheme, sections, or visual hierarchy of `reports/YYYY-MM-DD.html`. Examples: 「排版太擠 / 太鬆」、「Valuation 表格欄位太多」、「earnings pills 顯示不夠醒目」、「想新增一個 X 區塊」、「dark mode 顏色怪」、「mobile 版裂掉」."
---

# Stock Dashboard Design

## When to use this skill

The user is iterating on the **daily HTML report's visual layout**. They typically open `reports/<today>.html` in a browser and want a tweak.

Don't use this skill for:
- Adding a new **data source** → use `stock-pipeline-provider`
- Adding a **ticker** → use `stock-watchlist`
- Markdown report format (`.md`) — the audience there is Telegram + plain-text, layout work goes to HTML

## Files to know

| Concern | File |
| --- | --- |
| HTML template | [src/stock_daily_research/templates/daily_report.html.j2](src/stock_daily_research/templates/daily_report.html.j2) |
| Renderer + helpers | [src/stock_daily_research/report.py](src/stock_daily_research/report.py) |
| Data shapes | [src/stock_daily_research/models.py](src/stock_daily_research/models.py) — `DailyReport`, `TickerReport`, `EconomicEvent`, `NewsArticle`, `ValuationSnapshot`, `EarningsDate` |
| Tests | [tests/test_report.py](tests/test_report.py) |
| Latest output to inspect | `reports/<latest>.html` |

## Data the template receives

`render_html_report(report)` passes:

- `report` (`DailyReport`): `report_date`, `generated_at`, `ticker_reports[]`, `warnings[]`, `economic_events[]`
- `summary` (dict): `ticker_count`, `tickers_with_news`, `tickers_with_warnings`, `earnings_soon_count`, `economic_event_count`, `global_warning_count`
- `earnings_soon` (list of `TickerReport`): earnings ≤ 7 days
- `important_news` (list of `(TickerReport, NewsArticle, tier)` triples): importance ≥ 0.8, capped at 12. **Tier is by position quota**: `top` only when idx<3 AND score≥1.0, `primary` when idx<8, `minor` rest. This keeps "top" meaningful even when many articles share high scores.
- `hero` (list of dict): top 1–3 most decision-pressing items. Each dict has `kind`, `tone` (`imminent`/`soon`/`info`), `label`, `headline`, `subtitle`, `anchor`. Priority order: imminent earnings clusters (grouped by day) → imminent macro (≤2d) → valuation watch (P/E ≥100 tickers) → top news fallback.
- `valuation_keys` (list[str]): column order for the valuation table

## Filters available in template

| Filter | Source | Purpose |
| --- | --- | --- |
| `metric_label` | `report.METRIC_LABELS` | `market_cap` → `Market Cap` |
| `metric_value` | `valuation.format_metric_value` | `1_250_000_000_000` → `1.25T`, NaN → `N/A` |
| `date_or_na` | `report.date_or_na` | dates / None → ISO or `N/A` |
| `days_until` | `report.days_until` | `today` / `tomorrow` / `in 3d` / `2d ago` |
| `earnings_urgency` | `report.earnings_urgency` | `imminent` / `soon` / `week` / `later` / `past` |
| `pe_class` | `report.pe_class` | `""` / `elevated` / `high` / `extreme` / `neg` |
| `ticker_anchor` | inline lambda | `NVDA` → `ticker-nvda` |
| `event_label` | `report.event_label` (from `news.EVENT_LABELS`) | `analyst_call` → `Analyst call` |
| `news_tier` | `report.news_tier` | `top` (≥1.0) / `primary` (≥0.7) / `minor` |
| `ticker_insights` | `report.ticker_insights` | dict with `setup`/`risk`/`watch` lists |
| `card_state` | `report.card_state` | `hot` / `warm` / `warn` / `quiet` |

If you add a new helper, follow the precedent:
1. Add a pure function in `report.py`
2. Register it as a filter inside `render_html_report` (so it has access to `report.report_date` if it's date-relative)
3. Add a unit test in `tests/test_report.py` (look at `test_pe_class_buckets`, `test_earnings_urgency_buckets` for shape)

## Design system

Light/dark theme via CSS variables. **Use the existing variables — do not hardcode hex.** They live in `:root` and `@media (prefers-color-scheme: dark) :root`.

Tokens:
- Surfaces: `--bg`, `--surface`, `--surface-soft`, `--surface-alt`
- Text: `--text`, `--muted`
- Borders: `--border`, `--border-soft`
- Links: `--link`
- States: `--warning` / `--warning-bg`, `--danger` / `--danger-bg`, `--good` / `--good-bg`, `--info` / `--info-bg`
- Shadow: `--shadow`

Visual conventions already in place:
- Numbers right-aligned via `<th class="num">` / `<td class="num">` and `font-variant-numeric: tabular-nums`
- Long tables wrap in `.table-wrap` with `max-height: 560px` + sticky `thead`
- Chips: `.badge` + state modifier (`warn` / `danger` / `good` / `info`)
- News event chips: `.event-badge.event-<type>` — color-coded by category (earnings=red, guidance/supply=orange, ma/regulation/lawsuit/antitrust=blue, ai/product=green, others=neutral)
- Date-urgency cards: `.earnings-pill` + urgency class. `imminent` is intentionally **louder** (2px border + outer glow + danger-bg)
- News rows: `.news-item.tier-<top|primary|minor>` — top tier gets danger left-border + tinted bg; minor tier dims text
- Hero cards: `.hero-card.<imminent|soon|info>` — sit above summary, the page's "today matters" zone
- Ticker cards: `.ticker-card.<hot|warm|warn|quiet>` — top-edge color stripe (3px) + border tint by state. Quiet cards opacity 0.7 (full on hover)
- Insight rows on ticker cards: `.insight-row.<setup|risk|watch>` — auto-derived from data (don't fabricate sentiment, only summarize what's already in the report)
- Section anchors: each `<section id="...">` plus a `<nav class="toc">` entry
- Ticker cards have `id="ticker-<lowercase-symbol>"` and `scroll-margin-top: 80px` (so sticky ToC doesn't cover them)

Breakpoints: `1100px`, `760px`, `480px`. There's also a `@media print` block — don't break it.

## Fast iteration loop

The full pipeline takes ~15s (18 tickers × news + yfinance). For HTML-only changes, skip the network:

```powershell
python run_daily.py --no-news --no-valuation --no-macro
```

This regenerates `reports/<today>.html` from existing config in <1s. The page will be mostly N/A, but the **layout structure** renders identically — perfect for CSS / template work.

When you need real data, look at the most recent fully-fetched report (e.g. yesterday's) — open it directly in the browser. Or rerun without flags (~15s).

## Common requests → recipes

### "排版太擠" / "want more spacing"
- Increase `.section { padding }`, currently `16px`
- Increase `.summary-grid { gap }` / `.ticker-grid { gap }` from 10–12px to 14–16px
- Increase line-height on `body` from 1.45

### "排版太鬆 / 想看更多資訊"
- Lower `.metric` padding from 6–8px to 4–6px
- Drop `.summary-grid` to 4 columns by adjusting `grid-template-columns`
- Use `.ticker-grid` `minmax(280px, 1fr)` to fit more cards per row

### "Valuation 表格太寬 / 看不完"
- Trim `valuation_keys` in `render_html_report` (drop one of price_to_book / ev_to_revenue)
- Move secondary metrics to ticker cards only
- Switch the table to `position: sticky; left: 0` on the symbol column for horizontal-scroll legibility

### "想再加一個 section"
1. Compute the data — add a helper in `report.py` (e.g. `top_movers(report)`)
2. Pass as kwarg in `render_html_report(...)`
3. Add a `<section id="..." class="section">` in the template, **between existing sections** (don't append after the footer)
4. Add an entry in `<nav class="toc">`
5. Add a test in `tests/test_report.py` checking the new section appears
6. Increment `summary` if the section count is worth surfacing

### "Earnings pills 不夠醒目"
- They already use urgency colors (`imminent`/`soon`/`week`). To make them louder: add an `outline: 2px solid var(--danger)` on `.earnings-pill.imminent`, or animate with a subtle `@keyframes pulse`
- To highlight tickers with both earnings AND high-importance news, add a combined badge in the pill

### "首屏資訊密度太高 / 重點不夠突出"
- The hero block (`#hero`) is the dedicated "today matters" zone. Tweak `hero_items()` in `report.py` to change what surfaces — currently: imminent earnings clustered by day → next macro within 2d → top news fallback
- Summary stat count is 4. Going below 4 makes the row feel sparse; going above 6 dilutes attention
- If a section feels secondary, move it below the fold and add a stronger "find me" link in the ToC

### "我想再強化某類訊號"
- Visual hierarchy already cascades: hero → summary → macro → earnings (imminent loudest) → news (tier-top loudest) → valuation → ticker cards (hot loudest, quiet dimmed)
- Don't fight the cascade — strengthen the specific level. To make `pe-extreme` even louder, give it a small icon prefix; don't add a separate banner

### "新聞分類好像不準"
- Classifier is in [news.py:EVENT_RULES](src/stock_daily_research/news.py). 7 conservative categories + `other`: earnings / regulation / deal / ai / analyst / product / market.
- **Each rule is a regex requiring multi-word phrases** — `\bearnings\b` alone is intentionally NOT a match because a stray "earnings call" mention in a partnership story would hijack the category. Use `beats? estimates`, `quarterly results`, `raises guidance` etc.
- Order matters: more specific categories first, less specific last. `regulation` must come before `deal` because "DOJ sues" should beat "merger" if both appear.
- Prefer false negatives (→ `other`) over false positives. The user complained that "everything is earnings" hurts trust more than "some things uncategorized".

### "Top news 都是 tier-top,失去意義"
- `important_news()` enforces position quotas: top ≤3 (and score ≥1.0), primary fills idx 3-7, minor is rest. Don't relax this — the danger left-border is the strongest visual cue and dilutes if everything has it.

### "雜訊新聞混進來" (ETF profile, biography, quote pages)
- Two filters in [news.py](src/stock_daily_research/news.py): `NOISE_URL_PATTERNS` (path-based: `/quote/`, `/etfs/`, `/profile/`) and `NOISE_TITLE_PATTERNS` (text-based: "stock price", "About YieldMax", "Profile and Biography", "leveraged X bull").
- When a new noise pattern appears, add it to one of those tuples and add a unit test in `tests/test_news.py:test_is_noise_article_*`.

### "短代號 ticker (ARM, MU, AI) 抓到不相干文章"
- `is_relevant_article()` in news.py drops aliases shorter than 4 chars entirely — they're too ambiguous. ARM's bare alias "Arm" is ignored; only "Arm Holdings" or company_name "Arm Holdings plc" matches. This trades recall for precision.
- If a short-name ticker is missing real coverage, the fix is in **watchlist.yaml** — add longer specific aliases (e.g. "Arm CPU", "Arm chip design"), not in `is_relevant_article` itself.

### "Dark mode 顏色不對"
- Check the variable in **both** `:root` and the dark-mode block. Adding a new variable to one without the other causes mismatches.
- Test in browser: DevTools → Rendering → "Emulate CSS prefers-color-scheme"

### "Print / PDF export 變形"
- The `@media print` block at the end of the `<style>` controls this. It hides `.toc` and `details`, removes shadows, and unbounds `.table-wrap`. Verify with Ctrl+P preview.

### "Mobile 版裂掉"
- Test at the three breakpoints: 1100 / 760 / 480
- The 760px block already sets `.toc` to `position: static` and stacks `.news-item` to one column; if a new section breaks below 760, add overrides there
- Use `clamp()` or the smaller breakpoint instead of fighting flex/grid behavior

## Checklist before declaring done

- [ ] `python -m pytest tests/test_report.py` passes
- [ ] Regenerate via `python run_daily.py --no-news --no-valuation --no-macro` and open `reports/<today>.html`
- [ ] Toggle DevTools → Rendering → prefers-color-scheme dark; verify no contrast/legibility issues
- [ ] Resize to 760px and 480px; no overflow, no wrapping disasters
- [ ] Ctrl+P preview; sticky ToC and `<details>` are hidden, tables expand
- [ ] If you added a new template-side decision (urgency, classification), it's a Python helper + filter + test, not inline `{% if %}` chains
- [ ] No hardcoded colors — all via CSS variables

## Anti-patterns to avoid

- Inline `style="..."` on elements — kills theming; put it in the `<style>` block with a class
- Computing data in Jinja with nested `{% if %}` — move to `report.py` helpers
- Hardcoded margins/paddings in numbers like `padding: 13px` — stick to the existing scale (4 / 6 / 8 / 10 / 12 / 14 / 16 / 18 / 24)
- External JS / CSS / fonts — the report must work offline, when emailed, when printed. No `<script src>`, no `<link>` to CDNs.

## When inline JS is OK

Tiny dependency-free `<script>` blocks for UI-only state (theme toggle, collapse-all, etc.) are acceptable when:
- Self-contained (no external dependencies)
- Degrades gracefully if JS is disabled (CSS/HTML fallback works)
- Hidden in `@media print` so it doesn't appear in PDF / printouts
- Persists via `localStorage` only (no remote calls)

Existing precedent: the theme toggle. Pattern:
1. **Pre-paint script in `<head>`** reads `localStorage.getItem("stock-daily-theme")` and sets `data-theme` on `<html>` to avoid flash-of-wrong-theme
2. **CSS** defines tokens in `:root` (light) and overrides in `:root[data-theme="dark"]` AND `@media (prefers-color-scheme: dark) :root:not([data-theme="light"])` — so OS preference works when no manual override is set
3. **End-of-body script** wires the toggle button to cycle `auto → light → dark`, persists, applies
4. `.theme-toggle { display: none; }` inside `@media print`

Don't add JS for: sortable tables, live data refresh, charts, anything fetching remote resources. Those signals say "you've outgrown a static report" — at that point switch to the planned Phase 6 web dashboard rather than bolt features onto the daily HTML.
