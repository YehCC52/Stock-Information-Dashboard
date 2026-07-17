---
name: stock-strategy-validation
description: "Change or verify five-dimension stock health scores, strategy screener rules, right-side trading logic, persisted signals, and forward outcome validation. Use for score weights, thresholds, rankings, strategy categories, evidence text, or backtest integrity."
---

# Stock Strategy Validation

## Goal

Keep candidate rankings transparent, market-aware, and testable. A strategy match is a prompt for review, not investment advice or a guaranteed edge.

## Files

- `src/stock_daily_research/report.py`: diagnostics, strategy scores, execution gates, and validation summaries.
- `src/stock_daily_research/runner.py`: signal persistence timing and report assembly.
- `src/stock_daily_research/storage.py`: report runs, snapshots, and right-side signal history.
- `src/stock_daily_research/models.py`: immutable signal and history models.
- `tests/test_report.py`, `tests/test_runner.py`, `tests/test_storage.py`, and `tests/test_trading_workflow.py`.

## Scoring Invariants

- Keep every score deterministic, clamped to 0-100, and accompanied by inspectable evidence.
- Treat missing dimensions as unavailable and reweight across available dimensions; never coerce missing to zero.
- Keep technical regime resets decisive: failed trend or risk gates must be able to suppress a superficially strong setup.
- Penalize negative or unstable EPS before rewarding a large projected EPS-growth percentage.
- Use market-appropriate benchmarks and trading sessions.
- Rank within each market so a US universe cannot crowd out Taiwan or crypto.
- Keep position state and user-authored plans separate from objective setup quality.
- Do not move calculation logic into Jinja or client-side JavaScript.

## Current Dimensions

The health diagnostic combines:

1. Trend.
2. Momentum.
3. Volume and price behavior.
4. Fundamentals, only when the asset supports them.
5. Risk.

When changing weights, test full data, one missing dimension, ETF/crypto, strongly bullish, strongly bearish, negative EPS, and regime-reset cases.

## Current Strategy Views

The screener exposes:

- overall;
- breakout;
- pullback;
- squeeze;
- fundamental;
- unusual daily activity;
- risk-first.

Add a strategy only when it represents a distinct recurring decision. A renamed weight mix is not a new strategy. Prefer improving evidence or validation over adding another tab.

## Change Workflow

1. State the user decision the rule should improve.
2. Record current thresholds, example inputs, and expected rank order.
3. Make the smallest pure-function change.
4. Add boundary tests immediately below, at, and above each threshold.
5. Test missing and contradictory evidence.
6. Verify ranking limits independently for US, Taiwan, and crypto.
7. Generate a data-rich report and inspect score distribution, ties, labels, and empty states.
8. Run the full suite before completion.

Do not tune thresholds against one favored ticker or one trading day.

## Signal Persistence and Outcome Integrity

- Persist the signal as it existed on the report date before evaluating performance.
- Use exchange sessions, not raw calendar-day offsets.
- Default validation horizons are 5, 10, and 20 sessions.
- Never use future bars in feature calculation, signal generation, or threshold selection.
- Distinguish `pending` from `unavailable` outcomes.
- Keep source symbol, market, signal date, score, status, entry reference, and rule version stable.
- Avoid survivorship bias when selecting historical symbols.
- Show sample size with hit rate or excess return; never label a tiny sample as proven edge.
- Segment validation by market and regime before combining it globally.
- If strategy-specific signals are not persisted yet, describe their rankings as current-day screening only.

## Complexity Gate

Before exposing a new score, badge, or strategy, require all of these:

- It changes an entry, exit, sizing, risk, or review decision.
- Its input data is available and fresh enough.
- Its rule can be explained in one short evidence line.
- It has focused tests and a path to outcome validation.
- It does not duplicate an existing signal.

Otherwise keep it as background evidence or omit it.

## Done Criteria

- Scores remain within 0-100 and missing data is handled explicitly.
- Strong, weak, contradictory, ETF/crypto, and regime-reset tests pass.
- Per-market rank counts and ordering are deterministic.
- Historical validation has no lookahead and reports pending/unavailable correctly.
- The report communicates evidence and limitations without adding unnecessary visible complexity.
