# zpromo — Zazzle Ambassador 自動推薦系統

Ambassador ID：`238439349232116915`　自家商店：`readycardcard`、`nirvanatw`

每天自動從 Zazzle 官方 RSS 抓各分類前 15 頁的熱銷商品，依排程推薦到 **Pinterest、Tumblr、Bluesky、Threads**，
並產生一個 **GitHub Pages 選物網站**（全部商品都帶推薦碼）與 **監控面板**。

```
Zazzle RSS ──harvest──▶ 商品庫(SQLite) ──planner──▶ 排程 ──publisher──▶ Pinterest / Tumblr / Bluesky / Threads
                                   │                                         │
                                   └──site──▶ GitHub Pages 選物站            └──metrics──▶ 監控面板 + 每日報告
                     Zazzle 銷售 CSV（加密）──import-sales──┘
```

## 佣金規則（程式已內建，不用手動處理）

| 情況 | 連結格式 | 佣金 |
|---|---|---|
| 自家商品（readycardcard / nirvanatw） | 原始網址，**不帶任何參數** | 35–50%（邀請卡/婚禮 50%） |
| 其他創作者商品 | `網址?rf=238439349232116915&tc=<平台>` | 15% |

- 自家商品若帶了 `?rf=` 會被降成 15%，所以程式會先抓你兩家商店的全部商品，碰到就把參數全部拿掉。
- 推薦有效期 45 天；14 天內別人的推薦連結蓋不掉你的。
- 禁止：競標含「Zazzle」的付費關鍵字、優惠券網站、網域含 Zazzle、垃圾訊息。
- 每篇貼文都有 `#ad · affiliate link` 揭露（FTC 與 Pinterest 都要求）。

## 一、部署（約 30 分鐘）

1. GitHub 建立 **public** repo `zazzle-promo`（public 才有無限 Actions 分鐘數與免費 Pages）。
   從 bundle 還原並推上去：
   ```cmd
   cd /d D:\PROJECTS
   git clone zazzlepromo.bundle zazzle-promo
   cd zazzle-promo
   git remote set-url origin https://github.com/<你的帳號>/zazzle-promo.git
   git push -u origin main
   ```
2. repo → Settings → Pages → Source 選 **GitHub Actions**。
3. 產生加密金鑰：`pip install -r requirements.txt` 後執行
   `set PYTHONPATH=src && python -m zpromo.cli keygen`，把輸出存成 secret **ZPROMO_KEY**（自己也備份一份）。
4. 修改 `config/settings.yaml`：Tumblr blog 名稱、Bluesky handle、`site.public_url`、各平台 `start_date`。
5. Actions → zpromo → Run workflow，command 填 `probe` → 看到商品清單代表 Zazzle feed 正常。
6. 再跑一次 `daily`，網站與面板就會出現在 `https://<帳號>.github.io/zazzle-promo/`（面板在 `/report/`）。

## 二、各平台金鑰（repo → Settings → Secrets and variables → Actions）

| 平台 | Secrets | 取得方式 |
|---|---|---|
| Pinterest | `PINTEREST_APP_ID` `PINTEREST_APP_SECRET` `PINTEREST_REFRESH_TOKEN` | developers.pinterest.com 建 App → 本機 `python -m zpromo.cli auth-pinterest` 照指示取得 refresh token |
| Tumblr | `TUMBLR_CONSUMER_KEY` `TUMBLR_CONSUMER_SECRET` `TUMBLR_TOKEN` `TUMBLR_TOKEN_SECRET` | tumblr.com/oauth/apps 註冊 App → 本機 `python -m zpromo.cli auth-tumblr` |
| Bluesky | `BLUESKY_HANDLE` `BLUESKY_APP_PASSWORD` | Bluesky 設定 → 隱私與安全 → App passwords（不要用主密碼） |
| Threads | `THREADS_USER_ID` `THREADS_ACCESS_TOKEN` | developers.facebook.com 建 App 加 Threads API（權限 threads_basic、threads_content_publish、threads_manage_insights）→ 換成 60 天長效 token |
| 自動續期 | `GH_PAT` | fine-grained PAT，只給這個 repo 的 **Secrets: Read and write**；有了它 Threads token 每週自動續期 |
| 通知 | `NOTIFY_WEBHOOK` | Discord 或 Slack webhook（完整金額只送這裡） |

沒設定的平台會在報告顯示「缺少 secret」，不會影響其他平台。

### Pinterest 要特別注意
Pinterest 新 App 只有 **Trial access**，此時建立的 Pin「只有自己看得到」（sandbox）。要公開發文必須申請
**Standard access**（My apps → Upgrade，需要上傳一段示範 OAuth 登入與發 Pin 流程的影片）。
在核准之前，設定 `pinterest.mode: csv`（預設值）：

- 每週一 daily 會產生 `pinterest_bulk_*.csv`（每檔 ≤100 筆，含排定的發佈時間，14 天內）
  以及 `pinterest_boards_*.csv`（這批 Pin 用到的看板：名稱／SEO 描述／關鍵字／建議封面圖）
- 到 Actions 該次執行頁面下載 artifact **pinterest-bulk-csv**
- **Pinterest 的大量上傳不會自動建立看板**：先照 boards CSV 把還沒有的看板建好（名稱要一字不差）
- Pinterest → 建立 → **大量建立 Pin** → 上傳 bulk CSV，Pinterest 會依 Publish date 自動分時發佈
- 想一次拿到全部 23 個看板的清單：Actions → Run workflow → command 填 `pinterest-boards`

核准 Standard 後改成 `mode: api` 就全自動：程式會自動建立缺少的看板（名稱＋描述，公開），
並產生 1000×1500 直式 Pin 圖。Pinterest API 沒有「看板封面」欄位，封面預設取看板內的 Pin，
要指定封面請在 Pinterest App 看板 → 編輯 → 變更封面，選 boards CSV 建議的那張。

## 三、時序排程

| 時間（UTC） | 台灣時間 | 工作 |
|---|---|---|
| 每小時 :11 | 每小時 :11 | `hourly`：補排程 + 發出到時間的貼文 |
| 每天 05:37 | 13:37 | `daily`：自家商店同步（週一）→ 抓分類頁 → 排程 → Pinterest CSV（週一）→ 抓成效 → 匯入銷售 → 報告 → 重建網站 |
| 週日 04:23 | 週日 12:23 | Threads token 續期 |

每天的發文時間會在各平台的「美國受眾活躍時段」內隨機挑選，並保持最短間隔，不會像機器一樣整點發：

| 平台 | 第 1–2 週 | 之後逐步 | 上限 | 最短間隔 | 時段（UTC） |
|---|---|---|---|---|---|
| Pinterest | 8/天 | 12 → 18 | 25/天（第 9 週起） | 40 分 | 00–04、13–16、18–21 |
| Tumblr | 6/天 | 10 | 15/天 | 60 分 | 01–05、14–18、20–23 |
| Bluesky | 3/天 | 5 | 8/天 | 2 小時 | 00–04、13–17、21–23 |
| Threads | 3/天 | 5 | 7/天 | 2.5 小時 | 00–04、12–16、22–24 |

這些數字遠低於各平台 API 上限（Pinterest 100 次/分、Tumblr 250 篇/天、Threads 250 篇/天、Bluesky 1,666 則/時），
是刻意照「像真人」的節奏設計，避免被判定為 spam。全部都在 `config/settings.yaml` 調整。

### 選品順序（「依序把每個類別前 15 頁推完」）
- `harvest` 以「頁」為主軸：先抓所有分類的第 1 頁，再第 2 頁……到第 15 頁；每 14 天重抓更新排名。
- `planner` 每天每平台：先保留 25% 名額給自家商品（佣金高 2–3 倍），其餘用「加權輪替」—
  進度最落後的分類先排，分類內一律從排名最前面、尚未推過的商品開始。
- 當季分類（萬聖節、聖誕卡、日曆…）權重 ×3，淡季 ×0.3，所以會自動跟著節慶走。
- 同平台 90 天內不重複同一商品；同一創作者每天每平台最多 2 件。

### 老實說：要多久推完？
45 個分類 × 900 名 ≈ 4 萬件商品。以安全頻率，Pinterest 滿速一天 25 篇，全部推完要好幾年。
所以設計成：**選物網站當天就收錄全部商品**（每件都帶推薦碼、可被 Google 搜到），
社群平台則永遠先推「排名最前面 + 當季」的商品——這些才是最可能成交的。面板上有每個平台的完成率與預估天數。

## 四、監控

面板：`https://<帳號>.github.io/zazzle-promo/report/`（不被搜尋引擎索引），每日也會寫入 Actions Job Summary 與 webhook。

| 監控項目 | 用途 |
|---|---|
| 各平台 24h / 7天 / 30天 / 累計發文數、今日待發、失敗數 | 確認排程有在跑 |
| 錯誤與警示（憑證失效、429 限流、連續失敗、24h 無發文、Threads token 快到期、feed 抓取錯誤） | 需要人處理時立刻知道 |
| 分類頁抓取進度、每平台推薦完成率與預估天數 | 追蹤「前 15 頁推完」目標 |
| Pinterest 曝光、外連點擊、儲存、**CTR**；Tumblr notes；Bluesky 讚/轉發；Threads 瀏覽/讚 | 哪個平台、哪類商品有效 |
| 自家商品占比 | 確保高佣金商品有被推 |
| 佣金：自推/跨推筆數與金額、按平台歸因、按 `tc` 來源 | 真正的成效 |
| 表現最佳 15 篇貼文、各分類進度 | 決定要加重哪些分類 |

### 匯入 Zazzle 銷售報表
Zazzle 沒有公開的收益 API，需要你定期（建議每週）手動匯出一次：
1. Zazzle → My Account → Earnings → Referral History，匯出或把表格複製成 CSV
2. 本機加密：`python -m zpromo.cli encrypt-file --path referrals_2026-10.csv`（需設定環境變數 ZPROMO_KEY）
3. 把產生的 `.csv.enc` 放進 `data/zazzle_reports/` commit 推上去（明文 `.csv` 已被 .gitignore 擋住）

欄位名稱不用改，程式會自動辨識日期／商品／金額／佣金／類型；有 18 位數商品 ID 就能對應回是哪篇貼文帶來的。

## 五、隱私
- 狀態資料庫以 `ZPROMO_KEY` 加密後存在 `state` 分支（只保留一個 commit，不會無限長大）。
- 公開網站與 Actions 日誌預設隱藏金額（`privacy.public_money: false`），完整金額只送到你的 webhook。

## 六、常用指令（本機）
```cmd
set PYTHONPATH=src
python -m zpromo.cli probe        :: 測試 Zazzle feed
python -m zpromo.cli status       :: 看目前報告
python -m pytest -q               :: 跑測試
```
手動觸發：Actions → zpromo → Run workflow → command（hourly / daily / harvest / export-pinterest / status …）。
