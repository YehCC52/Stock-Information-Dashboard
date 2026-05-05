# Stock Daily Research

個人每日股票研究工具。它會依照 `watchlist.yaml` 產生每日報表，整合可信新聞、手動整理的 X 訊號、Yahoo Finance 風格估值、下次財報日期、重要總經事件，並可用 Telegram 發送精簡摘要。

此專案目前以免費或個人用途資料源為主，不會自動建立需要付費的 API 整合。

## 功能

- Watchlist：管理股票代號、公司名稱、別名、產業關鍵字、可信新聞 domain、可信 X 帳號。
- Trusted News：使用 Google News RSS 搜尋可信媒體來源，並做去重、分類與重要性排序。
- X Signals：MVP 不呼叫付費 X API，改用 `data/x_posts.yaml` 手動放入可信貼文。
- Valuation：使用 `yfinance` 取得 Market Cap、P/E、P/S、P/B、EV/EBITDA 等估值欄位。
- Last-known-good fallback：若當日估值抓取為空，會使用 SQLite 裡最近一次有效估值並加上 warning。
- Earnings Calendar：使用 `yfinance` 取得下次財報日期。
- Macro Calendar：追蹤 FOMC 利率決議與 Nonfarm Payrolls / Employment Situation 發布時間。
- Reports：輸出 Markdown 與互動式 HTML 報表。
- Telegram：可發送每日重點摘要，不把完整報表全部塞進訊息。
- Windows Schedule：可註冊每天早上 08:00 自動產出報表。

## Setup

```powershell
python -m pip install -e .[dev]
python run_daily.py --init-config
```

如果要使用 Telegram，建立 `.env`：

```powershell
Copy-Item .env.example .env
```

接著編輯 `.env`：

```dotenv
TELEGRAM_BOT_TOKEN=your_bot_token_here
TELEGRAM_CHAT_ID=your_chat_id_here
```

`.env` 已被 `.gitignore` 排除，請不要把真實 token 寫進 README、測試、watchlist 或任何會提交的檔案。

## Configuration

主要設定在 `watchlist.yaml`。

常用欄位：

- `settings.report_timezone`：報表時區，預設 `Asia/Taipei`。
- `settings.news.lookback_days`：新聞回看天數。
- `settings.news.max_articles_per_ticker`：每檔股票最多新聞數。
- `settings.x_signals.manual_file`：手動 X 訊號檔案位置。
- `settings.macro.enabled`：是否抓取總經事件。
- `settings.macro.days_back`：總經事件往回看幾天，台灣早報建議至少 1，用來保留凌晨已發生的 FOMC / 非農等事件。
- `settings.macro.days_ahead`：總經事件往後看幾天。
- `tickers[].trusted_news_domains`：可信新聞 domain 白名單。
- `tickers[].trusted_x_accounts`：可信 X 帳號白名單。

Macro calendar 範例：

```yaml
macro:
  enabled: true
  days_back: 1
  days_ahead: 14
```

## Run

產出完整報表：

```powershell
python run_daily.py
```

快速測試報表版面，不抓新聞和估值：

```powershell
python run_daily.py --no-news --no-valuation
```

不抓總經日曆：

```powershell
python run_daily.py --no-macro
```

產報表並發 Telegram 摘要：

```powershell
python run_daily.py --notify-telegram
```

輸出位置：

- Markdown report：`reports/YYYY-MM-DD.md`
- HTML report：`reports/YYYY-MM-DD.html`
- SQLite database：`data/stock_daily.sqlite3`

## Windows Daily Schedule

註冊每天 08:00 自動產生報表：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\register_daily_task.ps1
```

註冊每天 08:00 自動產生報表並發 Telegram：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\register_daily_task.ps1 -NotifyTelegram
```

指定其他時間：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\register_daily_task.ps1 -Time 07:30
```

## Data Sources

- Google News RSS：免費 RSS 搜尋，搭配 trusted domain 過濾。穩定性不等同正式授權新聞 API。
- yfinance：非官方 Yahoo Finance 資料來源，適合個人用途 MVP；若正式長期使用，建議改成穩定資料商。
- BLS Employment Situation schedule：官方非農發布時間來源。本機自動請求若被 403，會使用官方 2026 時程備援表。
- Federal Reserve FOMC calendar：官方 FOMC 會議與利率決議日期來源。
- X：官方 API 可能需要付費或有使用量限制；目前 MVP 不自動呼叫 X API。

## Telegram Notes

Telegram 摘要會優先列出：

- Macro：近期 FOMC、非農等總經事件。
- US overnight：美股收盤後到台灣早上產報表之間的高重要性可信新聞。
- Earnings <=7d：7 天內財報。
- Top news：高重要性可信新聞。
- Valuation / data flags：極端估值、負 P/E、估值 fallback。
- Data quality：資料抓取 warning 只做數量彙整，不逐條塞進 Telegram。

Telegram 設計原則是「早上先看重點」，完整細節仍以 HTML 報表為準。

若沒有收到 Telegram，先檢查：

- `.env` 是否在專案根目錄。
- `TELEGRAM_BOT_TOKEN` 和 `TELEGRAM_CHAT_ID` 是否都有值。
- 你是否已經先對 bot 傳過訊息。
- 執行時是否有加 `--notify-telegram`，或 `watchlist.yaml` 是否啟用 Telegram。

## Test

```powershell
python -m pytest
```

## Notes

- 此工具只供個人研究，不是投資建議。
- 報表中所有新聞、X 訊號、估值與日曆都應保留來源。
- 對重大投資決策，請回到公司公告、SEC filings、交易所公告或資料商原始資料交叉確認。
