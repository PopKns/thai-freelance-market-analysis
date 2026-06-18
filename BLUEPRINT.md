# พิมพ์เขียว — Fastwork Market Intelligence

> โปรเจค data ที่ดึงข้อมูลตลาดฟรีแลนซ์ไทยจาก Fastwork มาวิเคราะห์ → ทำ report + dashboard สาธารณะ → ต่อยอดเป็น prototype ML (fraud / recommendation)
> เป้าหมายคู่: **(1)** ของจริงที่คนไทยใช้ประโยชน์ได้ **(2)** flagship portfolio ที่ดึงความสนใจบริษัทเทคไทย (โดยเฉพาะ marketplace อย่าง Fastwork เอง)

---

## 1. ทำไมต้องทำ (Why)

ตลาดฟรีแลนซ์ไทยมีคนหลักแสน แต่ข้อมูลกระจัดกระจาย ไม่มีใครรวบรวม/วิเคราะห์ให้เห็นภาพ:
- ฟรีแลนซ์ไม่รู้ว่าควรตั้งราคาเท่าไหร่ สกิลไหนกำลังมาแรง
- ผู้ว่าจ้างไม่รู้ราคากลาง เสี่ยงโดนฟันราคา
- ตัว marketplace เองอยากได้เครื่องมือ fraud detection / recommendation

โปรเจคนี้ตอบทั้ง 3 กลุ่มด้วย **dataset + analysis เดียว**

## 2. ใครได้ประโยชน์ (3 audiences)

| กลุ่ม | ได้อะไร | artifact |
|---|---|---|
| **เล่นเอง / นักวิเคราะห์** | dataset ตลาดฟรีแลนซ์ไทย + report เชิงลึก | `data/`, report notebook |
| **Retail / คนนอก** | pricing advisor, demand dashboard, fair-price checker | dashboard สาธารณะ |
| **คนภายใน (Fastwork-like)** | prototype fraud detection / recsys / auto-categorize | `src/ml/` notebooks |

## 3. หลักการออกแบบ (Design principles)

- **เคารพ ToS เป็นอันดับแรก** — เช็ค `robots.txt`, rate-limit (1 req / 2-3 วินาที), cache ทุกหน้า, ดึงเฉพาะข้อมูลสาธารณะ, ไม่เก็บ PII (ชื่อจริง/อีเมล/เบอร์), anonymize seller เป็น id hash. นี่คือสัญญาณ professional ที่ employer มอง ไม่ใช่ข้อจำกัด
- **Snapshot ไม่ใช่ realtime** — ดึงเป็นชุดข้อมูลรายสัปดาห์ พอสำหรับ analysis ไม่กดดันเซิร์ฟเวอร์เขา
- **Pipeline แยกชั้นชัด** — collect → clean → analyze → serve แต่ละชั้นรันเดี่ยวได้ (ตามสไตล์ tech-radar)
- **Reproducible** — ใครก็ clone แล้วรันซ้ำได้ มี `requirements.txt` + README ที่รันตามได้จริง
- **Insight > raw data** — เป้าคือ "เห็นแล้วเข้าใจตลาด" ไม่ใช่กอง JSON

## 3.1 ผลตรวจสอบจริง (Verified 2026-06-17) ✅

- **robots.txt:** `Allow: /` ห้ามแค่ `/me/*`, `/profile`, `/inbox`, `/comingsoon`, `/method-refetch-category` (ส่วนส่วนตัว/PII ที่เราไม่แตะอยู่แล้ว) → หมวด/gig ดึงได้
- **gotcha:** site อยู่หลัง Cloudflare → `urllib` (default UA) โดน 403, ต้องใช้ `httpx` + custom UA; และ Python `robotparser` เป็น first-match เจอ `Allow: /` แล้ว allow หมด → เราเลย parse `Disallow` เป็น denylist บังคับเอง
- **โครงเว็บ:** Next.js SPA — หน้าหมวดเป็น JS tiles แต่หน้า gig ฝัง data ครบใน `__NEXT_DATA__` → `props.pageProps.dehydratedState.queries[PRODUCT_DETAIL]`
- **ขนาด:** products sitemap มี **222,512 gig URLs** (pattern `/user/<ชื่อ>/<หมวด>-<id>`)
- **ToS (review แล้ว 2026-06-17):** ✅ ไม่มี clause ห้าม scrape/crawl/automated access; ผูกพันเฉพาะ "ผู้ใช้งานที่สมัครบัญชี+กดยอมรับ" — เราดึงนิรนามไม่ล็อกอิน. ข้อจำกัดจริง 3 ข้อ = PDPA / ลิขสิทธิ์ / พรบ.คอมพิวเตอร์ 2550 → จัดการด้วย anonymize + เผยแพร่แค่ aggregate + เคารพ denylist (ดู README §Ethics & Compliance)

## 4. สถาปัตยกรรม (Architecture)

```
                  ┌──────────────┐     raw html/json      ┌──────────────┐
  Fastwork  ─────▶│ collect.py   │──────(cached)─────────▶│ clean.py     │
  (public listings)│ rate-limited │                        │ normalize +  │
                  │ + robots chk │                        │ anonymize    │
                  └──────────────┘                        └──────┬───────┘
                                                                 │ tidy dataset (parquet/csv)
                          ┌──────────────────────────────────────┤
                          │                                       │
                   ┌──────▼───────┐                       ┌───────▼────────┐
                   │ analyze.py   │  charts + stats       │ ml/ (phase 3)  │
                   │ report.ipynb │──────────────────────▶│ fraud / recsys │
                   └──────┬───────┘                       │ categorize     │
                          │ figures + tables              └────────────────┘
                   ┌──────▼───────┐
                   │ dashboard/   │  Streamlit / static HTML (public)
                   └──────────────┘
```

## 5. โครงสร้างโฟลเดอร์

```
fastwork-market-intel/
├── BLUEPRINT.md          ← ไฟล์นี้ (แผนงาน)
├── README.md             ← public-facing (อังกฤษ) สำหรับ GitHub/employer
├── requirements.txt
├── .gitignore            ← กัน data/ + .env หลุดขึ้น git
├── config.example.json   ← ตั้งค่า rate-limit, หมวดที่ดึง
├── src/
│   ├── collect.py        ← scraper (robots check + rate-limit + cache)
│   ├── clean.py          ← normalize + anonymize → tidy dataset
│   ├── analyze.py        ← สถิติ + charts
│   └── ml/               ← phase 3: fraud_detect.py, recommend.py, categorize.py
├── notebooks/
│   └── report.ipynb      ← "State of Thai Freelance Market" report
├── dashboard/            ← phase 2: Streamlit app หรือ static HTML
└── data/                 ← cache + dataset (gitignored, ไม่ push)
```

## 6. ข้อมูลที่เก็บ (Schema — เฉพาะ public, ไม่มี PII)

| field | ตัวอย่าง | ใช้ทำอะไร |
|---|---|---|
| `gig_id` | hash | คีย์ (anonymized) |
| `category` / `subcategory` | "ออกแบบโลโก้" | วิเคราะห์ตามหมวด |
| `price_min`, `price_max` | 1500, 5000 | pricing analysis |
| `delivery_days` | 3 | speed vs price |
| `rating`, `review_count` | 4.9, 120 | คุณภาพ / fraud signal |
| `seller_hash`, `seller_level` | hash, "Pro" | seller analytics (anonymized) |
| `tags`, `description` | text ไทย | NLP / categorize |
| `scraped_at` | 2026-06-17 | snapshot versioning |

> **ไม่เก็บ:** ชื่อจริง, อีเมล, เบอร์, รูปโปรไฟล์, ลิงก์ติดต่อส่วนตัว

## 7. Roadmap (3 สัปดาห์)

### Phase 1 — Data foundation (สัปดาห์ 1)
- [x] `collect.py`: robots denylist + rate-limit + cache + sitemap→gig→`__NEXT_DATA__`
- [x] `clean.py`: flatten + anonymize seller → parquet (พิสูจน์แล้วกับ 3 gig)
- [ ] ดึง sample ตัวแทน (เช่น ~2-5k gig กระจายทุกหมวด) → dataset แรก
- **Deliverable:** dataset สะอาด + README รันตามได้

### Phase 2 — Analysis & public dashboard (สัปดาห์ 2)
- [x] `report.ipynb` ร่างแล้ว (8 sections): glance, price dist, price/หมวด, supply, speed↔price, ratings, pricing advisor, takeaways — code รันผ่านทุก cell (validate บน 154 gig)
- [ ] เรนเดอร์ notebook บน sample เต็ม 3,000 (charts) เมื่อ collection เสร็จ
- [x] dashboard สาธารณะ (`dashboard/app.py`, Streamlit): **sidebar filters** (หมวด/ช่วงราคา/มีรีวิว) + 4 tabs — Pricing advisor, Demand map, **Opportunity finder** (price×low-supply×demand ปรับ weight ได้), **Trust & anomaly** (reuse `ml/anomaly.py` โชว์ gig น่าสงสัย) — validate ด้วย streamlit AppTest ผ่านทั้ง 4 tab
- **Deliverable:** report แชร์ได้ + dashboard ที่คนนอกเข้าดูได้

### Phase 3 — ML prototypes (สัปดาห์ 3)
- [x] `src/ml/anomaly.py`: unsupervised trust/fraud **screening** (rule flags + IsolationForest + deterministic explain), CLI จัด ranking
- [x] `notebooks/fraud_explore.ipynb`: สำรวจ + viz + write-up honest (เรนเดอร์ charts แล้ว)
- [x] `tests/test_anomaly.py`: 4 tests พิสูจน์ทุกกฎด้วย synthetic (CI-safe)
- **Finding จริง:** EXTREME_PRICE ยิง 14 (฿2M placeholder ฯลฯ); rule อื่น dormant เพราะ (1) review counts consistent → fake-review มองไม่เห็น (2) random sample ทำลาย seller-spam signal → ต้อง targeted collection. IsolationForest จับ star-seller ปนด้วย → เป็น triage ไม่ใช่ classifier
- **Deliverable:** ✅ prototype + write-up เชิงเทคนิค (honest about limits = จุดขาย)

## 8. Tech stack

- **เก็บ/ทำความสะอาด:** Python, `httpx`, `selectolax`/`beautifulsoup4`, `pandas`, `pyarrow`
- **วิเคราะห์:** `pandas`, `matplotlib`/`plotly`, Jupyter
- **dashboard:** Streamlit (เร็วสุด) หรือ static HTML
- **ML (phase 3):** `scikit-learn`; ส่วน NLP ไทยใช้ `pythainlp`; explanation layer ใช้ Claude
- **คุณภาพ:** `pytest`, `ruff`, GitHub Actions CI

## 9. ตัวชี้วัดความสำเร็จ (สำหรับ portfolio)

- README ที่ dev เห็นแล้วรันตามได้ใน 5 นาที
- report ที่แชร์ได้บน FB/Twitter dev ไทย (เป้า: มีคน reshare)
- "โค้ด/insight ผมถูกเอาไปใช้/อ้างอิง" = ประโยคเด็ดในสัมภาษณ์
- โชว์ครบ pipeline: scraping → cleaning → analysis → ML → presentation

## 10. ความเสี่ยง & ข้อควรระวัง

| ความเสี่ยง | การรับมือ |
|---|---|
| ToS / กฎหมาย | ดึงเฉพาะ public, ไม่เก็บ PII, rate-limit, ใส่ disclaimer ใน README, พร้อมถอดถ้าถูกร้องขอ |
| หน้าเว็บเปลี่ยน structure | cache raw ไว้, แยก parser ออกเป็นชั้น, มี test |
| ข้อมูลไม่ครบ/มี noise | clean ให้ดี, รายงาน coverage อย่างตรงไปตรงมา |
| มองว่าเป็น "แค่ scraper" | จุดขายคือ analysis + ML + presentation ไม่ใช่การดึงข้อมูล |

---

**Next action:** เริ่ม Phase 1 — เขียน `collect.py` (robots check + rate-limit + cache) ดึง 1 หมวดทดสอบก่อน แล้วค่อยขยาย
