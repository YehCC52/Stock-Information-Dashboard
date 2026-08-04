# Daily Stock Research Roadmap

這份 roadmap 用來指引後續開發。目標是打造一個每天自動產生的個人股票研究系統，重點是可信來源、可追溯資料、低成本、可穩定排程。

## Current Status

目前已完成 MVP：

- `watchlist.yaml` 管理追蹤股票。
- Google News RSS 抓可信 domain 新聞。
- `data/x_posts.yaml` 手動放入可信 X 訊號，避免付費 X API。
- `yfinance` 抓估值和財報日期。
- SQLite 儲存 news、X signals、valuation snapshots、earnings dates。
- Markdown / HTML 報表。
- Telegram 精簡摘要。
- Windows Task Scheduler 每天 08:00 排程。
- Macro calendar：FOMC 與 Nonfarm Payrolls / Employment Situation。
- Valuation last-known-good fallback：當日估值空值時使用最近一次有效 snapshot。

## Phase 1 - Reliability First

優先把每天自動跑的穩定性補強。

- 修正文件與 skills 編碼，保持 UTF-8。
- 補 `.env.example`，避免把 token 寫進 repo。
- 估值資料使用 last-known-good fallback。
- 增加 `report_runs` / `run_warnings` 儲存每次執行狀態。
- 把 provider error、fallback、skip reason 分級，避免 Telegram 過度吵。
- 增加資料源健康狀態：last success、last failure、failure count。

## Phase 2 - News Quality

提升新聞品質與效能。

- 將 trusted news domains 抽成全域 defaults，個別 ticker 只補特殊來源。
- 增加 raw RSS / normalized articles cache，減少重複抓取。
- 改善去重：canonical URL、normalized title、相似標題、同源轉載。
- 改善分類：earnings、guidance、M&A、regulation、lawsuit、product、analyst rating、macro。
- 加入來源權重與事件權重，產生 daily attention score。
- 對重要新聞保留 source URL、published time、source domain。

## Phase 3 - Valuation And Calendar

讓估值表更接近 Yahoo Finance 風格，並可看趨勢。

- 每日保留 valuation snapshot。
- 報表顯示 current + historical snapshots。
- 支援 30 / 90 天估值趨勢圖。
- 對異常估值做提示，例如負 P/E、極高 P/E、缺值。
- 若未來可接受 API key，優先評估 FMP 作為穩定估值來源。
- 財報日期可加入 Alpha Vantage 或 Finnhub 作為 yfinance 備援，但只有在使用者接受 API 成本或免費額度限制時才啟用。

核心 valuation fields：

- `market_cap`
- `enterprise_value`
- `trailing_pe`
- `forward_pe`
- `peg_ratio`
- `price_to_sales`
- `price_to_book`
- `ev_to_revenue`
- `ev_to_ebitda`

## Phase 4 - Macro Calendar

擴充影響利率預期與科技股估值的總經事件。

- 已完成：FOMC rate decision。
- 已完成：Nonfarm Payrolls / Employment Situation。
- 已完成：CPI（透過 BLS selected releases 即時抓取，`macro.py` `CORE_BLS_RELEASES`）。
- 已完成：PPI（同上路徑；深度 fallback（BLS 兩個來源都掛掉時）目前只涵蓋 NFP + CPI，尚未補 PPI 的離線備援時程）。
- 下一步：PCE。
- 下一步：ISM Manufacturing / Services。
- 下一步：Initial Jobless Claims。
- 報表中標示事件時間、來源、原始美東時間與本地時間。

## Phase 5 - X Signals

在不做未授權爬蟲、不碰付費 API 的前提下維持可信社群訊號。

- MVP：只讀 `data/x_posts.yaml`。
- 只接受 `trusted_x_accounts` 白名單中的帳號。
- 每則訊號保留 author、category、created_at、URL、engagement metrics。
- 將 X 視為 commentary / signal，不視為已驗證事實。
- 若未來使用官方 X API，必須先加入 daily budget、cache、rate-limit guard、failure fallback。

## Phase 6 - Reporting UX

讓每天閱讀更快。

- HTML 報表加入 attention ranking，把今天最該看的股票排前面。
- Telegram 摘要只放 actionable highlights。
- 增加一頁 overview：macro、earnings soon、top news、valuation warnings。
- Ticker card 增加近期估值變化、財報倒數、新聞熱度。
- 報表支援 mobile-friendly layout。

## Phase 7 - Local Dashboard

從靜態報表升級成本機 dashboard。

- 讀取 SQLite 顯示歷史資料。
- 支援 ticker 篩選、日期範圍、事件類型篩選。
- 顯示 valuation trend charts。
- 顯示 news history 和 attention score。
- 管理 watchlist，但不在 UI 中儲存 API secret。

## Data Source Notes

- X API：官方 API 可能付費或受使用量限制，目前不自動使用。
- NewsAPI：可做 domain filtering，但可能需要 API key；目前先不用。
- yfinance：非官方 Yahoo Finance 資料來源，適合個人用途 MVP，不保證穩定。
- Alpha Vantage：有 earnings calendar，可作未來財報日期來源。
- Finnhub：有 earnings calendar 和公司資料，可作未來備援。
- FMP：企業價值與 ratios 較完整，可作未來正式估值來源。
- BLS / Federal Reserve：總經日曆優先使用官方來源。

## Acceptance Criteria

- 每天排程能在部分資料源失敗時仍產出報表。
- 每個資料點都保留 source attribution。
- 不把 API keys 或 token 寫進 repo。
- Telegram 摘要短、清楚、只放重點。
- HTML 報表可以快速看出：今天有什麼事、哪些股票要優先看、哪些資料是 fallback。
- 測試維持通過，新增 provider 或 fallback 時要補測試。
