"""Withhold a website that is a group's or a shared platform's, not this company's own.

A published site is withheld, together with its social links, when either holds:

  shared_domain      two or more registry entities declare the same registrable domain as their
                     homepage (a parent group, a chain, a housing association, a party)
  locale_section     the company's page is a country section of a non-.no site (``/no-no/``,
                     ``/nb/``): the domain belongs to a foreign parent

Withheld sites stay in the evidence record (``withheld_by``) so the decision can be audited, but
``identity_assessment.publishable`` is false, so no website, social link or site-derived fact is
published for the company. See IDENTITY_RESOLUTION.md.
"""

from __future__ import annotations

import re
import urllib.parse
from typing import Any

from .identity import _tokens
from .identity_index import IdentityIndex
from .website import _registered_domain

METHOD = "shared_or_group_site_guard_v1"
DOMAIN_HANDLE_METHODS = {"deterministic_name_org_evidence_v2", "strict_free_candidate_proof_v1"}
LOCALE_SEGMENT = re.compile(r"^/(?:no|nb|nn|no-no|nb-no|nn-no|norge|norway)(?:/|$)", re.I)


def site_scope_verdict(final_url: str, index: IdentityIndex) -> dict[str, Any]:
    parsed = urllib.parse.urlparse(final_url or "")
    domain = (_registered_domain(final_url or "") or "").casefold()
    declared_by = index.homepage_domains.get(domain, 0)
    reasons = []
    if declared_by >= 2:
        reasons.append(f"shared_domain: {declared_by} registry entities declare {domain}")
    if domain and not domain.endswith(".no") and LOCALE_SEGMENT.match(parsed.path or ""):
        reasons.append(f"locale_section: {parsed.path} on non-.no domain {domain}")
    return {"domain": domain, "declared_by": declared_by, "withheld": bool(reasons), "reasons": reasons}


def apply_site_scope_guard(website: dict[str, Any], index: IdentityIndex, profile: dict[str, Any] | None = None) -> dict[str, Any]:
    """Mutate and return ``website``: unpublish it when it is a shared or group site.

    With ``profile`` it also drops social links whose handle is not distinctive for the company."""
    value = website.get("value") or {}
    assessment = value.get("identity_assessment") or {}
    if website.get("status") != "available" or not assessment.get("publishable"):
        return website
    verdict = site_scope_verdict(value.get("final_url") or website.get("source_url") or "", index)
    value["site_scope_check"] = verdict
    if profile is not None and not verdict["withheld"]:
        kept = [link for link in value.get("social_links") or [] if social_handle_is_distinctive(profile, link.get("url"))]
        dropped = [link for link in value.get("social_links") or [] if link not in kept]
        if dropped:
            value["social_links_dropped_weak_handle"] = dropped
        # A handle that spells the verified domain (facebook.com/nordanger.no for nordanger.no) is the
        # site's own profile. Only for sites proven by name/orgnr on the page, not registry-declared
        # brand sites, where the domain may be a parent brand's.
        registry_row = (profile.get("evidence", {}).get("registry") or {}).get("value") or {}
        in_group = str(registry_row.get("erIKonsern") or "").casefold() == "true" or (profile.get("evidence", {}).get("group") or {}).get("status") == "available"
        if assessment.get("method") in DOMAIN_HANDLE_METHODS and not in_group:
            label = re.sub(r"[^a-z0-9]", "", verdict["domain"].rsplit(".", 1)[0])
            for link in value.get("discovered_social_links") or []:
                item = {"platform": link.get("platform"), "url": link.get("url")}
                if item not in kept and len(label) >= 5 and handle_spells_domain(link.get("url"), label):
                    kept.append({**item})
                    value.setdefault("social_links_from_domain_handle", []).append(item)
        value["social_links"] = kept
    if verdict["withheld"]:
        value["withheld_by"] = METHOD
        value["withheld_social_links"] = list(value.get("social_links") or [])
        value["social_links"] = []
        value["identity_assessment"] = {
            **assessment,
            "status": "related_or_uncertain",
            "publishable": False,
            "reasons": [*(assessment.get("reasons") or []), "withheld: " + "; ".join(verdict["reasons"])],
            "withheld_method": METHOD,
        }
    website["value"] = value
    return website


def social_handle_is_distinctive(profile: dict[str, Any], url: str) -> bool:
    """Stricter than the kit's handle test: a short token inside a long handle proves nothing.

    Accept when the handle carries the whole compacted legal name (five or more characters), or a distinctive token of at
    least five characters (or equals the whole name), or at least two name tokens one of which has four or more characters.
    """
    core = _tokens(profile.get("name"))
    handle = "".join(_tokens(urllib.parse.unquote(urllib.parse.urlparse(url or "").path)))
    if not core or not handle:
        return False
    compact = "".join(core)
    if compact == handle or (len(compact) >= 5 and compact in handle):
        return True
    present = [token for token in core if token in handle]
    return any(len(token) >= 5 for token in present) or (len(present) >= 2 and any(len(token) >= 4 for token in present))


def handle_spells_domain(url: str | None, label: str) -> bool:
    """The first path segment equals the domain label, optionally followed by its TLD."""
    path = urllib.parse.unquote(urllib.parse.urlparse(url or "").path).strip("/").split("/")
    first = path[0] if path and path[0] != "company" else (path[1] if len(path) > 1 else "")
    compact = re.sub(r"[^a-z0-9]", "", first.casefold().lstrip("@"))
    return compact in {label, label + "no", label + "as", label + "com"}
