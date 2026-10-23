"""Dated posts from a verified company website's own RSS/Atom feed.

Runs only for a website that passed identity verification and was not withheld as a shared or
group site. The feed must be declared by the homepage (``<link rel="alternate">``) and live on the
same registered domain. Each published item is one dated post with its own title, link (on the
same domain) and publish date taken from the item itself (RSS ``pubDate``/``dc:date``, Atom ``published``);
an "updated" or ``lastBuildDate`` time is never used as a publish date. Items with
no parseable date are dropped. One request (plus the cached robots.txt check) per company.
"""

from __future__ import annotations

import hashlib
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any

from .evidence import evidence, utc_now
from .gate import REQUEST_TIMEOUT_S, BudgetExhausted
from .website import USER_AGENT, _gated_open, _registered_domain, _robots_allowed

MAX_FEED_BYTES = 1_000_000
MAX_POSTS = 20
PLACEHOLDER_TITLE = re.compile(r"^(hello world!?|hei verden!?|protected:.*|private:.*|beskyttet:.*|sample page|eksempelside|lorem ipsum.*|post \d+( headline)?|test(post)?|untitled|uten tittel)$", re.I)
SOURCE_TYPE = "company_owned_feed"


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].casefold()


def _child_text(node: ET.Element, *names: str) -> str | None:
    for child in node:
        if _local(child.tag) in names and (child.text or "").strip():
            return child.text.strip()
    return None


def _atom_link(node: ET.Element) -> str | None:
    for child in node:
        if _local(child.tag) == "link" and child.get("href") and child.get("rel", "alternate") == "alternate":
            return child.get("href")
    return _child_text(node, "link")


def _parse_date(value: str | None) -> str | None:
    if not value:
        return None
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError, IndexError):
        parsed = None
    if parsed is None:
        try:
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    if parsed > datetime.now(timezone.utc):
        return None  # a future "publish" date is not a post that exists yet
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def parse_feed(raw: bytes, feed_url: str) -> list[dict[str, Any]]:
    """Return dated items (newest first) whose link stays on the feed's registered domain."""
    if re.search(rb"<!DOCTYPE|<!ENTITY", raw[:2000], re.I):
        return []  # refuse DTDs/entities outright
    root = ET.fromstring(raw)
    domain = _registered_domain(feed_url)
    items = []
    for node in root.iter():
        kind = _local(node.tag)
        if kind not in {"item", "entry"}:
            continue
        title = _child_text(node, "title")
        link = _atom_link(node) if kind == "entry" else _child_text(node, "link")
        date_raw = _child_text(node, "pubdate", "date") if kind == "item" else _child_text(node, "published")
        date = _parse_date(date_raw)
        if not (title and link and date) or PLACEHOLDER_TITLE.match(title.strip()):
            continue
        link = urllib.parse.urljoin(feed_url, link.strip())
        if urllib.parse.urlparse(link).scheme not in {"http", "https"} or _registered_domain(link) != domain:
            continue
        items.append({"title": re.sub(r"\s+", " ", title)[:300], "url": link, "published_at": date, "date_field": "pubDate" if kind == "item" else "published"})
    unique = {item["url"]: item for item in items}
    return sorted(unique.values(), key=lambda item: item["published_at"], reverse=True)[:MAX_POSTS]


def fetch_company_posts(org: str, website: dict[str, Any]) -> dict[str, Any]:
    """Return the ``company_posts`` evidence record for one company."""
    value = website.get("value") or {}
    assessment = value.get("identity_assessment") or {}
    site_url = value.get("final_url") or website.get("source_url") or "about:signalpost-company-posts"
    if website.get("status") != "available" or not assessment.get("publishable"):
        return evidence("company_posts", "not_applicable", SOURCE_TYPE, site_url, note="No verified company website to read posts from", source_row_key=org)
    feeds = value.get("feed_links") or []
    if not feeds:
        return evidence("company_posts", "not_found", SOURCE_TYPE, site_url, note="Verified website declares no RSS/Atom feed", source_row_key=org)
    feed_url = feeds[0]
    try:
        if not _robots_allowed(feed_url, REQUEST_TIMEOUT_S):
            return evidence("company_posts", "blocked", SOURCE_TYPE, feed_url, note="robots.txt disallows the feed", source_row_key=org)
        request = urllib.request.Request(feed_url, headers={"User-Agent": USER_AGENT, "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml"})
        with _gated_open(request, REQUEST_TIMEOUT_S) as response:
            raw = response.read(MAX_FEED_BYTES + 1)
            final_url = response.geturl()
    except BudgetExhausted as exc:
        return evidence("company_posts", "blocked", SOURCE_TYPE, feed_url, note=str(exc), source_row_key=org)
    except Exception as exc:
        return evidence("company_posts", "source_error", SOURCE_TYPE, feed_url, note=f"{type(exc).__name__}: {str(exc)[:160]}", source_row_key=org)
    retrieved_at = utc_now()
    sha = hashlib.sha256(raw).hexdigest()
    if len(raw) > MAX_FEED_BYTES or _registered_domain(final_url) != _registered_domain(site_url):
        return evidence("company_posts", "source_error", SOURCE_TYPE, feed_url, note="Feed oversized or redirected off the verified domain", retrieved_at=retrieved_at, content_sha256=sha, source_row_key=org)
    try:
        posts = parse_feed(raw, final_url)
    except ET.ParseError as exc:
        return evidence("company_posts", "source_error", SOURCE_TYPE, final_url, note=f"Feed is not valid XML: {str(exc)[:120]}", retrieved_at=retrieved_at, content_sha256=sha, source_row_key=org)
    if not posts:
        return evidence("company_posts", "not_found", SOURCE_TYPE, final_url, value={"posts": []}, note="Feed has no dated posts on the verified domain", retrieved_at=retrieved_at, content_sha256=sha, source_row_key=org)
    return evidence(
        "company_posts",
        "available",
        SOURCE_TYPE,
        final_url,
        value={"posts": posts, "latest_post_at": posts[0]["published_at"], "website": site_url},
        retrieved_at=retrieved_at,
        content_sha256=sha,
        source_row_key=org,
        note="Company-owned posts from the verified website's own feed; each date is the item's own publish date",
    )
