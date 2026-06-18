"""
Pipeline tests — run without any scraped data (data/ is git-ignored), so every
fixture is synthetic. Covers the parts that matter: __NEXT_DATA__ extraction,
the flatten/anonymize step, robots denylist enforcement, and the dashboard's
pure data helpers.
"""
import hashlib
import json

import pandas as pd
import pytest

import clean
import collect
from app import category_summary, opportunity_scores, price_bands

# --- a minimal but realistic gig payload ----------------------------------

PRODUCT_DATA = {
    "id": "gig-123",
    "snapshot": {
        "id": "gig-123",
        "title": "ออกแบบโลโก้",
        "tags": ["โลโก้", "แบรนด์"],
        "base_price": 500,
        "category": {"slug": "design-graphic", "title": "ออกแบบกราฟิก"},
        "subcategory": "logo",
        "packages": [
            {"name": "basic", "price": 500, "active": True, "delivery_times": 3},
            {"name": "pro", "price": 1500, "active": True, "delivery_times": 5},
            {"name": "retired", "price": 99, "active": False, "delivery_times": 1},
        ],
    },
    "stats": {
        "purchase_count": 7,
        "completion_rate": "0.9",
        "rating": {"overall_rating": "4.8", "count": 5},
    },
    "user": {"username": "someseller", "display_name": "Real Name", "about_me": "bio"},
}

NEXT_DATA_BLOB = {
    "props": {
        "pageProps": {
            "dehydratedState": {
                "queries": [
                    {"queryKey": ["PRODUCT_DETAIL", "gig-123"], "state": {"data": PRODUCT_DATA}}
                ]
            }
        }
    }
}


# --- collect.py -----------------------------------------------------------

def test_extract_next_data_roundtrips():
    html = (
        '<html><body><script id="__NEXT_DATA__" type="application/json">'
        + json.dumps(NEXT_DATA_BLOB, ensure_ascii=False)
        + "</script></body></html>"
    )
    assert collect.extract_next_data(html) == NEXT_DATA_BLOB


def test_extract_next_data_missing_returns_none():
    assert collect.extract_next_data("<html>no blob here</html>") is None


def test_allowed_enforces_denylist():
    fetcher = collect.PoliteFetcher({"base_url": "https://fastwork.co", "respect_robots": False})
    fetcher._disallow = ["/me/", "/profile", "/inbox"]
    assert fetcher.allowed("https://fastwork.co/user/foo/logo-1")
    assert fetcher.allowed("https://fastwork.co/sitemap-products-th.xml")
    assert not fetcher.allowed("https://fastwork.co/me/123")
    assert not fetcher.allowed("https://fastwork.co/profile")
    fetcher.close()


# --- clean.py -------------------------------------------------------------

def test_product_detail_extraction():
    assert clean._product_detail(NEXT_DATA_BLOB) == PRODUCT_DATA


def test_flatten_prices_use_active_packages_only():
    row = clean.flatten(PRODUCT_DATA)
    assert row["price_min"] == 500  # the 99 inactive package is ignored
    assert row["price_max"] == 1500
    assert row["n_packages"] == 2
    assert row["delivery_min_days"] == 3
    assert row["delivery_max_days"] == 5


def test_flatten_extracts_category_and_rating():
    row = clean.flatten(PRODUCT_DATA)
    assert row["category_slug"] == "design-graphic"
    assert row["rating_overall"] == pytest.approx(4.8)
    assert row["rating_count"] == 5
    assert row["purchase_count"] == 7


def test_flatten_anonymizes_seller():
    row = clean.flatten(PRODUCT_DATA)
    expected = hashlib.sha256(b"someseller").hexdigest()[:12]
    assert row["seller_hash"] == expected
    # no personal fields leak through
    assert "Real Name" not in row.values()
    assert "someseller" not in row.values()
    assert "display_name" not in row
    assert "about_me" not in row


def test_seller_hash_is_deterministic_and_distinct():
    assert clean._seller_hash("a") == clean._seller_hash("a")
    assert clean._seller_hash("a") != clean._seller_hash("b")
    assert clean._seller_hash(None) is None


# --- dashboard helpers ----------------------------------------------------

@pytest.fixture
def sample_df():
    return pd.DataFrame(
        {
            "gig_id": ["1", "2", "3", "4"],
            "category_slug": ["design-graphic", "design-graphic", "web", "web"],
            "price_min": [400.0, 800.0, 5000.0, 15000.0],
            "rating_overall": [5.0, 4.0, None, 5.0],
            "purchase_count": [2, 0, 1, 3],
        }
    )


def test_price_bands(sample_df):
    bands = price_bands(sample_df, "design-graphic")
    assert bands["n_gigs"] == 2
    assert bands["typical"] == 600.0  # median of 400, 800
    assert bands["budget"] <= bands["typical"] <= bands["premium"]


def test_price_bands_unknown_category(sample_df):
    assert price_bands(sample_df, "does-not-exist") is None


def test_category_summary_counts_and_sorts(sample_df):
    summary = category_summary(sample_df)
    assert set(summary.index) == {"design-graphic", "web"}
    assert summary.loc["web", "n_gigs"] == 2
    assert summary.loc["web", "total_sales"] == 4


def test_opportunity_scores_favors_high_price_low_supply(sample_df):
    # 'web' is pricier (5000/15000) and same supply as cheaper 'design-graphic'
    scored = opportunity_scores(category_summary(sample_df), w_price=1, w_supply=1, w_demand=1)
    assert scored.index[0] == "web"                 # best opportunity ranks first
    assert {"c_price", "c_low_competition", "c_demand", "opportunity"} <= set(scored.columns)
    # pure price weighting still favors the expensive category
    price_only = opportunity_scores(category_summary(sample_df), w_price=1, w_supply=0, w_demand=0)
    assert price_only.iloc[0]["median_price"] >= price_only.iloc[-1]["median_price"]
