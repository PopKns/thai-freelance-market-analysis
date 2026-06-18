"""
Build the *publishable* dataset shipped with the deployed dashboard.

The full ``data/listings.parquet`` is gitignored on purpose: it carries each
gig's free-text ``title`` (the freelancer's own wording) plus a ``subcategory``
blob with image URLs — i.e. content we deliberately do NOT republish under the
project's aggregate-only / PDPA stance (see README §Ethics & Compliance).

This script strips those columns and writes ``data_public/listings_public.parquet``,
which IS committed (whitelisted in .gitignore) so Streamlit Community Cloud can
render the dashboard without the raw collection. What remains is anonymized,
non-copyrightable structured facts: category, price, rating, sales, delivery,
and an already-hashed seller id. The dashboard and anomaly screener use none of
the dropped columns, so functionality is unchanged.

Run:  python src/make_public_dataset.py
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "data" / "listings.parquet"
OUT = ROOT / "data_public" / "listings_public.parquet"

# free-text / non-aggregate columns we never republish
DROP_COLS = ["title", "subcategory", "tags"]


def build(src: Path = SRC, out: Path = OUT) -> pd.DataFrame:
    df = pd.read_parquet(src)
    public = df.drop(columns=[c for c in DROP_COLS if c in df.columns])
    out.parent.mkdir(parents=True, exist_ok=True)
    public.to_parquet(out, index=False)
    return public


if __name__ == "__main__":
    if not SRC.exists():
        raise SystemExit(f"no source dataset at {SRC} — run collect.py + clean.py first")
    public = build()
    print(f"wrote {OUT.relative_to(ROOT)}  ({len(public)} rows, {len(public.columns)} cols)")
    print("columns:", list(public.columns))
