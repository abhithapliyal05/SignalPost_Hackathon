"""Find and strictly verify a company's official website from free candidates.

Candidates (never evidence by themselves):
  registry homepage the starter kit could not confirm, registry e-mail domain (not free-mail and
  not shared by many entities), homepages of the company's registered subunits, and the employer
  homepage on the company's own NAV job ads; then ``<name>.no`` and ``<na-me>.no`` guessed from
  the legal name when the domain exists in DNS and no other entity declares it.

A candidate is published only on proof found on a page fetched from that domain:
  orgnr proof    the exact 9-digit organisation number appears on the page and no other valid
                 organisation number does, except the company's own subunits;
  contact proof  on a .no domain, the full legal name plus a registry phone number or
                 street+postcode that belongs to this entity alone in the registry.

Everything else is recorded as a rejected candidate with the reason. See IDENTITY_RESOLUTION.md.
"""

from __future__ import annotations

import hashlib
import re
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Iterable

from bs4 import BeautifulSoup

from .evidence import evidence, utc_now
from .gate import BudgetExhausted, REQUEST_TIMEOUT_S, is_budget_note
from .identity_index import IdentityIndex, entity_contacts, normalize_phone
from .jobs import normalize_name
from .website import USER_AGENT, _gated_open, _registered_domain, _robots_allowed, assert_public_url, normalize_homepage

FREE_MAIL_DOMAINS = {
    "gmail.com", "googlemail.com", "hotmail.com", "hotmail.no", "outlook.com", "outlook.no", "live.com", "live.no",
    "msn.com", "yahoo.com", "yahoo.no", "icloud.com", "me.com", "mac.com", "online.no", "frisurf.no", "start.no",
    "c2i.net", "broadpark.no", "getmail.no", "lyse.net", "altibox.no", "tele2.no", "chello.no", "bluezone.no",
    "haugnett.no", "netcom.no", "telenor.no", "loqal.no", "proton.me", "protonmail.com", "aol.com", "gmx.com",
    "mail.com", "yandex.com", "ymail.com", "sensewave.com", "eunet.no", "vikenfiber.no", "enivest.net", "tussa.com",
    "tdcadsl.no", "ebnett.no", "kvinnherad.net", "nktv.no", "mimer.no", "neasonline.no",
}
AGGREGATOR_DOMAINS = {
    "proff.no", "gulesider.no", "purehelp.no", "1881.no", "finn.no", "brreg.no", "regnskapstall.no", "forvalt.no",
    "allabolag.se", "kompass.com", "bedriftsdatabasen.no", "firmasok.no", "enirocdn.com", "dnb.no", "nav.no",
    "arbeidsplassen.no", "linkedin.com", "facebook.com", "instagram.com", "google.com", "bing.com", "yelp.com",
    "tripadvisor.com", "hjemmeside.no", "wixsite.com", "squarespace.com", "webnode.com", "webnode.no", "blogspot.com",
    "wordpress.com", "weebly.com", "jimdo.com", "jimdosite.com", "business.site", "godaddysites.com", "one.com",
    "domeneshop.no", "uniweb.no", "123hjemmeside.no", "visma.no", "fiken.no", "tripletex.no", "poweroffice.no",
    "regnskapnorge.no", "kunngjoring.no", "kommune.no",
}
PARKED_MARKERS = (
    "domain is for sale", "domain for sale", "domenet er til salgs", "dette domenet er registrert", "hugedomains",
    "parked at", "miss hosting", "her flytter snart en ny gjest", "has been informing visitors", "buy this domain",
    "find the best information and most relevant links on all topics related to", "coming soon", "under construction",
    "kommer snart", "nettsiden er under arbeid", "default web site page", "it works!", "welcome to nginx",
    "is parked", "does not have an active website", "har ingen aktiv nettside", "this domain is registered",
)
CONTACT_TERMS = ("kontakt", "contact", "om-oss", "om oss", "about")
SHARED_EMAIL_DOMAIN_LIMIT = 5
MAX_CANDIDATES = 3
ORGNR_PATTERN = re.compile(r"(?<![\d])(?:NO[\s -]*)?(\d{3})[\s .]?(\d{3})[\s .]?(\d{3})(?:[\s ]*MVA)?(?![\d])", re.I)
PHONE_PATTERN = re.compile(r"(?<![\d])(?:\+47[\s ]?|0047[\s ]?)?\d{2}[\s .]?\d{2}[\s .]?\d{2}[\s .]?\d{2}(?![\d])|(?<![\d])(?:\+47[\s ]?)?\d{3}[\s .]?\d{2}[\s .]?\d{3}(?![\d])")
MAX_BYTES = 1_500_000


def valid_orgnr(digits: str) -> bool:
    if len(digits) != 9 or not digits.isdigit() or digits[0] not in "89":
        return False
    weights = (3, 2, 7, 6, 5, 4, 3, 2)
    remainder = sum(int(d) * w for d, w in zip(digits, weights)) % 11
    check = 0 if remainder == 0 else 11 - remainder
    return check != 10 and check == int(digits[8])


def orgnr_mentions(text: str) -> list[dict[str, Any]]:
    found = []
    for match in ORGNR_PATTERN.finditer(text):
        digits = "".join(match.groups())
        if valid_orgnr(digits):
            found.append({"orgnr": digits, "span": [match.start(), match.end()], "text": match.group(0)})
    return found


def page_text(html: str) -> tuple[str, BeautifulSoup]:
    soup = BeautifulSoup(html, "lxml")
    for node in soup(["script", "style", "noscript", "template"]):
        node.decompose()
    text = re.sub(r"\s+", " ", soup.get_text(" ", strip=True))
    return text, soup


def _snippet(text: str, span: list[int], pad: int = 80) -> str:
    return text[max(0, span[0] - pad): span[1] + pad]


def candidate_urls(profile: dict[str, Any], index: IdentityIndex, jobs_record: dict[str, Any] | None) -> list[dict[str, str]]:
    raw = (profile.get("evidence", {}).get("registry") or {}).get("value") or {}
    candidates: list[dict[str, str]] = []
    seen: set[str] = set()

    def add(url: Any, source: str) -> None:
        normalized = normalize_homepage(str(url or "").strip()) if url else None
        if not normalized:
            return
        domain = _registered_domain(normalized)
        if not domain or domain in seen or domain in AGGREGATOR_DOMAINS or any(domain.endswith("." + item) for item in AGGREGATOR_DOMAINS):
            return
        seen.add(domain)
        candidates.append({"url": normalized, "domain": domain, "source": source})

    website = profile.get("evidence", {}).get("website") or {}
    if website.get("status") == "available":
        assessment = (website.get("value") or {}).get("identity_assessment") or {}
        if not assessment.get("publishable"):
            add(website.get("source_url") or profile.get("website"), "registry_homepage_unconfirmed")
    domain = entity_contacts(raw)["email_domain"]
    if domain and domain not in FREE_MAIL_DOMAINS and index.email_domains.get(domain, 0) <= SHARED_EMAIL_DOMAIN_LIMIT:
        add("https://" + domain + "/", "registry_email_domain")
    for location in ((profile.get("evidence", {}).get("locations") or {}).get("value") or {}).get("locations") or []:
        add(location.get("website"), "subunit_homepage")
    for ad in ((jobs_record or {}).get("value") or {}).get("active_ads") or []:
        add(ad.get("employer_homepage"), "nav_ad_employer_homepage")
    del candidates[MAX_CANDIDATES:]
    for domain in guessed_domains(profile.get("name"), index):
        add("https://" + domain + "/", "name_domain_guess")
    return candidates


def guessed_domains(legal_name: Any, index: IdentityIndex) -> list[str]:
    """``<name>.no`` and ``<na-me>.no`` built from the legal name, kept only when the label has at
    least five characters, no registry entity declares the domain as its homepage, and it resolves
    in DNS (a lookup, not an HTTP request). A guess is a candidate only; it publishes nothing
    without the same strict page proof as every other candidate."""
    from .identity import _tokens

    tokens = _tokens(legal_name)
    labels = ["".join(tokens)] + (["-".join(tokens)] if len(tokens) > 1 else [])
    out = []
    for label in labels:
        domain = f"{label}.no"
        if len(label.replace("-", "")) < 5 or len(label) > 63 or index.homepage_domains.get(domain, 0) > 0:
            continue
        if _resolves(domain) or _resolves("www." + domain):
            out.append(domain)
    return out


_DNS_CACHE: dict[str, bool] = {}


def _resolves(host: str) -> bool:
    if host not in _DNS_CACHE:
        try:
            socket.getaddrinfo(host, 443)
            _DNS_CACHE[host] = True
        except socket.gaierror as exc:
            # EAI_NONAME / EAI_NODATA: the name does not exist. Any other resolver failure
            # (no DNS in the sandbox) is treated as "maybe": the gated fetch decides.
            _DNS_CACHE[host] = exc.errno not in {socket.EAI_NONAME, getattr(socket, "EAI_NODATA", -5)}
        except OSError:
            _DNS_CACHE[host] = True
    return _DNS_CACHE[host]


def _fetch_page(url: str) -> dict[str, Any]:
    assert_public_url(url)
    if not _robots_allowed(url, REQUEST_TIMEOUT_S):
        return {"url": url, "error": "robots.txt disallows page"}
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"})
    try:
        with _gated_open(request, REQUEST_TIMEOUT_S) as response:
            raw = response.read(MAX_BYTES + 1)
            final_url = response.geturl()
            content_type = response.headers.get("content-type", "")
    except BudgetExhausted:
        raise
    except urllib.error.HTTPError as exc:
        return {"url": url, "error": f"HTTP {exc.code}"}
    except Exception as exc:
        return {"url": url, "error": f"{type(exc).__name__}: {str(exc)[:120]}"}
    if len(raw) > MAX_BYTES or "html" not in content_type.lower():
        return {"url": url, "final_url": final_url, "error": "unsupported or oversized page"}
    html = raw.decode("utf-8", errors="replace")
    text, soup = page_text(html)
    return {
        "url": url,
        "final_url": final_url,
        "retrieved_at": utc_now(),
        "content_sha256": hashlib.sha256(raw).hexdigest(),
        "text": text,
        "soup": soup,
    }


def _contact_link(page: dict[str, Any]) -> str | None:
    base = page["final_url"]
    host = urllib.parse.urlparse(base).netloc.lower()
    best = None
    for anchor in page["soup"].select("a[href]"):
        url = urllib.parse.urljoin(base, str(anchor.get("href") or ""))
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme not in {"http", "https"} or parsed.netloc.lower() != host:
            continue
        haystack = (parsed.path + " " + anchor.get_text(" ", strip=True)).casefold()
        rank = next((i for i, term in enumerate(CONTACT_TERMS) if term in haystack), None)
        clean = urllib.parse.urlunparse((parsed.scheme, parsed.netloc, parsed.path or "/", "", "", ""))
        if rank is not None and clean.rstrip("/") != base.rstrip("/") and (best is None or rank < best[0]):
            best = (rank, clean)
    return best[1] if best else None


def domain_matches_name(domain: str, legal_name: str) -> bool:
    """The registrable domain's label contains the legal name's first distinctive token."""
    from .identity import _tokens

    core = [token for token in _tokens(legal_name) if len(token) >= 3]
    label = re.sub(r"[^a-z0-9]", "", domain.rsplit(".", 1)[0].casefold())
    return bool(core) and core[0] in label


def assess_page(page: dict[str, Any], org: str, allowed_orgnrs: set[str], legal_name: str, identifying_phones: set[str], identifying_addresses: list[tuple[str, str]], domain: str, in_group: bool = False) -> dict[str, Any]:
    text = page["text"]
    lowered = text.casefold()
    if any(marker in lowered for marker in PARKED_MARKERS) and len(text) < 3000:
        return {"verdict": "reject", "reason": "parked, placeholder or for-sale page"}
    mentions = orgnr_mentions(text)
    own = [item for item in mentions if item["orgnr"] == org]
    foreign = sorted({item["orgnr"] for item in mentions if item["orgnr"] not in allowed_orgnrs})
    if own and not foreign:
        return {"verdict": "proof", "proof_type": "orgnr", "span": own[0]["span"], "snippet": _snippet(text, own[0]["span"])}
    if foreign:
        return {"verdict": "reject", "reason": f"page names other organisation number(s) {', '.join(foreign[:3])}", "own_orgnr_present": bool(own)}
    name = normalize_name(legal_name)
    normalized_text = normalize_name(text)
    if in_group:
        return {"verdict": "no_proof", "reason": "group member: only organisation-number proof is accepted"}
    if not domain_matches_name(domain, legal_name):
        return {"verdict": "no_proof", "reason": "no organisation number, and domain does not carry the legal name (contact proof not allowed)"}
    if domain.endswith(".no") and name and f" {name} " in f" {normalized_text} ":
        for match in PHONE_PATTERN.finditer(text):
            phone = normalize_phone(match.group(0))
            if phone and phone in identifying_phones:
                return {"verdict": "proof", "proof_type": "legal_name_and_unique_phone", "span": [match.start(), match.end()], "snippet": _snippet(text, [match.start(), match.end()])}
        for street, postcode in identifying_addresses:
            if f" {street} " in f" {normalized_text} " and re.search(rf"(?<!\d){postcode}(?!\d)", text):
                position = re.search(rf"(?<!\d){postcode}(?!\d)", text)
                span = [position.start(), position.end()]
                return {"verdict": "proof", "proof_type": "legal_name_and_unique_address", "span": span, "snippet": _snippet(text, span)}
        return {"verdict": "no_proof", "reason": "legal name present but no identifying phone or address"}
    return {"verdict": "no_proof", "reason": "no organisation number or legal-name contact proof"}


def verify_candidate(candidate: dict[str, str], profile: dict[str, Any], index: IdentityIndex, allowed_orgnrs: set[str]) -> dict[str, Any]:
    org = profile["organisation_number"]
    raw = (profile.get("evidence", {}).get("registry") or {}).get("value") or {}
    contacts = entity_contacts(raw)
    phones = {phone for phone in contacts["phones"] if index.phones.get(phone) == 1}
    addresses = [tuple(key.split("|", 1)) for key in contacts["addresses"] if index.addresses.get(key) == 1]
    result: dict[str, Any] = {**candidate, "pages": []}
    page = _fetch_page(candidate["url"])
    if page.get("error") and candidate["url"].startswith("https://"):
        fallback = _fetch_page("http://" + candidate["url"][len("https://"):])
        if not fallback.get("error"):
            page = fallback
    pages = [page]
    for attempt in range(2):
        current = pages[-1]
        if current.get("error"):
            result["pages"].append({"url": current["url"], "error": current["error"]})
            if attempt == 0:
                result.update(verdict="unreachable", reason=current["error"])
            else:
                result.update(verdict="no_proof", reason=f"no proof on homepage; contact page {current['error']}")
            return result
        final_domain = _registered_domain(current["final_url"])
        if final_domain != candidate["domain"] and (final_domain in AGGREGATOR_DOMAINS or any(final_domain.endswith("." + item) for item in AGGREGATOR_DOMAINS)):
            result.update(verdict="reject", reason=f"redirects to directory or platform {final_domain}")
            return result
        in_group = str(raw.get("erIKonsern") or "").casefold() == "true" or (profile.get("evidence", {}).get("group") or {}).get("status") == "available"
        assessment = assess_page(current, org, allowed_orgnrs, str(profile.get("name") or ""), phones, addresses, final_domain, in_group)
        result["pages"].append({"url": current["final_url"], "retrieved_at": current["retrieved_at"], "content_sha256": current["content_sha256"], **assessment})
        if assessment["verdict"] in {"proof", "reject"}:
            result.update(verdict=assessment["verdict"], final_url=current["final_url"], final_domain=final_domain, reason=assessment.get("reason"))
            if assessment["verdict"] == "proof":
                result["proof"] = {
                    "type": assessment["proof_type"],
                    "page_url": current["final_url"],
                    "retrieved_at": current["retrieved_at"],
                    "content_sha256": current["content_sha256"],
                    "char_span": assessment["span"],
                    "snippet": assessment["snippet"],
                    "extraction": "visible_text_v1 (BeautifulSoup get_text, whitespace collapsed)",
                }
            return result
        if attempt == 0:
            link = _contact_link(current) or urllib.parse.urljoin(current["final_url"], "/kontakt")
            pages.append(_fetch_page(link))
    result.update(verdict="no_proof", reason="no proof on homepage or contact page")
    return result


def discover_website(profile: dict[str, Any], index: IdentityIndex, jobs_record: dict[str, Any] | None) -> dict[str, Any]:
    """Return the website_discovery evidence record (candidates, verdicts, published site)."""
    org = profile["organisation_number"]
    subunits = {
        str(item.get("organisation_number"))
        for item in ((profile.get("evidence", {}).get("locations") or {}).get("value") or {}).get("locations") or []
        if item.get("organisation_number")
    }
    allowed = {org, *subunits}
    source_url = "about:signalpost-website-discovery"
    website = profile.get("evidence", {}).get("website") or {}
    if website.get("status") == "available" and ((website.get("value") or {}).get("identity_assessment") or {}).get("publishable"):
        return evidence("website_discovery", "not_applicable", "free_candidate_discovery", source_url, value={"candidates": []}, note="Registry-listed website already passed the identity gate")
    candidates = candidate_urls(profile, index, jobs_record)
    if not candidates:
        return evidence("website_discovery", "not_found", "free_candidate_discovery", source_url, value={"candidates": []}, note="No free website candidate (registry homepage, e-mail domain, subunit or NAV employer homepage)")
    results = []
    budget_note = None
    for candidate in candidates:
        try:
            outcome = verify_candidate(candidate, profile, index, allowed)
        except BudgetExhausted as exc:
            budget_note = str(exc)
            break
        except ValueError as exc:  # non-public or unresolvable host
            outcome = {**candidate, "verdict": "unreachable", "reason": str(exc)[:160]}
        results.append(outcome)
        if outcome.get("verdict") == "proof":
            break
    value = {"candidates": results}
    verified = next((item for item in results if item.get("verdict") == "proof"), None)
    if verified:
        parsed = urllib.parse.urlparse(verified["final_url"])
        value["verified_url"] = urllib.parse.urlunparse((parsed.scheme, parsed.netloc, "/", "", "", ""))
        value["proof"] = verified["proof"]
        value["candidate_source"] = verified["source"]
        return evidence("website_discovery", "available", "verified_company_website", value["verified_url"], value=value, retrieved_at=verified["proof"]["retrieved_at"], content_sha256=verified["proof"]["content_sha256"], source_row_key=org, note=f"Published on {verified['proof']['type']} proof")
    if budget_note:
        return evidence("website_discovery", "blocked", "free_candidate_discovery", source_url, value=value, note=budget_note)
    rejected = [item for item in results if item.get("verdict") == "reject"]
    note = "ambiguous: candidate(s) rejected by identity rules" if rejected else "No candidate passed strict identity proof"
    return evidence("website_discovery", "not_found", "free_candidate_discovery", source_url, value=value, note=note)


def publish_discovered_site(profile: dict[str, Any], site_record: dict[str, Any], discovery: dict[str, Any]) -> dict[str, Any]:
    """Turn a fetched, proof-verified site into the kit's website evidence shape."""
    from .identity import assess_social_identity

    value = site_record.get("value") or {}
    proof = (discovery.get("value") or {}).get("proof") or {}
    value["identity_assessment"] = {
        "status": "exact",
        "score": 1.0,
        "publishable": True,
        "reasons": [f"strict {proof.get('type')} proof on {proof.get('page_url')}"],
        "proof": proof,
        "candidate_source": (discovery.get("value") or {}).get("candidate_source"),
        "method": "strict_free_candidate_proof_v1",
    }
    original = list(value.get("social_links") or [])
    value["discovered_social_links"] = original
    assessments = [assess_social_identity(profile, link) for link in original]
    value["social_link_assessments"] = assessments
    value["social_links"] = [{"platform": item["platform"], "url": item["url"]} for item in assessments if item["publishable"]]
    site_record["value"] = value
    site_record["source_type"] = site_record["source_class"] = "verified_company_website"
    site_record["note"] = "Company-controlled claim layer; identity proven by " + str(proof.get("type"))
    return site_record
