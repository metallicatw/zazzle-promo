# 平台研究與推廣策略（2026-09）

## 為什麼選這 5 個曝光管道

| 管道 | 優點 | 限制 / 風險 | 結論 |
|---|---|---|---|
| **Pinterest** | 使用者帶「找東西買」的意圖；Pin 壽命以月計；婚禮、節慶、客製禮物正是 Zazzle 強項；POD 業者公認第一流量來源 | 新 App 只有 Trial（sandbox）；公開發文需 Standard access 審核；重複貼同一連結、短時間爆量、短網址/轉址容易被判 spam | **主力**。直連 Zazzle 商品頁、每日量逐步放大、每篇揭露 #ad |
| **Tumblr** | API 免費、OAuth1 token 不過期；對聯盟連結友善；貼文會被 Google 收錄；tag 搜尋帶長尾流量 | 每帳號 250 篇/天；受眾較小 | 次要自動管道，SEO 加分 |
| **Bluesky** | 開放 AT Protocol、無審核、可帶連結卡片縮圖；寫入上限寬鬆（35,000 點/天） | 購物意圖弱；300 字限制 | 低成本曝光，量少質精 |
| **Threads** | 免費官方 API；250 篇/24h；使用者基數大 | token 60 天要續期；Meta App 設定較繁瑣 | 自動發文 + 每週自動續期 |
| **GitHub Pages 選物站** | 全部 4 萬件商品一次上線、每件帶推薦碼；可被 Google 搜到；可當各平台個人簡介的「link in bio」；也是監控面板 | 冷啟動要時間累積 SEO | 解決「社群平台一天只能推幾十件」的量能問題 |

### 評估後不採用
- **X (Twitter)**：2026 起 API 改為按量計費，每篇都要付費，連結貼文觸及又被降權，CP 值低。
- **Instagram**：貼文內文連結不能點，只能靠 bio；API 發文需商業帳號＋FB 粉專，對聯盟導購不划算。
- **Reddit**：多數社群明文禁止自我推銷，自動發文很快被 ban，不建議。
- **Facebook 社團**：沒有發文 API；粉專 API 需要 App 審核，觸及率低。

## 反封鎖設計
1. 暖身期：新自動化從低量開始，第 9 週才到 Pinterest 25/天。
2. 隨機時間 + 最短間隔，避開整點規律。
3. 同一商品同平台 90 天內不重發；同一創作者每天最多 2 件；分類輪替讓內容多元。
4. 不用短網址、不用轉址，一律直連 zazzle.com。
5. 遇到 429 立即停該平台、2 小時後重排；憑證錯誤立即停並警示。
6. 每篇 `#ad · affiliate link` 揭露。
7. Zazzle 端只用官方 RSS，每次請求間隔 3 秒，每天抓取有上限。

## 佣金最大化
- 自家商品固定 25% 名額（自推 35–50% vs 跨推 15%，一單抵 2–3 單）。
- 邀請卡／婚禮類（自推 50%，客單價高、常大量訂購）權重較高。
- 季節權重自動跟著節慶：9–10 月萬聖節，10–12 月聖誕卡／裝飾品／2027 日曆，1–2 月情人節…
- `tc=pin/tb/bs/th/site` 追蹤碼讓 Zazzle 報表能分辨是哪個平台帶來的訂單（第一週請確認報表有顯示；若無影響或異常可在設定關閉）。

## 參考來源
- Zazzle Ambassador Center（附件 PDF）；[Referral Commissions & Creator Royalties](https://www.zazzle.com/hc/article/ambassador_referral_commissions_creator_royalties-30810357489175)
- [Ambassador Program Agreement](https://www.zazzle.com/terms/ambassadors_agreement)；[Ambassador Program FAQs (PDF)](https://www.zazzle.com/assets/graphics/z5/zmisc/ambassador_program/Ambassador_Program_FAQs.pdf)
- [Zazzle RSS Guide v1.05](https://asset.zcache.com/assets/graphics/z2/mk/sell/RSSGuide_2016.pdf)；[Zazzle Community：RSS feed 2026 討論](https://community.zazzle.com/t/product-type-in-rss-feed/305)
- [Pinterest API rate limits](https://developers.pinterest.com/docs/reference/rate-limits/)；[Pinterest access tiers](https://developers.pinterest.com/docs/key-concepts/access-tiers/)；[Pinterest 大量上傳 Pin](https://help.pinterest.com/en/business/article/bulk-upload-video-pins)
- [Pinterest marketing for POD 2026](https://merchtitans.com/blog/pinterest-marketing-print-on-demand)；[Pinterest affiliate without getting banned](https://84pins.com/pinterest-affiliate-marketing-without-getting-banned/)
- [Tumblr API v2](https://www.tumblr.com/docs/en/api/v2)；[Bluesky rate limits](https://docs.bsky.app/docs/advanced-guides/rate-limits)；[Threads API limits 2026](https://www.socialcrawl.dev/blog/threads-api)
- [X API pricing 2026](https://postproxy.dev/blog/x-api-pricing-2026/)
