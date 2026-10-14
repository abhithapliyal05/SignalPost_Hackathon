"""Hiring signals from NAV's job vacancy feed, joined by organisation number.

The declared cache (data/cache/nav_ads.jsonl.gz, built by scripts/build_nav_cache.py) holds every
ad that was ACTIVE when it was built, with the employer organisation number from the ad detail.
At run start the feed is continued from the cache's last page so ads that became inactive are
dropped and new ads are seen. New ads only carry a business name in the feed header, so their
detail is fetched in-run only when that name exactly matches a batch company or one of its
subunits, and they are published only when the detail's employer orgnr confirms the match.

Ads are matched to a company through its own orgnr or the orgnr of one of its registered subunits
(job ads usually carry the subunit). Contact details are never stored or published.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import re
import threading
import time
import unicodedata
import urllib.error
import urllib.request
from collections import defaultdict
from pathlib import Path
from typing import Any, Callable, Iterable

from .evidence import evidence, utc_now
from .gate import GATE, REQUEST_TIMEOUT_S, BudgetExhausted

NAV_BASE = "https://pam-stilling-feed.nav.no"
NAV_PUBLIC_TOKEN = NAV_BASE + "/api/publicToken"
NAV_TERMS = "https://navikt.github.io/pam-stilling-feed/"
USER_AGENT = "signalpost-agent/0.1"
DEFAULT_CACHE_DIR = Path(__file__).resolve().parents[2] / "data" / "cache"
LEGAL_SUFFIXES = {"as", "asa", "ans", "da", "enk", "sa", "nuf", "ba", "ks", "stiftelsen", "sf", "iks"}


def normalize_name(value: Any) -> str:
    """Casefolded, accent-free name without a trailing legal-form suffix."""
    text = str(value or "").translate(str.maketrans({"ø": "o", "Ø": "O", "å": "a", "Å": "A", "æ": "ae", "Æ": "AE"}))
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().casefold()
    tokens = re.findall(r"[a-z0-9]+", text)
    while tokens and tokens[-1] in LEGAL_SUFFIXES:
        tokens.pop()
    return " ".join(tokens)


def _digits(value: Any) -> str | None:
    digits = re.sub(r"\D", "", str(value or ""))
    return digits if len(digits) == 9 else None


def compact_ad(raw: dict[str, Any], *, detail_url: str, retrieved_at: str, content_sha256: str) -> dict[str, Any]:
    """Keep the publishable, non-personal fields of an ad detail response."""
    ad = raw.get("ad_content") or {}
    employer = ad.get("employer") or {}
    return {
        "uuid": raw.get("uuid") or ad.get("uuid"),
        "status": raw.get("status"),
        "title": ad.get("title"),
        "jobtitle": ad.get("jobtitle"),
        "published": ad.get("published"),
        "updated": ad.get("updated"),
        "expires": ad.get("expires"),
        "application_due": ad.get("applicationDue"),
        "link": ad.get("link"),
        "source": ad.get("source"),
        "engagement_type": ad.get("engagementtype"),
        "extent": ad.get("extent"),
        "position_count": ad.get("positioncount"),
        "sector": ad.get("sector"),
        "occupations": [item.get("level2") or item.get("level1") for item in ad.get("occupationCategories") or [] if item],
        "work_locations": [
            {key: location.get(key) for key in ("city", "municipal", "county", "postalCode", "country")}
            for location in ad.get("workLocations") or []
        ],
        "employer_name": employer.get("name"),
        "employer_orgnr": _digits(employer.get("orgnr")),
        "employer_homepage": employer.get("homepage"),
        "sist_endret": raw.get("sistEndret"),
        "detail_url": detail_url,
        "retrieved_at": retrieved_at,
        "content_sha256": content_sha256,
    }


def _http_get(url: str, token: str | None, *, gated: bool) -> tuple[int, bytes]:
    if gated:
        refusal = GATE.acquire(url)
        if refusal:
            raise BudgetExhausted(refusal)
    headers = {"Accept": "application/json", "User-Agent": USER_AGENT}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_S if gated else 60) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, b""


def nav_token(*, gated: bool = False) -> tuple[str, str]:
    """NAV_FEED_TOKEN if set (private), else NAV's rotating public experimental token."""
    private = os.environ.get("NAV_FEED_TOKEN", "").strip()
    if private:
        return private, "private"
    status, body = _http_get(NAV_PUBLIC_TOKEN, None, gated=gated)
    match = re.search(rb"ey[A-Za-z0-9._-]+", body or b"")
    if status != 200 or not match:
        raise RuntimeError(f"NAV public token unavailable (HTTP {status})")
    return match.group(0).decode(), "public"


class JobsIndex:
    def __init__(self, cache_dir: str | Path = DEFAULT_CACHE_DIR) -> None:
        self.cache_dir = Path(cache_dir)
        self.state: dict[str, Any] = {}
        self.ads: dict[str, dict[str, Any]] = {}
        self.new_headers_by_name: dict[str, list[dict[str, Any]]] = defaultdict(list)
        self.removed: set[str] = set()
        self.refresh_report: dict[str, Any] = {"status": "not_run"}
        self.token: str | None = None
        self.available = False
        self._lock = threading.Lock()
        self._fetched: dict[str, dict[str, Any] | None] = {}
        ads_path = self.cache_dir / "nav_ads.jsonl.gz"
        state_path = self.cache_dir / "nav_feed_state.json"
        if ads_path.exists() and state_path.exists():
            self.state = json.loads(state_path.read_text(encoding="utf-8"))
            with gzip.open(ads_path, "rt", encoding="utf-8") as handle:
                for line in handle:
                    if line.strip():
                        row = json.loads(line)
                        self.ads[row["uuid"]] = row
            self.available = True
        self._by_orgnr: dict[str, list[str]] = defaultdict(list)
        for uuid, row in self.ads.items():
            if row.get("employer_orgnr"):
                self._by_orgnr[row["employer_orgnr"]].append(uuid)

    # -- run-start feed continuation ---------------------------------------------------------
    def refresh(self, *, max_pages: int = 60) -> dict[str, Any]:
        if not self.available:
            self.refresh_report = {"status": "no_cache"}
            return self.refresh_report
        try:
            self.token, token_kind = nav_token(gated=True)
        except (BudgetExhausted, RuntimeError, OSError) as exc:
            self.refresh_report = {"status": "token_unavailable", "error": str(exc)[:200]}
            return self.refresh_report
        page_path = (self.state.get("last_page") or {}).get("feed_url")
        pages = 0
        last_retrieved = None
        try:
            while page_path and pages < max_pages:
                status, body = _http_get(NAV_BASE + page_path, self.token, gated=True)
                if status != 200:
                    break
                page = json.loads(body)
                pages += 1
                last_retrieved = utc_now()
                for item in page.get("items", []):
                    entry = item.get("_feed_entry") or {}
                    uuid = entry.get("uuid") or item.get("id")
                    if entry.get("status") != "ACTIVE":
                        self.removed.add(uuid)
                        continue
                    self.removed.discard(uuid)
                    if uuid not in self.ads:
                        self.new_headers_by_name[normalize_name(entry.get("businessName"))].append({**item, "_retrieved_at": last_retrieved})
                page_path = page.get("next_url")
        except (BudgetExhausted, OSError, ValueError) as exc:
            self.refresh_report = {"status": "partial", "error": str(exc)[:200], "pages": pages}
        else:
            caught_up = page_path is None
            self.refresh_report = {"status": "caught_up" if caught_up else "page_limit", "pages": pages}
        self.refresh_report.update({
            "token_kind": token_kind,
            "cache_built_at": self.state.get("built_at"),
            "cached_active_ads": len(self.ads),
            "now_inactive": len(self.removed & set(self.ads)),
            "new_active_headers": sum(len(items) for items in self.new_headers_by_name.values()),
            "last_page_retrieved_at": last_retrieved,
        })
        return self.refresh_report

    # -- per-company lookup ------------------------------------------------------------------
    def _fetch_new(self, item: dict[str, Any]) -> dict[str, Any] | None:
        uuid = item.get("id")
        with self._lock:
            if uuid in self._fetched:
                return self._fetched[uuid]
        url = NAV_BASE + item["url"]
        status, body = _http_get(url, self.token, gated=True)
        row = None
        if status == 200:
            raw = json.loads(body)
            if raw.get("status") == "ACTIVE" and raw.get("ad_content"):
                row = compact_ad(raw, detail_url=url, retrieved_at=utc_now(), content_sha256=hashlib.sha256(body).hexdigest())
        with self._lock:
            self._fetched[uuid] = row
        return row

    def lookup(self, org: str, names: dict[str, str], subunits: Iterable[str]) -> dict[str, Any]:
        """Return the jobs evidence record for one company.

        ``names`` maps normalized names (legal name, subunit names) to the orgnr that carries them.
        """
        source_url = NAV_BASE + "/api/v1/feed"
        if not self.available:
            return evidence("jobs", "blocked", "nav_job_feed", source_url, note="NAV cache not built (run make cache)")
        if self.refresh_report.get("status") in {"token_unavailable", "not_run"}:
            note = f"NAV feed not reachable this run: {self.refresh_report.get('error') or self.refresh_report.get('status')}"
            return evidence("jobs", "source_error", "nav_job_feed", source_url, note=note)
        allowed = {org, *subunits}
        matched: dict[str, dict[str, Any]] = {}
        for orgnr in allowed:
            for uuid in self._by_orgnr.get(orgnr, []):
                if uuid not in self.removed:
                    matched[uuid] = {**self.ads[uuid], "matched_via": "organisation_number" if orgnr == org else f"subunit:{orgnr}", "snapshot": "declared_cache"}
        unconfirmed = 0
        budget_note = None
        for name in names:
            if not name:
                continue
            for item in self.new_headers_by_name.get(name, []):
                try:
                    row = self._fetch_new(item)
                except BudgetExhausted as exc:
                    budget_note = str(exc)
                    break
                except (OSError, ValueError):
                    unconfirmed += 1
                    continue
                if row and row.get("employer_orgnr") in allowed:
                    matched[row["uuid"]] = {**row, "matched_via": "organisation_number" if row["employer_orgnr"] == org else f"subunit:{row['employer_orgnr']}", "snapshot": "live"}
                elif row:
                    unconfirmed += 1
        ads = sorted(matched.values(), key=lambda row: (row.get("published") or "", row["uuid"]), reverse=True)
        value = {
            "active_ads": ads,
            "active_ad_count": len(ads),
            "name_matches_not_confirmed_by_orgnr": unconfirmed,
            "feed_refresh": {key: self.refresh_report.get(key) for key in ("status", "cache_built_at", "last_page_retrieved_at")},
        }
        content = hashlib.sha256(json.dumps([row["content_sha256"] for row in ads]).encode()).hexdigest()
        if ads:
            latest = max((row["retrieved_at"] for row in ads), default=None)
            return evidence("jobs", "available", "nav_job_feed", source_url, value=value, retrieved_at=latest, content_sha256=content, source_row_key=org, note=f"Active NAV job ads matched by employer orgnr; terms {NAV_TERMS}")
        if budget_note:
            return evidence("jobs", "blocked", "nav_job_feed", source_url, value=value, note=budget_note)
        return evidence("jobs", "not_found", "nav_job_feed", source_url, value=value, content_sha256=content, source_row_key=org, note="NAV feed checked: no active ads for this organisation or its registered subunits")
