# Fastwork Market Intelligence

![CI](https://github.com/PopKns/thai-freelance-market-analysis/actions/workflows/ci.yml/badge.svg)

**Data pipeline แบบ end-to-end (production-minded)** ที่เปลี่ยน "ตลาดฟรีแลนซ์ไทย" ให้เป็น insight:
เก็บ gig สาธารณะจาก Fastwork (resilient + resumable) → ETL ทำความสะอาด + anonymize → parquet →
วิเคราะห์ว่าตลาดหน้าตาเป็นยังไง (ราคา median ต่อหมวด, สกิลไหนจ่ายดี, หมวดไหนแข่งเดือด) → ต่อยอดเป็น
ML prototype เชิงสำรวจ (คัดกรอง gig ที่ควรตรวจแบบ unsupervised) — มี unit tests + CI

โปรเจกต์เดี่ยวเชิง portfolio ที่น่าจะเป็นประโยชน์กับ:
- **นักวิเคราะห์ / สาย tinker** — ชุดข้อมูลตลาดฟรีแลนซ์ไทยที่สะอาดและทำซ้ำได้ (reproducible)
- **ฟรีแลนซ์ & ผู้ว่าจ้าง** — เครื่องมือแนะนำราคา (pricing advisor) + dashboard ดูดีมานด์
- **ทีม marketplace** — แนวคิด prototype คัดกรองความผิดปกติเบื้องต้น (triage)

> **[`FINDINGS.md`](./FINDINGS.md)** — สรุปผลทั้งหมดในหน้าเดียว (ข้อมูลบอกอะไรบ้าง)
> [`BLUEPRINT.md`](./BLUEPRINT.md) — แผนงานเต็ม

## หลักการออกแบบ

- **เก็บข้อมูลอย่างเคารพกติกา** — ทำตาม `robots.txt`, จำกัด rate, cache ทุกหน้า,
  เก็บเฉพาะ field สาธารณะ, **ไม่เก็บ PII** (seller ถูกแปลงเป็น hash)
- **Snapshot ไม่ใช่ realtime** — เก็บเป็นชุดต่อสัปดาห์ก็พอสำหรับวิเคราะห์ ไม่กวนเซิร์ฟเวอร์เขา
- **ทำซ้ำได้** — clone, `pip install -r requirements.txt`, รันแต่ละ stage แยกได้
- **เน้น insight มากกว่า raw data** — สิ่งที่ส่งมอบคือ "ความเข้าใจ" ไม่ใช่กอง JSON

## สถาปัตยกรรม

```
Fastwork ──▶ collect.py ──▶ clean.py ──▶ analyze.py / report.ipynb ──▶ dashboard/
(สาธารณะ)    จำกัด rate     normalize     ชาร์ต + สถิติ                  หน้าเว็บสาธารณะ
             + เช็ค robots   + anonymize        │
                                                └──▶ src/ml/ (triage ความผิดปกติ — unsupervised)
```

## จุดเด่นด้านวิศวกรรมข้อมูล (Data Engineering highlights)

ส่วนที่หนักสุดของโปรเจคคือ **pipeline การเก็บและแปลงข้อมูล** ที่ออกแบบให้ทนทานและทำซ้ำได้จริง:

- **Ingestion ที่ทนทาน (`collect.py`)** — robots-aware (parse `Disallow` เป็น denylist เองเพราะ
  Python `robotparser` จัดการ `Allow: /` ผิด + เว็บอยู่หลัง Cloudflare ที่บล็อก default UA),
  จำกัด rate, **cache ลงดิสก์ → idempotent** (รันซ้ำไม่ยิงซ้ำ), **resumable** (skip ของที่มีแล้ว),
  และ **ทน failure รายตัว** (กรอง 404/410 + per-record try/except → gig เสีย 1 อันไม่ล้มทั้ง run 3,000)
- **Source-aware extraction** — Fastwork เป็น Next.js SPA จึงดึง data จาก `__NEXT_DATA__`
  (JSON ที่ server render) แทนการ parse HTML ที่เปราะ
- **ETL → tidy schema** (`clean.py`) — flatten JSON ซ้อน, **anonymize PII เป็น hash**, เขียนเป็น
  **parquet** (columnar) พร้อม dedup
- **Seeded random sampling** — สุ่ม sample (~1.3% ของ 222k URL จาก products sitemap) ด้วย seed คงที่ → ทำซ้ำได้
- **Reproducible & config-driven** — แยก stage รันเดี่ยวได้, ตั้งค่าผ่าน `config.json`
- **Unit tests + CI** — `pytest` (synthetic fixtures, รัน offline — เทสต์ตรรกะโค้ด ไม่ใช่คุณภาพข้อมูล runtime), `ruff`, GitHub Actions

```
collect (ingest, resilient) ──▶ clean (ETL, anonymize) ──▶ parquet ──▶ analyze / serve / ML
```

## เริ่มใช้งาน (Quickstart)

รัน dashboard ได้ทันทีด้วย dataset ตัวอย่าง (sanitized) ที่ติดมากับ repo:

```bash
pip install -r requirements.txt        # deps เฉพาะ runtime ของ dashboard
streamlit run dashboard/app.py          # 4 แท็บ: pricing advisor · demand map · opportunity finder · trust/anomaly (+ sidebar filters)
```

อยากรัน pipeline เก็บข้อมูลเองตั้งแต่ต้น (collect → clean → analyze):

```bash
pip install -r requirements-dev.txt     # runtime + httpx / matplotlib / notebook / pytest / ruff
cp config.example.json config.json      # ปรับ rate-limit & ขนาด sample

python src/collect.py --sitemap         # ดู gig URL จาก products sitemap
python src/collect.py --limit 200       # ดึง gig ลง data/gigs/ (จำกัด rate, cache)
python src/clean.py                     # -> data/listings.parquet (anonymized, full)
python src/make_public_dataset.py        # -> data_public/listings_public.parquet (ตัด title/ข้อความฟรีแลนซ์)

python src/ml/anomaly.py                 # triage ความผิดปกติ — จัดอันดับ gig ที่ควรตรวจ + เหตุผล
jupyter notebook notebooks/report.ipynb # รายงาน "State of the Market" ฉบับเขียน
```

> dataset เต็ม (`data/listings.parquet`) มีคอลัมน์ `title` = ข้อความที่ฟรีแลนซ์เขียนเอง จึง **ไม่ commit** ตามนโยบาย aggregate-only;
> สิ่งที่ deploy/commit คือ `data_public/listings_public.parquet` ที่ตัดข้อความอิสระทั้งหมดออก เหลือแต่ตัวเลข+หมวดหมู่ (seller เป็น hash)

Notebook: [`report.ipynb`](./notebooks/report.ipynb) (รายงานตลาด) และ
[`fraud_explore.ipynb`](./notebooks/fraud_explore.ipynb) (คัดกรองความน่าเชื่อถือ/ความผิดปกติ)

แต่ละหน้า gig เป็น Next.js app — เราอ่าน data จาก `__NEXT_DATA__` (JSON ที่ server render มาให้)
ไม่ใช่ scrape จาก HTML ที่ render แล้ว; seller ถูก anonymize เป็น hash และไม่เก็บ field ส่วนตัวใดๆ

## การพัฒนา (Development)

```bash
pip install -r requirements-dev.txt
ruff check src/ dashboard/ tests/    # lint
python -m pytest tests/ -q           # 16 tests, รันได้แบบ offline ล้วน (ไม่ต้องมีข้อมูลที่ scrape)
```

Test ใช้ synthetic fixture จึงผ่านได้โดยไม่ต้องมีข้อมูลจริง และรันใน CI ทุก push

## สถานะ

ครบ Phase 1–3: เก็บข้อมูล → วิเคราะห์ & dashboard → ML prototype triage ความผิดปกติ
ชุดข้อมูล ~2,900 gig; 16 tests, CI เขียว — แผนงาน & ผลลัพธ์ดูที่ [`BLUEPRINT.md`](./BLUEPRINT.md)
และ [`FINDINGS.md`](./FINDINGS.md)

## จริยธรรม & การปฏิบัติตามกติกา (Ethics & Compliance)

โปรเจคนี้ตรวจสอบกฎของเว็บต้นทาง **ก่อน** เริ่มเก็บข้อมูล และทุกการตัดสินใจด้านการออกแบบด้านล่าง
มาจากการตรวจสอบนั้นโดยตรง

**robots.txt** — Fastwork อนุญาตให้ crawl (`Allow: /`) และห้ามเฉพาะ path ส่วนตัว/บัญชี
(`/me/*`, `/profile`, `/inbox`, `/comingsoon`, `/method-refetch-category`)
ตัว collector เคารพ denylist นี้อย่างชัดเจนและไม่แตะ path เหล่านั้นเลย

**Terms of Service** — ข้อตกลงการใช้งานของแพลตฟอร์ม **ไม่มีข้อห้าม scraping / crawling /
automated access** เลย และข้อตกลงนั้นผูกพันเฉพาะ *ผู้ใช้งานที่สมัครบัญชีและกดยอมรับ* —
โปรเจคนี้เก็บข้อมูลในฐานะ visitor นิรนามผ่าน HTTP ปกติ ไม่ล็อกอินและไม่สมัครบัญชี

**ข้อจำกัดจริง 3 ข้อที่เราออกแบบเพื่อรองรับ**

| ข้อจำกัด | โปรเจคนี้ทำตามยังไง |
| --- | --- |
| **PDPA / ข้อมูลส่วนบุคคล** | seller ถูกแปลงเป็น hash ตั้งแต่ขั้น `clean.py` — ทิ้งชื่อ, username, รูป, ข้อความ "about me" เก็บแต่ field ตัวเลข/ตลาด |
| **ลิขสิทธิ์ / IP** (ข้อความ gig & รูปผลงานเป็นของฟรีแลนซ์) | เผยแพร่เฉพาะ **สถิติแบบ aggregate** (เช่น ราคา median ต่อหมวด) ไม่ republish listing/คำอธิบาย/รูปดิบ และ cache ดิบถูก git-ignore |
| **พ.ร.บ. คอมพิวเตอร์ พ.ศ. 2550** | ดึงเฉพาะหน้าสาธารณะผ่าน HTTP ปกติ ไม่ bypass auth และเคารพ robots denylist |

**ขอบเขตการทำงาน**

- จำกัด rate (ปกติ 3 วิ/request) และ cache ลงดิสก์ → รันซ้ำไม่ยิงเซิร์ฟเวอร์ซ้ำ
- เป็น snapshot ไม่ใช่ feed สด
- มีช่องทาง takedown ชัดเจน: ชุดข้อมูล/การวิเคราะห์นี้จะถูกลบเมื่อมีการร้องขอผ่าน
  `support@fastwork.co` หรือเปิด issue ใน repo นี้

โปรเจคนี้เป็นงานวิจัย/เพื่อการศึกษาในเชิง portfolio ไม่ได้มีส่วนเกี่ยวข้องหรือได้รับการรับรองจาก
บริษัท เช้นจ์ซี จำกัด (Fastwork) และไม่ถือเป็นคำปรึกษาทางกฎหมาย
