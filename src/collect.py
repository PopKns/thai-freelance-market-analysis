"""
collect.py — fetch public Fastwork gig data, politely.

Fastwork is a Next.js app: category pages are JS-rendered tiles, but each gig
detail page ships its data as a server-rendered `__NEXT_DATA__` JSON blob (for
SEO). So instead of scraping rendered HTML we:

    1. read the products sitemap to enumerate gig URLs   (sitemap-products-th.xml)
    2. fetch each gig page (rate-limited, cached)
    3. extract the __NEXT_DATA__ JSON and cache it as structured data

clean.py then turns those JSON blobs into a tidy, anonymized dataset.

Every fetch goes through PoliteFetcher: robots.txt check -> rate limit -> disk
cache, so re-runs never re-hit the server.

Run standalone:
    python src/collect.py --sitemap        # list gig URLs from the products sitemap
    python src/collect.py                   # fetch up to config.max_gigs gigs into cache
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import urljoin, urlparse

import httpx

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config.json"

NEXT_DATA_RE = re.compile(
    r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.DOTALL
)


def load_config() -> dict:
    path = CONFIG_PATH if CONFIG_PATH.exists() else ROOT / "config.example.json"
    return json.loads(path.read_text(encoding="utf-8"))


class PoliteFetcher:
    """Rate-limited, robots-aware, disk-cached HTTP GET."""

    def __init__(self, cfg: dict):
        self.base_url = cfg["base_url"].rstrip("/")
        self.delay = float(cfg.get("rate_limit_seconds", 3))
        self.user_agent = cfg.get("user_agent", "fastwork-market-intel/0.1")
        self.respect_robots = cfg.get("respect_robots", True)
        self.cache_dir = ROOT / cfg.get("cache_dir", "data/cache")
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._last_request = 0.0
        self._client = httpx.Client(
            headers={"User-Agent": self.user_agent}, timeout=30, follow_redirects=True
        )
        self._disallow = self._load_robots()

    def _load_robots(self) -> list[str]:
        """Parse Disallow prefixes from robots.txt for User-agent: *.

        We do NOT use urllib.robotparser: (1) it fetches with a default UA that
        Cloudflare 403s here, and (2) its first-match logic mis-handles this
        file's `Allow: /` (it would wrongly allow the Disallow'd private paths).
        Honoring the explicit Disallow list ourselves matches the site's intent.
        """
        if not self.respect_robots:
            return []
        try:
            txt = self._client.get(urljoin(self.base_url, "/robots.txt")).text
        except Exception as exc:  # noqa: BLE001 - network best-effort
            print(f"[warn] could not read robots.txt ({exc}) — using empty denylist")
            return []
        disallow, in_star = [], False
        for line in txt.splitlines():
            line = line.split("#", 1)[0].strip()
            if not line or ":" not in line:
                continue
            field, value = (p.strip() for p in line.split(":", 1))
            field = field.lower()
            if field == "user-agent":
                in_star = value == "*"
            elif field == "disallow" and in_star and value:
                disallow.append(value.rstrip("*"))
        return disallow

    def allowed(self, url: str) -> bool:
        path = urlparse(url).path
        return not any(path.startswith(prefix) for prefix in self._disallow)

    def _cache_path(self, url: str, suffix: str) -> Path:
        key = hashlib.sha256(url.encode()).hexdigest()[:16]
        slug = (urlparse(url).path.strip("/").replace("/", "_") or "root")[:60]
        return self.cache_dir / f"{slug}__{key}.{suffix}"

    def _throttle(self) -> None:
        wait = self.delay - (time.monotonic() - self._last_request)
        if wait > 0:
            time.sleep(wait)
        self._last_request = time.monotonic()

    def get_text(self, url: str, suffix: str = "html") -> str | None:
        """Fetch a page as text, using the disk cache.

        Returns None for disallowed paths and for gigs that have since been
        removed (404/410) — those are expected in a 222k-row sitemap and must
        not crash a long collection run. Other HTTP/network errors propagate.
        """
        url = urljoin(self.base_url + "/", url)
        cache_path = self._cache_path(url, suffix)
        if cache_path.exists():
            return cache_path.read_text(encoding="utf-8")
        if not self.allowed(url):
            print(f"[skip] robots.txt disallows: {url}")
            return None
        self._throttle()
        resp = self._client.get(url)
        if resp.status_code in (404, 410):
            print(f"[gone] {resp.status_code} {url}")
            return None
        resp.raise_for_status()
        cache_path.write_text(resp.text, encoding="utf-8")
        print(f"[get] {url} -> cached ({len(resp.text)} bytes)")
        return resp.text

    def close(self) -> None:
        self._client.close()


def sitemap_urls(fetcher: PoliteFetcher, sitemap_url: str) -> list[str]:
    """Return all <loc> URLs from a sitemap (streamed, cached)."""
    xml = fetcher.get_text(sitemap_url, suffix="xml")
    if not xml:
        return []
    # strip namespace for simple tag matching
    xml = re.sub(r'xmlns="[^"]+"', "", xml, count=1)
    root = ET.fromstring(xml)
    return [loc.text.strip() for loc in root.iter("loc") if loc.text]


def extract_next_data(html: str) -> dict | None:
    """Pull the __NEXT_DATA__ JSON blob out of a Next.js page."""
    m = NEXT_DATA_RE.search(html)
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError:
        return None


def collect(cfg: dict, limit: int | None = None, seed: int = 42) -> None:
    fetcher = PoliteFetcher(cfg)
    raw_dir = ROOT / "data" / "gigs"
    raw_dir.mkdir(parents=True, exist_ok=True)
    try:
        gig_urls = sitemap_urls(fetcher, cfg["sitemaps"]["products"])
        print(f"[info] {len(gig_urls)} gig URLs in sitemap")
        limit = limit or cfg.get("max_gigs", 100)
        # seeded random sample for representativeness across the whole market
        if limit < len(gig_urls):
            random.Random(seed).shuffle(gig_urls)
            gig_urls = gig_urls[:limit]
        saved, total = 0, len(gig_urls)
        for i, url in enumerate(gig_urls, 1):
            if i % 100 == 0:
                print(f"[progress] {i}/{total} fetched, {saved} saved")
            try:
                html = fetcher.get_text(url, suffix="html")
                if not html:
                    continue
                data = extract_next_data(html)
                if data is None:
                    print(f"[warn] no __NEXT_DATA__ in {url}")
                    continue
                out = raw_dir / (hashlib.sha256(url.encode()).hexdigest()[:16] + ".json")
                out.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
                saved += 1
            except Exception as exc:  # noqa: BLE001 - one bad gig must not kill the run
                print(f"[error] {url}: {type(exc).__name__}: {exc}")
                continue
        print(f"[done] saved {saved} gig JSON blobs to {raw_dir}")
    finally:
        fetcher.close()


def main(argv: list[str]) -> None:
    parser = argparse.ArgumentParser(description="Collect Fastwork gig data politely.")
    parser.add_argument(
        "--sitemap", action="store_true", help="just list gig URLs from the products sitemap"
    )
    parser.add_argument("--limit", type=int, default=None, help="max gigs to fetch")
    parser.add_argument("--seed", type=int, default=42, help="sampling seed (reproducible)")
    args = parser.parse_args(argv)
    cfg = load_config()

    if args.sitemap:
        fetcher = PoliteFetcher(cfg)
        try:
            urls = sitemap_urls(fetcher, cfg["sitemaps"]["products"])
            print(f"{len(urls)} gig URLs")
            for u in urls[:10]:
                print(" ", u)
        finally:
            fetcher.close()
        return

    collect(cfg, limit=args.limit, seed=args.seed)


if __name__ == "__main__":
    main(sys.argv[1:])
