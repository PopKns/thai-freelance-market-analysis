"""
anomaly.py — a trust / fraud *screening* tool for the marketplace.

There are no fraud labels in public data, so this is deliberately **unsupervised
+ rule-based**, not a classifier. It surfaces gigs worth a human review by
combining:

  1. interpretable red-flag rules (price outliers, sales-without-reviews, etc.)
  2. an IsolationForest over per-category-normalized features (multivariate odd-ness)

into a single suspicion score — and every flagged gig comes with a plain-language
reason, so the output is auditable rather than a black box. That framing (triage,
not verdict) is exactly how a marketplace trust team would actually use it.

    python src/ml/anomaly.py            # print the top suspicious gigs + why

The pure functions (engineer_features, rule_flags, explain) are import-and-test
friendly; only run_screening / main touch sklearn and the parquet file.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent.parent
PARQUET = ROOT / "data" / "listings.parquet"

# --- rule thresholds (tunable, documented) --------------------------------
PRICE_Z_EXTREME = 4.0       # log-price this many SD above its category mean
SALES_NO_REVIEW_MIN = 10    # >= this many sales but zero reviews -> odd
SELLER_SPAM_GIGS = 8        # one seller posting >= this many near-identical gigs


# --- feature engineering (pure) -------------------------------------------

def engineer_features(df: pd.DataFrame) -> pd.DataFrame:
    """Add derived, mostly per-category-normalized signals used downstream."""
    out = df.copy()
    out["log_price"] = np.log1p(out["price_min"].fillna(0))

    # z-score of log price *within its own category* (catches the ฿2M outliers)
    grp = out.groupby("category_slug")["log_price"]
    mean, std = grp.transform("mean"), grp.transform("std").replace(0, np.nan)
    out["price_z_in_cat"] = ((out["log_price"] - mean) / std).fillna(0)

    pc = out["purchase_count"].fillna(0)
    rc = out["rating_count"].fillna(0)
    out["purchase_count_f"] = pc
    out["rating_count_f"] = rc
    out["has_review"] = (rc > 0).astype(int)
    out["reviews_per_sale"] = rc / (pc + 1)
    out["completion_rate_f"] = out["completion_rate"].fillna(0)
    out["n_packages_f"] = out["n_packages"].fillna(1)

    # how many gigs this (anonymized) seller has in the sample -> spam signal
    out["seller_gig_count"] = out["seller_hash"].map(out["seller_hash"].value_counts())
    return out


# --- interpretable red-flag rules (pure) ----------------------------------

def rule_flags(feat: pd.DataFrame) -> pd.DataFrame:
    """Boolean flag columns + a `flags` list per row. Expects engineer_features()."""
    f = pd.DataFrame(index=feat.index)
    f["EXTREME_PRICE"] = feat["price_z_in_cat"] > PRICE_Z_EXTREME
    f["SALES_NO_REVIEWS"] = (feat["purchase_count_f"] >= SALES_NO_REVIEW_MIN) & (
        feat["rating_count_f"] == 0
    )
    f["REVIEWS_NO_SALES"] = (feat["rating_count_f"] > 0) & (feat["purchase_count_f"] == 0)
    f["SELLER_SPAM"] = feat["seller_gig_count"] >= SELLER_SPAM_GIGS

    flag_cols = list(f.columns)
    f["flags"] = [
        [c for c in flag_cols if row[c]] for _, row in f.iterrows()
    ]
    f["n_flags"] = f[flag_cols].sum(axis=1)
    return f


REASONS = {
    "EXTREME_PRICE": "starting price is a wild outlier for its category (possible placeholder/fake price)",
    "SALES_NO_REVIEWS": "many recorded sales but zero reviews",
    "REVIEWS_NO_SALES": "has reviews despite zero recorded sales (possible fake reviews)",
    "SELLER_SPAM": "seller posts an unusually high number of near-identical gigs",
}


def explain(row: pd.Series) -> str:
    """Plain-language, deterministic reason string for a flagged gig."""
    parts = [REASONS[f] for f in row.get("flags", []) if f in REASONS]
    if row.get("iforest_outlier"):
        parts.append("statistically unusual feature combination (IsolationForest)")
    return "; ".join(parts) or "no individual rule fired"


# --- multivariate model + orchestration (needs sklearn) -------------------

FEATURE_COLS = [
    "price_z_in_cat", "purchase_count_f", "rating_count_f", "reviews_per_sale",
    "completion_rate_f", "n_packages_f", "seller_gig_count",
]


def score_anomalies(feat: pd.DataFrame, contamination: float = 0.05) -> pd.DataFrame:
    from sklearn.ensemble import IsolationForest

    X = feat[FEATURE_COLS].fillna(0).to_numpy()
    iso = IsolationForest(contamination=contamination, random_state=42)
    pred = iso.fit_predict(X)
    out = pd.DataFrame(index=feat.index)
    out["iforest_score"] = -iso.score_samples(X)   # higher = more anomalous
    out["iforest_outlier"] = pred == -1
    return out


def run_screening(df: pd.DataFrame, contamination: float = 0.05) -> pd.DataFrame:
    feat = engineer_features(df)
    flags = rule_flags(feat)
    scores = score_anomalies(feat, contamination)
    res = pd.concat(
        [df[["gig_id", "category_slug", "price_min", "purchase_count", "rating_count",
             "seller_hash"]], feat[["price_z_in_cat", "seller_gig_count"]],
         flags[["flags", "n_flags"]], scores], axis=1
    )
    # composite: rule hits dominate, IsolationForest breaks ties
    res["suspicion"] = res["n_flags"] + res["iforest_score"] / res["iforest_score"].max()
    res["reason"] = res.apply(explain, axis=1)
    return res.sort_values("suspicion", ascending=False)


def main() -> None:
    if not PARQUET.exists():
        raise SystemExit("no dataset — run collect.py then clean.py first")
    df = pd.read_parquet(PARQUET)
    res = run_screening(df)
    flagged = res[res["n_flags"] > 0]
    print(f"=== Screened {len(df):,} gigs — {len(flagged):,} hit >=1 rule "
          f"({len(flagged)/len(df):.1%}) ===\n")
    print("Rule hit counts:")
    print(pd.Series([f for fl in res["flags"] for f in fl]).value_counts().to_string() or "none")
    print("\nTop 15 most suspicious gigs:")
    cols = ["category_slug", "price_min", "purchase_count", "rating_count", "n_flags", "reason"]
    with pd.option_context("display.width", 200, "display.max_colwidth", 60):
        print(res.head(15)[cols].to_string(index=False))


if __name__ == "__main__":
    main()
