"""Publish a registry-declared website the name-based gate could not confirm.

The starter kit publishes a registry-listed homepage only when the legal name (or orgnr) appears
on it. Small companies often trade under a brand ("KVANT" for RUNAR KVANT AS), so many correct
sites fail that test. The company itself declared the homepage to the Brønnøysund register, which
is strong evidence on its own. This rule accepts such a site only when every check below holds on
the snapshot the kit already fetched (no extra requests):

  unique_domain     no other entity in the registry bulk lists the same registrable domain
  not_group         the company is not a group member (groups share and redirect domains)
  same_domain       the fetched page's final domain equals the declared domain, or it forwards to a
                    domain no other entity declares that also carries the legal name
  live_content      not parked, expired, for-sale or an empty server page, with real captured text
                    (title, description and page text together)
  no_foreign_orgnr  no valid organisation number other than the company's own (or its subunits)
                    appears in the captured text
  name_in_domain    a distinctive legal-name token (not a generic word), or the whole compacted legal
                    name ("SK DATA" -> skdata), is in the domain label

Otherwise the kit's verdict stands. See IDENTITY_RESOLUTION.md.
"""

from __future__ import annotations

import re
from typing import Any

from .identity import _tokens, assess_social_identity
from .identity_index import IdentityIndex, homepage_domain
from .site_verify import PARKED_MARKERS, orgnr_mentions
from .website import _registered_domain

METHOD = "registry_declared_unique_domain_v1"
EXTRA_DEAD_MARKERS = (
    "has expired", "domain has expired", "domenet har utløpt", "index of /", "account suspended",
    "this site can't be reached", "website is no longer available", "nettstedet er stengt",
)
GENERIC_TOKENS = {
    "invest", "investering", "holding", "holdings", "eiendom", "eiendommer", "norge", "norway", "norsk",
    "norwegian", "group", "gruppen", "consulting", "consult", "service", "services", "trading", "handel",
    "drift", "utvikling", "bygg", "transport", "regnskap", "kapital", "capital", "management", "partner",
    "partners", "selskap", "selskapet", "firma", "company", "media", "design", "data", "tech", "nordic",
    "nord", "sor", "vest", "ost", "bolig", "boligsameie", "sameie", "borettslag", "brl", "foreningen",
    "forening", "lag", "klubb", "senter", "team", "prosjekt", "solutions", "systems", "energi", "eiendomsselskap",
}
MIN_TEXT_CHARS = 150
NATIONAL_SUFFIX = re.compile(r"\b(NORWAY|NORGE|NORDIC|NORDICS|SCANDINAVIA|NORDEN)\b", re.I)


def _captured_text(value: dict[str, Any]) -> str:
    parts = [value.get("title"), value.get("description"), value.get("main_text_excerpt"), value.get("identity_text_excerpt")]
    for page in value.get("pages") or []:
        parts.extend([page.get("title"), page.get("main_text_excerpt"), page.get("identity_text_excerpt")])
    rendered = value.get("js_fallback") or {}
    parts.extend([rendered.get("title"), rendered.get("main_text_excerpt")])
    return " ".join(str(part) for part in parts if part)


def assess_registry_declared(profile: dict[str, Any], website: dict[str, Any], index: IdentityIndex) -> dict[str, Any]:
    """Return {"publishable": bool, "checks": {...}, "reason": str}."""
    org = profile["organisation_number"]
    value = website.get("value") or {}
    raw = (profile.get("evidence", {}).get("registry") or {}).get("value") or {}
    declared = homepage_domain(profile.get("website"))
    final_domain = (_registered_domain(value.get("final_url") or "") or "").casefold()
    text = _captured_text(value)
    lowered = text.casefold()
    subunits = {
        str(item.get("organisation_number"))
        for item in ((profile.get("evidence", {}).get("locations") or {}).get("value") or {}).get("locations") or []
        if item.get("organisation_number")
    }
    foreign = sorted({item["orgnr"] for item in orgnr_mentions(text) if item["orgnr"] not in {org, *subunits}})
    core = _tokens(profile.get("name"))
    distinctive = [token for token in core if len(token) >= 3 and token not in GENERIC_TOKENS]
    # The whole compacted name counts too ("SK DATA" -> skdata), unless every token is generic.
    compact_name = "".join(core) if any(token not in GENERIC_TOKENS for token in core) else ""

    def carries_name(domain: str | None) -> bool:
        label = re.sub(r"[^a-z0-9]", "", (domain or "").rsplit(".", 1)[0])
        return bool(label) and (any(token in label for token in distinctive) or (len(compact_name) >= 5 and compact_name in label))

    # A declared domain may forward to a brand domain (runarkvant.no -> kvant.no). Accept the
    # forward only when the target is not declared by any other entity and also carries the name.
    redirect_ok = bool(final_domain) and index.homepage_domains.get(final_domain, 0) == 0 and carries_name(final_domain)
    in_group = str(raw.get("erIKonsern") or "").casefold() == "true" or (profile.get("evidence", {}).get("group") or {}).get("status") == "available"
    checks = {
        "unique_domain": bool(declared) and index.homepage_domains.get(declared, 0) == 1,
        "not_group": not in_group,
        "same_domain": bool(declared) and (final_domain == declared or redirect_ok),
        "live_content": len(text) >= MIN_TEXT_CHARS
        and not any(marker in lowered for marker in (*PARKED_MARKERS, *EXTRA_DEAD_MARKERS)),
        "no_foreign_orgnr": not foreign,
        "name_in_domain": carries_name(declared),
        # "BRADY ENERGY NORWAY AS" declaring bradytechnologies.com: the national subsidiary of a
        # foreign brand points at the parent's international site, not a site of its own.
        "not_foreign_parent_site": not (declared and not declared.endswith(".no") and NATIONAL_SUFFIX.search(str(profile.get("name") or ""))),
    }
    failed = [name for name, ok in checks.items() if not ok]
    reason = (
        f"company declared {declared} to the Brønnøysund register; domain unique in registry, live, same-domain, no foreign orgnr, distinctive name token in domain"
        if not failed else "registry-declared rule not met: " + ", ".join(failed)
    )
    return {
        "publishable": not failed,
        "checks": checks,
        "declared_domain": declared,
        "final_domain": final_domain,
        "foreign_orgnrs": foreign[:5],
        "distinctive_tokens": distinctive,
        "reason": reason,
    }


def apply_registry_declared_rule(profile: dict[str, Any], website: dict[str, Any], index: IdentityIndex) -> dict[str, Any]:
    """Upgrade an available, kit-unconfirmed registry website when the rule holds. Mutates and returns it."""
    if website.get("status") != "available":
        return website
    value = website.get("value") or {}
    kit_assessment = value.get("identity_assessment") or {}
    if kit_assessment.get("publishable"):
        return website
    verdict = assess_registry_declared(profile, website, index)
    value["registry_declared_check"] = verdict
    if verdict["publishable"]:
        value["kit_identity_assessment"] = kit_assessment
        value["identity_assessment"] = {
            "status": "exact",
            "score": 0.92,
            "publishable": True,
            "legal_name_tokens": kit_assessment.get("legal_name_tokens"),
            "matched_tokens": kit_assessment.get("matched_tokens"),
            "reasons": [verdict["reason"]],
            "checks": verdict["checks"],
            "method": METHOD,
        }
        assessments = [assess_social_identity(profile, link) for link in value.get("discovered_social_links") or []]
        value["social_link_assessments"] = assessments
        value["social_links"] = [{"platform": item["platform"], "url": item["url"]} for item in assessments if item["publishable"]]
        website["note"] = "Registry-declared homepage published under " + METHOD
    website["value"] = value
    return website
