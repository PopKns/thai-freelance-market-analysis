"""
analyze.py — "State of the Thai Freelance Market" summary from the tidy dataset.

Reads data/listings.parquet and prints the headline numbers + writes a few
figures to data/figures/. Designed to run on whatever has been collected so far.

    python src/analyze.py
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
PARQUET = ROOT / "data" / "listings.parquet"
FIG_DIR = ROOT / "data" / "figures"


def load() -> pd.DataFrame:
    if not PARQUET.exists():
        raise SystemExit("no dataset yet — run collect.py then clean.py first")
    return pd.read_parquet(PARQUET)


def category_summary(df: pd.DataFrame) -> pd.DataFrame:
    """Median price, spread, rating and competition per category."""
    g = df.groupby("category_slug")
    out = pd.DataFrame(
        {
            "n_gigs": g.size(),
            "median_price": g["price_min"].median(),
            "p25_price": g["price_min"].quantile(0.25),
            "p75_price": g["price_min"].quantile(0.75),
            "median_rating": g["rating_overall"].median(),
            "median_delivery_days": g["delivery_min_days"].median(),
            "total_purchases": g["purchase_count"].sum(),
        }
    )
    return out.sort_values("n_gigs", ascending=False)


def save_figures(summary: pd.DataFrame) -> None:
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print("[skip] matplotlib not installed — no figures")
        return
    FIG_DIR.mkdir(parents=True, exist_ok=True)
    top = summary.head(15)

    ax = top["median_price"].sort_values().plot.barh(figsize=(8, 6))
    ax.set_xlabel("Median starting price (THB)")
    ax.set_title("Fastwork: median starting price by category")
    ax.figure.tight_layout()
    ax.figure.savefig(FIG_DIR / "median_price_by_category.png", dpi=120)
    plt.close(ax.figure)

    ax = top["n_gigs"].sort_values().plot.barh(figsize=(8, 6), color="#c0504d")
    ax.set_xlabel("Number of gigs (competition)")
    ax.set_title("Fastwork: supply by category")
    ax.figure.tight_layout()
    ax.figure.savefig(FIG_DIR / "supply_by_category.png", dpi=120)
    plt.close(ax.figure)
    print(f"[done] figures -> {FIG_DIR}")


def main() -> None:
    df = load()
    print(f"\n=== Dataset: {len(df):,} gigs, {df['category_slug'].nunique()} categories ===\n")

    priced = df["price_min"].dropna()
    print(f"Starting price (THB): median {priced.median():,.0f} | "
          f"p25 {priced.quantile(.25):,.0f} | p75 {priced.quantile(.75):,.0f} | "
          f"max {priced.max():,.0f}")
    rated = df[df["rating_count"].fillna(0) > 0]
    print(f"Gigs with >=1 review: {len(rated):,} ({len(rated)/len(df):.0%})")

    summary = category_summary(df)
    print("\n--- By category ---")
    with pd.option_context("display.width", 200, "display.max_columns", None):
        print(summary.to_string())

    save_figures(summary)


if __name__ == "__main__":
    main()
