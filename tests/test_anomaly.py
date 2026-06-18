"""
Tests for the anomaly screener. The rule logic is proven on synthetic rows where
each rule is *designed* to fire — independent of whether the live random sample
happens to contain such cases.
"""
import pandas as pd

from ml import anomaly


def test_rule_flags_each_rule_fires():
    # one row engineered to trip each rule, plus a clean row
    feat = pd.DataFrame(
        {
            "price_z_in_cat": [5.0, 0.1, 0.0, 0.0, 0.0],
            "purchase_count_f": [0, 15, 0, 2, 1],
            "rating_count_f": [0, 0, 3, 1, 0],
            "seller_gig_count": [1, 1, 1, 9, 1],
        }
    )
    flags = anomaly.rule_flags(feat)
    assert flags.loc[0, "EXTREME_PRICE"]
    assert flags.loc[1, "SALES_NO_REVIEWS"]
    assert flags.loc[2, "REVIEWS_NO_SALES"]
    assert flags.loc[3, "SELLER_SPAM"]
    assert flags.loc[4, "n_flags"] == 0          # clean row trips nothing
    assert flags.loc[0, "flags"] == ["EXTREME_PRICE"]


def test_engineer_features_price_z_and_seller_count():
    df = pd.DataFrame(
        {
            "category_slug": ["a", "a", "a", "a"],
            "price_min": [100.0, 100.0, 100.0, 100000.0],
            "purchase_count": [0, 0, 0, 0],
            "rating_count": [0, 0, 0, 0],
            "completion_rate": [None, None, None, None],
            "n_packages": [1, 1, 1, 1],
            "seller_hash": ["s1", "s1", "s2", "s3"],
        }
    )
    feat = anomaly.engineer_features(df)
    assert feat["price_z_in_cat"].iloc[3] > 1.0          # the 100k gig stands out
    assert feat["seller_gig_count"].iloc[0] == 2          # s1 appears twice


def test_explain_lists_reasons():
    row = pd.Series({"flags": ["EXTREME_PRICE"], "iforest_outlier": True})
    text = anomaly.explain(row)
    assert "outlier for its category" in text
    assert "IsolationForest" in text
    assert anomaly.explain(pd.Series({"flags": [], "iforest_outlier": False})) == "no individual rule fired"


def test_run_screening_smoke():
    df = pd.DataFrame(
        {
            "gig_id": [str(i) for i in range(20)],
            "category_slug": ["a"] * 10 + ["b"] * 10,
            "price_min": [100.0] * 9 + [99999.0] + [500.0] * 10,
            "purchase_count": [0] * 20,
            "rating_count": [0] * 20,
            "completion_rate": [None] * 20,
            "n_packages": [1] * 20,
            "seller_hash": [f"s{i}" for i in range(20)],
        }
    )
    res = anomaly.run_screening(df, contamination=0.1)
    assert {"suspicion", "reason", "n_flags"} <= set(res.columns)
    # the ฿99,999 gig in category 'a' should be the most suspicious
    assert res.iloc[0]["price_min"] == 99999.0
