# 台股月營收查詢系統

Taiwan Stock Monthly Revenue Query System

## 系統架構

⚠️ 目前 GitHub Pages 實際上線版本與下方 backend/frontend 目錄的架構不同，說明如下。

**實際上線版本（GitHub Pages）**：純 HTML/CSS/Vanilla JavaScript 單頁應用（根目錄 index.html），無資料庫、無後端伺服器。開啟頁面時直接在瀏覽器呼叫 TWSE OpenAPI 批次端點（上市月營收、收盤價）與 FinMind API 取得全市場資料，實測約 6 秒內可完整載入上市 1000 多檔股票的表格。即時資料經 functions/api/proxy.js（Cloudflare Pages Function）做 CORS 代理；部署於非 pages.dev 網域（如目前使用的 GitHub Pages）時，改用公開的 corsproxy.io 備援。搶先報分頁不會發送新的網路請求，而是直接從主表已載入的資料中篩選「次月營收」有值的個股，切換分頁近乎即時。

**本機開發版本（backend/ + frontend/，目前尚未部署上線）**：Backend 為 Python FastAPI（async）+ SQLAlchemy async + SQLite，啟動時與每日排程做增量同步，並提供手動全量同步的 API。Frontend 為 React + Vite + Zustand + CSS Modules + Recharts，透過相對路徑 /api/... 呼叫上述後端。這一組後端／前端目前只能依下方「快速啟動」步驟在本機執行，尚未串接到實際的 GitHub Pages 部署。

**資料來源**：TWSE OpenAPI（上市股票清單＋收盤價）、TPEx OpenAPI（上櫃股票清單＋收盤價）、FinMind API（月營收歷史資料）。

## 快速啟動

### 1. 設定環境變數

```bash
cd backend
cp .env.example .env
# 編輯 .env，填入 FINMIND_TOKEN
```

### 2. 啟動 Backend

```bash
cd backend
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Backend 會在 http://localhost:8000 啟動，並自動同步資料。

### 3. 啟動 Frontend

```bash
cd frontend
npm install
npm run dev
```

Frontend 會在 http://localhost:5173 啟動。

## API 端點

| 端點 | 說明 |
|------|------|
| GET /api/stocks | 股票清單（支援 q, market 搜尋） |
| GET /api/stocks/{stock_id} | 單支股票資訊 |
| GET /api/stocks/count | 股票總數 |
| GET /api/revenue/{stock_id} | 月營收資料 |
| POST /api/sync | 手動觸發同步 |
| GET /health | 健康檢查 |

## 資料同步

- 啟動時自動執行一次增量同步（priority stocks + 近 3 個月）
- 每天 18:30 自動增量同步
- 可透過 POST /api/sync?full=true 觸發完整歷史同步

## 色彩規範（台股慣例）

- 🔴 上漲：`#e05252`
- 🟢 下跌：`#3fb950`
