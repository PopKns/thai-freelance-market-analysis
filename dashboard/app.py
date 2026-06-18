"""
Fastwork Market Intelligence — public dashboard.

Sidebar filters drive four tabs:
  1. Pricing advisor    — pick a category, see the budget / typical / premium bands.
  2. Demand map         — price vs. competition, to spot under-served niches.
  3. Opportunity finder — rank categories by price x low-competition x demand (tunable).
  4. Trust & anomaly    — the screener's most suspicious gigs, with reasons.

Run:  streamlit run dashboard/app.py

The pure data helpers (category_summary, price_bands, opportunity_scores) live at
module top so they can be unit-tested without launching Streamlit.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
# Prefer the full local dataset for development; fall back to the committed,
# title-stripped public dataset that ships with the deploy (Streamlit Cloud).
_FULL = ROOT / "data" / "listings.parquet"
_PUBLIC = ROOT / "data_public" / "listings_public.parquet"
DATA = _FULL if _FULL.exists() else _PUBLIC
SRC = str(ROOT / "src")
if SRC not in sys.path:  # make `ml.anomaly` importable when run via streamlit
    sys.path.insert(0, SRC)


# --- pure data helpers (testable without streamlit) -----------------------

def load_frame(path: Path = DATA) -> pd.DataFrame:
    return pd.read_parquet(path)


def category_summary(df: pd.DataFrame) -> pd.DataFrame:
    """Per-category supply, price bands, rating and total sales."""
    out = (
        df.groupby("category_slug")
        .agg(
            n_gigs=("gig_id", "size"),
            median_price=("price_min", "median"),
            p25=("price_min", lambda s: s.quantile(0.25)),
            p75=("price_min", lambda s: s.quantile(0.75)),
            median_rating=("rating_overall", "median"),
            total_sales=("purchase_count", "sum"),
        )
        .sort_values("n_gigs", ascending=False)
    )
    return out


def price_bands(df: pd.DataFrame, category_slug: str) -> dict | None:
    """Budget / typical / premium starting-price bands for one category."""
    s = df.loc[df["category_slug"] == category_slug, "price_min"].dropna()
    if s.empty:
        return None
    return {
        "n_gigs": int(len(s)),
        "budget": float(s.quantile(0.25)),
        "typical": float(s.median()),
        "premium": float(s.quantile(0.75)),
        "floor": float(s.min()),
        "ceiling": float(s.quantile(0.95)),
    }


def _norm(s: pd.Series) -> pd.Series:
    rng = s.max() - s.min()
    return (s - s.min()) / rng if rng else s * 0.0


def opportunity_scores(
    summary: pd.DataFrame, w_price: float = 1.0, w_supply: float = 1.0, w_demand: float = 1.0
) -> pd.DataFrame:
    """Score categories: high price + low competition + real demand = attractive.

    Each component is min-max normalized to 0..1 so the weights are comparable.
    Returns the summary with component + total `opportunity` columns, best first.
    """
    out = summary.copy()
    out["c_price"] = _norm(out["median_price"])
    out["c_low_competition"] = 1 - _norm(out["n_gigs"])
    out["c_demand"] = _norm(out["total_sales"])
    out["opportunity"] = (
        w_price * out["c_price"]
        + w_supply * out["c_low_competition"]
        + w_demand * out["c_demand"]
    )
    return out.sort_values("opportunity", ascending=False)


# --- streamlit UI ---------------------------------------------------------

TH_REASON = {
    "EXTREME_PRICE": "ราคาผิดปกติมากเทียบกับหมวด (อาจเป็นราคาปลอม/placeholder)",
    "SALES_NO_REVIEWS": "มียอดขายเยอะแต่ไม่มีรีวิว",
    "REVIEWS_NO_SALES": "มีรีวิวแต่ไม่มียอดขาย (อาจเป็นรีวิวปลอม)",
    "SELLER_SPAM": "ผู้ขายโพสต์งานซ้ำๆ จำนวนมากผิดปกติ",
}


def _th_reason(row) -> str:
    parts = [TH_REASON[f] for f in row.get("flags", []) if f in TH_REASON]
    if row.get("iforest_outlier"):
        parts.append("ชุดคุณสมบัติผิดปกติเชิงสถิติ (IsolationForest)")
    return "; ".join(parts) or "ไม่มีกฎใดติด"


def main() -> None:  # pragma: no cover - UI glue
    import streamlit as st

    st.set_page_config(page_title="ข้อมูลตลาดฟรีแลนซ์ไทย", layout="wide")

    if not DATA.exists():
        st.error("ยังไม่มีชุดข้อมูล — รัน `python src/collect.py` แล้วตามด้วย `python src/clean.py`")
        st.stop()

    df = load_frame()
    st.title("🇹🇭 ข้อมูลเชิงลึกตลาดฟรีแลนซ์ไทย (Fastwork)")
    st.caption(
        "ภาพรวมข้อมูลสาธารณะของ Fastwork แบบ anonymized — แสดงเฉพาะสถิติรวม "
        "เพื่อการศึกษา/วิจัย ไม่ได้มีส่วนเกี่ยวข้องกับ Fastwork"
    )

    # --- sidebar global filters ---
    with st.sidebar:
        st.header("🔎 ตัวกรอง")
        all_cats = sorted(df["category_slug"].dropna().unique())
        sel_cats = st.multiselect("หมวดหมู่", all_cats, default=all_cats)
        lo = int(df["price_min"].min())
        hi = int(df["price_min"].quantile(0.99))
        price_range = st.slider("ราคาเริ่มต้น (บาท)", lo, hi, (lo, hi), step=50)
        only_reviewed = st.checkbox("เฉพาะงานที่มีรีวิวอย่างน้อย 1", value=False)
        st.caption("ตัวกรองมีผลกับทุกแท็บ ยกเว้นแท็บความน่าเชื่อถือ ที่สแกนข้อมูลทั้งหมดเสมอ")

    fdf = df[df["category_slug"].isin(sel_cats)]
    fdf = fdf[fdf["price_min"].between(*price_range)]
    if only_reviewed:
        fdf = fdf[fdf["rating_count"].fillna(0) > 0]

    if fdf.empty:
        st.warning("ไม่มีงานที่ตรงกับตัวกรอง — ลองขยายเงื่อนไขในแถบด้านซ้าย")
        st.stop()

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("งาน (หลังกรอง)", f"{len(fdf):,}", delta=f"จาก {len(df):,}")
    c2.metric("จำนวนหมวด", fdf["category_slug"].nunique())
    c3.metric("ราคาเริ่มต้น (median)", f"฿{fdf['price_min'].median():,.0f}")
    c4.metric("สัดส่วนงานที่มีรีวิว", f"{(fdf['rating_count'].fillna(0) > 0).mean():.0%}")

    tab_advisor, tab_demand, tab_opp, tab_fraud = st.tabs(
        ["💰 แนะนำราคา", "📊 แผนที่ดีมานด์", "🎯 ค้นหาโอกาส", "🚩 ความน่าเชื่อถือ"]
    )

    with tab_advisor:
        st.subheader("ควรตั้งราคาเท่าไหร่ดี?")
        cats = sorted(fdf["category_slug"].dropna().unique())
        choice = st.selectbox("หมวดหมู่", cats)
        bands = price_bands(fdf, choice)
        if bands is None:
            st.warning("ยังไม่มีข้อมูลราคาสำหรับหมวดนี้")
        else:
            b1, b2, b3 = st.columns(3)
            b1.metric("ประหยัด (p25)", f"฿{bands['budget']:,.0f}")
            b2.metric("ทั่วไป (median)", f"฿{bands['typical']:,.0f}")
            b3.metric("พรีเมียม (p75)", f"฿{bands['premium']:,.0f}")
            st.caption(
                f"อ้างอิงจาก {bands['n_gigs']:,} งาน — "
                f"ราคาเริ่มต้นส่วนใหญ่อยู่ระหว่าง ฿{bands['floor']:,.0f} ถึง ฿{bands['ceiling']:,.0f}"
            )
            sub = fdf.loc[fdf["category_slug"] == choice, "price_min"].dropna()
            sub = sub[sub < sub.quantile(0.95)]
            if len(sub) >= 5:
                hist = pd.cut(sub, bins=min(20, sub.nunique())).value_counts().sort_index()
                chart_df = pd.DataFrame(
                    {"ราคา (บาท)": [round(iv.mid) for iv in hist.index], "จำนวนงาน": hist.values}
                )
                st.bar_chart(chart_df, x="ราคา (บาท)", y="จำนวนงาน", width="stretch")

    with tab_demand:
        st.subheader("ราคา เทียบกับ การแข่งขัน แยกตามหมวด")
        st.caption("มุมซ้ายบน = ราคาสูง + คู่แข่งน้อย = niche ที่น่าลงทุน")
        summary = category_summary(fdf)
        plot_df = summary.reset_index().rename(
            columns={"category_slug": "หมวดหมู่", "n_gigs": "จำนวนงาน", "median_price": "ราคา median"}
        )
        st.scatter_chart(
            plot_df, x="จำนวนงาน", y="ราคา median", color="หมวดหมู่", width="stretch"
        )
        table = summary.rename(
            columns={
                "n_gigs": "จำนวนงาน", "median_price": "ราคา median", "p25": "ราคา p25",
                "p75": "ราคา p75", "median_rating": "rating median", "total_sales": "ยอดขายรวม",
            }
        )
        table.index.name = "หมวดหมู่"
        st.dataframe(
            table.style.format(
                {
                    "ราคา median": "฿{:,.0f}", "ราคา p25": "฿{:,.0f}", "ราคา p75": "฿{:,.0f}",
                    "rating median": "{:.1f}", "ยอดขายรวม": "{:,.0f}",
                }
            ),
            width="stretch",
        )

    with tab_opp:
        st.subheader("โอกาสอยู่ตรงไหน?")
        st.caption("คะแนนสูง = น่าสนใจ: ราคาสูง + คู่แข่งน้อย + มีดีมานด์จริง — ปรับน้ำหนักได้")
        w1, w2, w3 = st.columns(3)
        wp = w1.slider("น้ำหนัก · ราคา", 0.0, 2.0, 1.0, 0.1)
        ws = w2.slider("น้ำหนัก · คู่แข่งน้อย", 0.0, 2.0, 1.0, 0.1)
        wd = w3.slider("น้ำหนัก · ดีมานด์", 0.0, 2.0, 1.0, 0.1)
        scored = opportunity_scores(category_summary(fdf), wp, ws, wd)
        bar_df = scored.reset_index().rename(
            columns={"category_slug": "หมวดหมู่", "opportunity": "คะแนนโอกาส"}
        )
        st.bar_chart(bar_df, x="หมวดหมู่", y="คะแนนโอกาส", width="stretch")
        opp_table = scored[["n_gigs", "median_price", "total_sales", "opportunity"]].rename(
            columns={
                "n_gigs": "จำนวนงาน", "median_price": "ราคา median",
                "total_sales": "ยอดขายรวม", "opportunity": "คะแนนโอกาส",
            }
        )
        opp_table.index.name = "หมวดหมู่"
        st.dataframe(
            opp_table.style.format(
                {"ราคา median": "฿{:,.0f}", "ยอดขายรวม": "{:,.0f}", "คะแนนโอกาส": "{:.2f}"}
            ),
            width="stretch",
        )

    with tab_fraud:
        st.subheader("คัดกรองความน่าเชื่อถือ / ความผิดปกติ")
        st.caption(
            "คัดกรองแบบ unsupervised บนข้อมูล **ทั้งหมด** (ไม่อิงตัวกรองราคา เพื่อให้ outlier ยังเห็นได้) "
            "— เป็นการ \"คัดให้คนตรวจ\" ไม่ใช่คำตัดสิน · ผิดปกติ ≠ ผิด"
        )
        from ml import anomaly

        res = anomaly.run_screening(df)
        res["เหตุผล"] = res.apply(_th_reason, axis=1)
        flagged = res[res["n_flags"] > 0]
        st.metric("งานที่ติดกฎคัดกรอง", f"{len(flagged):,}", delta=f"จาก {len(df):,}")
        fraud_table = res.head(25)[
            ["category_slug", "price_min", "purchase_count", "rating_count", "n_flags", "เหตุผล"]
        ].rename(
            columns={
                "category_slug": "หมวดหมู่", "price_min": "ราคาเริ่มต้น",
                "purchase_count": "ยอดขาย", "rating_count": "จำนวนรีวิว", "n_flags": "จำนวนกฎที่ติด",
            }
        )
        st.dataframe(
            fraud_table.style.format({"ราคาเริ่มต้น": "฿{:,.0f}"}),
            width="stretch",
        )


if __name__ == "__main__":
    main()
