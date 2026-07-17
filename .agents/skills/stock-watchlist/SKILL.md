---
name: stock-watchlist
description: "Manage watchlist.yaml for US stocks, Taiwan stocks, ETFs, and crypto. Use to add or remove symbols, set market and asset capabilities, edit aliases or trusted sources, link cross-listing symbols, or maintain position, plan, and research defaults."
---

# Stock Watchlist

## Goal

Keep `watchlist.yaml` accurate enough that every downstream provider, market view, score, and portfolio calculation knows what the asset is and which data is meaningful.

Use `stock-pipeline-provider` for source integration and `stock-dashboard-design` for presentation changes.

## Source of Truth

Each ticker may define:

- `symbol` and `company_name`.
- `market`: `us`, `twse`, `tpex`, or `crypto`.
- `currency`: normally `USD` or `TWD`.
- `has_fundamentals`: set false for ETFs, leveraged ETFs, and crypto.
- `aliases` and `keywords` for news relevance.
- `trusted_news_domains` and `trusted_x_accounts`.
- `related_symbols` for cross-listing references such as `TSM` and `2330.TW`.
- `position`, `plan`, and `research` as durable defaults.

`TickerConfig.has_earnings` is derived from asset capability. Do not add a separate YAML flag unless the model changes.

## Market Conventions

| Asset | Example | Required settings |
| --- | --- | --- |
| US stock | `NVDA` | `market: us`, `currency: USD` |
| TWSE stock | `2330.TW` | `market: twse`, `currency: TWD` |
| TPEx stock | `5425.TWO` | `market: tpex`, `currency: TWD` |
| Taiwan ETF | `0050.TW` | Taiwan market, TWD, `has_fundamentals: false` |
| Crypto | `BTC-USD` | `market: crypto`, USD, `has_fundamentals: false` |

Use Yahoo-compatible exchange suffixes for price history. Do not put a US ADR in the Taiwan market merely because the company is Taiwanese.

## Minimal Examples

```yaml
- symbol: 2330.TW
  company_name: 台灣積體電路製造股份有限公司
  market: twse
  currency: TWD
  aliases: [台積電, TSMC]
  related_symbols: [TSM]
  position:
    status: watchlist

- symbol: 0050.TW
  company_name: 元大台灣50
  market: twse
  currency: TWD
  has_fundamentals: false
  aliases: [0050, 元大台灣50]
  position:
    status: watchlist

- symbol: BTC-USD
  company_name: Bitcoin
  market: crypto
  currency: USD
  has_fundamentals: false
  aliases: [BTC, Bitcoin]
  position:
    status: watchlist
```

Position status values used by the UI are `watchlist`, `holding`, `tracking`, and `avoid`. Preserve shares, average cost, stop loss, sector, and manual portfolio weight when editing another field.

## Asset-Capability Rules

- Company stocks may use fundamentals and earnings.
- ETFs and crypto may use price, trend, momentum, volume, liquidity, risk, and news, but must not request meaningless earnings or company fundamentals.
- Missing data is unavailable, not zero.
- `related_symbols` creates navigation/context only. It does not merge news, earnings, positions, market membership, or rankings.
- Keep Taiwan, US, and crypto aliases specific enough to avoid ambiguous news matches.
- Do not add a trusted domain simply to increase article volume; source quality and relevance come first.

## Workflow

1. Read the complete ticker list and check for duplicate symbols or aliases.
2. Identify asset type, exchange suffix, market, currency, and capabilities.
3. Make the smallest YAML edit and preserve user-authored plan, position, and research fields.
4. Validate configuration:

```powershell
python -c "from stock_daily_research.config import load_config; load_config('watchlist.yaml')"
python -m pytest tests/test_config.py -q
```

5. Generate an offline structural report:

```powershell
python run_daily.py --no-news --no-valuation --no-macro --no-taiwan-data
```

6. For a new symbol, run the relevant real providers and verify its market tab, data-quality state, and lack of cross-market leakage.

## Removal and History

Removing a YAML block stops future collection but does not purge SQLite history. Preserve historical data unless the user explicitly requests deletion.

## Done Criteria

- Config loads without errors and the symbol is unique.
- Market, currency, suffix, and `has_fundamentals` match the asset.
- ETFs and crypto do not produce fundamental or earnings errors.
- Cross-listed symbols remain separate instruments.
- The generated report places the ticker only in the intended market view.
