#!/usr/bin/env python3
"""Build the declared NAV job-ad cache (data/cache/nav_ads.jsonl.gz).

Source: NAV's job vacancy feed (https://navikt.github.io/pam-stilling-feed/), used under NAV's API
terms. The feed is read from ``--days`` back (an ad is never active for more than six months), the
latest header per ad is kept, and the detail entry of every ACTIVE ad is fetched once. Each cached ad
keeps its own detail URL, real retrieval time and SHA-256 of the raw detail response.

Contact details (contactList) and free-text descriptions are not stored, so inactive ads never
expose contact information. The run (src/norway_company_agent/jobs.py) continues the feed from the
page recorded in data/cache/nav_feed_state.json and drops ads that have since become inactive.

Token: NAV_FEED_TOKEN if set, else NAV's public experimental token fetched at start.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from norway_company_agent.jobs import NAV_BASE, compact_ad, nav_token  # noqa: E402


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def get(url: str, token: str, headers: dict[str, str] | None = None, attempts: int = 3) -> tuple[int, bytes, dict[str, str]]:
    last: Exception | None = None
    for attempt in range(attempts):
        request = urllib.request.Request(url, headers={"Accept": "application/json", "Authorization": f"Bearer {token}", "User-Agent": "signalpost-agent/0.1", **(headers or {})})
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                return response.status, response.read(), dict(response.headers)
        except urllib.error.HTTPError as exc:
            if exc.code in {304, 404, 410}:
                return exc.code, b"", dict(exc.headers or {})
            last = exc
        except Exception as exc:  # network hiccup: back off and retry
            last = exc
        time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"{url}: {last}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=183)
    parser.add_argument("--out", default="data/cache")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--max-pages", type=int, default=2000)
    args = parser.parse_args()

    token, token_kind = nav_token()
    since = datetime.now(timezone.utc) - timedelta(days=args.days)
    headers: dict[str, dict] = {}
    page_url = NAV_BASE + "/api/v1/feed"
    request_headers = {"If-Modified-Since": format_datetime(since, usegmt=True)}
    last_page = None
    pages = 0
    while page_url and pages < args.max_pages:
        status, body, _ = get(page_url, token, request_headers)
        request_headers = {}
        if status != 200:
            break
        page = json.loads(body)
        pages += 1
        last_page = {"feed_url": page.get("feed_url"), "id": page.get("id"), "retrieved_at": utc_now()}
        for item in page.get("items", []):
            headers[item["id"]] = item
        page_url = NAV_BASE + page["next_url"] if page.get("next_url") else None
        if pages % 50 == 0:
            print(f"pages {pages}, ads seen {len(headers):,}", flush=True)
    active = [item for item in headers.values() if (item.get("_feed_entry") or {}).get("status") == "ACTIVE"]
    print(f"feed pages {pages}, ads seen {len(headers):,}, active {len(active):,}", flush=True)

    def detail(item: dict) -> dict | None:
        url = NAV_BASE + item["url"]
        try:
            status, body, _ = get(url, token)
        except RuntimeError as exc:
            return {"error": str(exc), "uuid": item["id"]}
        if status != 200:
            return None
        raw = json.loads(body)
        if raw.get("status") != "ACTIVE" or not raw.get("ad_content"):
            return None
        return compact_ad(raw, detail_url=url, retrieved_at=utc_now(), content_sha256=hashlib.sha256(body).hexdigest())

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        rows = [row for row in pool.map(detail, active) if row]
    errors = [row for row in rows if "error" in row]
    ads = sorted((row for row in rows if "error" not in row), key=lambda row: row["uuid"])
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    with gzip.open(out / "nav_ads.jsonl.gz", "wt", encoding="utf-8", compresslevel=9) as handle:
        for row in ads:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")
    state = {
        "source": "https://pam-stilling-feed.nav.no/api/v1/feed",
        "terms": "https://navikt.github.io/pam-stilling-feed/ (NAV API terms of use)",
        "token_kind": token_kind,
        "built_at": utc_now(),
        "window_days": args.days,
        "feed_pages_read": pages,
        "ads_seen": len(headers),
        "active_headers": len(active),
        "active_ads_cached": len(ads),
        "ads_with_employer_orgnr": sum(1 for row in ads if row.get("employer_orgnr")),
        "detail_errors": len(errors),
        "last_page": last_page,
    }
    (out / "nav_feed_state.json").write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(state, indent=2))


if __name__ == "__main__":
    main()
