"""
clean.py — turn cached gig JSON blobs into one tidy, anonymized dataset.

Reads data/gigs/*.json (each a Next.js __NEXT_DATA__ blob), pulls the
PRODUCT_DETAIL payload, flattens the fields we care about, and **anonymizes the
seller** (username -> short hash). No names, photos, or "about me" text are kept.

    python src/clean.py        # -> data/listings.parquet (+ data/listings_preview.csv)
"""
from __future__ import annotations

import glob
import hashlib
import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
GIGS_DIR = ROOT / "data" / "gigs"
OUT_PARQUET = ROOT / "data" / "listings.parquet"
OUT_PREVIEW = ROOT / "data" / "listings_preview.csv"


def _seller_hash(username: str | None) -> str | None:
    if not username:
        return None
    return hashlib.sha256(username.encode()).hexdigest()[:12]


def _to_float(v) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _product_detail(blob: dict) -> dict | None:
    try:
        queries = blob["props"]["pageProps"]["dehydratedState"]["queries"]
    except (KeyError, TypeError):
        return None
    for q in queries:
        if q.get("queryKey", [None])[0] == "PRODUCT_DETAIL":
            return q.get("state", {}).get("data")
    return None


def flatten(data: dict) -> dict | None:
    snap = data.get("snapshot") or {}
    if not snap:
        return None
    packages = [p for p in (snap.get("packages") or []) if p.get("active")]
    prices = [p["price"] for p in packages if isinstance(p.get("price"), (int, float))]
    deliveries = [
        p["delivery_times"] for p in packages if isinstance(p.get("delivery_times"), (int, float))
    ]
    stats = data.get("stats") or {}
    rating = stats.get("rating") or {}
    category = snap.get("category") or {}

    return {
        "gig_id": snap.get("id") or data.get("id"),
        "category_slug": category.get("slug"),
        "category_title": category.get("title"),
        "subcategory": snap.get("subcategory"),
        "title": snap.get("title"),
        "n_packages": len(packages),
        "price_min": min(prices) if prices else _to_float(snap.get("base_price")),
        "price_max": max(prices) if prices else None,
        "base_price": _to_float(snap.get("base_price")),
        "delivery_min_days": min(deliveries) if deliveries else None,
        "delivery_max_days": max(deliveries) if deliveries else None,
        "rating_overall": _to_float(rating.get("overall_rating")),
        "rating_count": rating.get("count"),
        "purchase_count": stats.get("purchase_count"),
        "completion_rate": _to_float(stats.get("completion_rate")),
        "n_tags": len(snap.get("tags") or []),
        "tags": "|".join(snap.get("tags") or []),
        "seller_hash": _seller_hash((data.get("user") or {}).get("username")),
    }


def build() -> pd.DataFrame:
    rows = []
    for path in sorted(glob.glob(str(GIGS_DIR / "*.json"))):
        blob = json.loads(Path(path).read_text(encoding="utf-8"))
        data = _product_detail(blob)
        if not data:
            continue
        row = flatten(data)
        if row and row.get("gig_id"):
            rows.append(row)
    return pd.DataFrame(rows).drop_duplicates(subset="gig_id")


def main() -> None:
    df = build()
    if df.empty:
        print("[warn] no gigs parsed — run collect.py first")
        return
    OUT_PARQUET.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(OUT_PARQUET, index=False)
    df.head(50).to_csv(OUT_PREVIEW, index=False)
    print(f"[done] {len(df)} gigs -> {OUT_PARQUET}")
    print(df[["category_slug", "price_min", "rating_overall", "purchase_count"]].describe(include="all").to_string())


if __name__ == "__main__":
    main()
