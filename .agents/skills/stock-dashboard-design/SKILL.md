---
name: stock-dashboard-design
description: "Design and verify the stock daily HTML dashboard. Use for layout, information hierarchy, responsive behavior, Traditional Chinese localization, market switching, report sections, or local UI interactions."
---

# Stock Dashboard Design

## Goal

Make the generated report answer three questions in order: what needs attention, why it matters, and what to inspect next. Improve decision clarity before adding visible features.

Use this skill for report UI and UX work. Use `stock-strategy-validation` for score or strategy logic, `stock-pipeline-provider` for data sources, and `stock-watchlist` for ticker configuration.

## Files

- `src/stock_daily_research/templates/daily_report.html.j2`: HTML, CSS, responsive rules, and dependency-free UI state.
- `src/stock_daily_research/report.py`: analysis helpers and render context.
- `src/stock_daily_research/models.py`: immutable data shapes.
- `tests/test_report.py`: helper, output-structure, and regression tests.
- `reports/YYYY/MM/YYYY-MM-DD.html`: generated artifact to inspect.

## Product Invariants

- Preserve the hierarchy: daily decisions, portfolio risk, candidates, ticker detail.
- Keep US, Taiwan, and crypto content isolated in market-scoped views.
- Treat `stock-daily:market` as the shared market-switch event.
- Keep calculations and classifications in pure Python helpers, not Jinja or JavaScript.
- Keep the report self-contained and usable offline. Do not add CDN assets, external fonts, or runtime fetches.
- Preserve light/dark themes, print behavior, localStorage state, keyboard focus, and no-JavaScript readability.
- Put detailed evidence in an existing collapsed area before creating a new top-level section.
- Do not describe generated daily snapshots as real-time data.

## Decision Hierarchy

Prefer these surfaces, in this order:

1. Morning actions and daily summary for immediate decisions.
2. Portfolio risk and current holdings for exposure control.
3. Strategy screener and right-side candidates for review.
4. Ticker cards for evidence, plans, news, and research state.
5. Validation, trade journal, and advanced frameworks as supporting detail.

A new feature should normally replace, consolidate, or enrich one of these surfaces. Add a new section only when it serves a distinct recurring workflow.

## Localization

- Write natural Taiwan Traditional Chinese, not word-for-word translations.
- Keep familiar terms such as ticker, ETF, EPS, RSI, ATR, P/E, and API when translation reduces clarity.
- Prefer direct labels such as `觀察中`, `已持有`, `待檢視`, `突破成立`, and `風險升高`.
- Use one term consistently across headings, filters, badges, exports, and empty states.
- Keep source titles and company names in their original language when appropriate.

## Workflow

1. Inspect the latest data-rich report and identify the user's primary task.
2. Find the smallest existing surface that can answer it.
3. Add or change a pure helper in `report.py` when the UI needs derived data.
4. Render presentation in the template using existing CSS variables and spacing.
5. Add focused tests for helper boundaries and rendered output.
6. Regenerate a structural report:

```powershell
python run_daily.py --no-news --no-valuation --no-macro --no-taiwan-data
```

7. Inspect a data-rich report so empty placeholders do not hide overflow or density problems.
8. Verify desktop, 760px, and 480px widths, each market tab, light/dark mode, print preview, and browser console.

## Responsive Checklist

- Text and controls stay inside their containers; long symbols and labels wrap or truncate intentionally.
- Fixed-format controls use stable dimensions so state changes do not shift layout.
- The page has no horizontal overflow at 760px or 480px.
- Buttons use familiar icons where available and retain accessible names or tooltips.
- Score grids, tables, and ticker cards remain scannable without nested cards.
- Hidden market content does not affect visible counts, rankings, news, or events.
- Empty, loading, unavailable, and stale-data states remain distinguishable.

## Feature Gate

Before adding visible UI, require at least three of these:

- It changes a daily decision.
- It uses reliable available data.
- It can be understood in about ten seconds.
- It replaces manual work or an existing section.

If it fails the gate, improve background validation, evidence text, or an existing summary instead.

## Anti-Patterns

- Do not add decorative cards, oversized headings, animation, or extra badges without decision value.
- Do not place cards inside cards.
- Do not hardcode colors; use existing CSS variables.
- Do not add business logic through nested Jinja conditionals.
- Do not duplicate the same signal in summary, screener, and ticker header.
- Do not add JavaScript sorting or filtering when existing market/filter controls can be extended cleanly.

## Done Criteria

- Focused report tests pass.
- A generated report works offline and has no console errors.
- US, Taiwan, and crypto views show only their own scoped content.
- Desktop and mobile layouts have no overlap, clipped labels, or page-level overflow.
- The new UI makes the next action clearer without increasing the number of concepts the user must learn.
