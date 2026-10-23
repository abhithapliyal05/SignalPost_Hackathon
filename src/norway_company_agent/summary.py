"""A short, fully sourced company summary built from the evidence already in the profile.

Deterministic (no model): every sentence is generated from one or more published evidence
records and carries their source URLs. It answers what the company is and does, its size and
latest results, what changed recently, and what remains unknown. Nothing is inferred beyond the
records: a missing source is reported as unknown, never as zero or absence.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

from .evidence import evidence

LEGAL_FORMS = {
    "AS": "private limited company (AS)", "ASA": "public limited company (ASA)", "ENK": "sole proprietorship (ENK)",
    "ANS": "general partnership (ANS)", "DA": "partnership with shared liability (DA)", "SA": "cooperative (SA)",
    "BRL": "housing cooperative (borettslag)", "ESEK": "owner-section condominium (eierseksjonssameie)",
    "STI": "foundation (stiftelse)", "NUF": "Norwegian branch of a foreign company (NUF)", "FLI": "association (forening/lag)",
    "KS": "limited partnership (KS)", "SAM": "co-ownership (sameie)", "BBL": "housing association (boligbyggelag)",
    "IKS": "inter-municipal company (IKS)", "SPA": "savings bank (sparebank)", "PK": "pension fund (pensjonskasse)",
    "ORGL": "organisational unit (organisasjonsledd)", "GFS": "mutual insurance company (gjensidig forsikringsselskap)", "KF": "municipal enterprise (KF)", "SF": "state enterprise (SF)",
}
RECENT_DAYS = 548  # about 18 months


def _ok(record: dict[str, Any] | None) -> bool:
    return bool(record) and record.get("status") == "available"


def _nok(value: Any) -> str | None:
    if value is None:
        return None
    amount = float(value)
    sign = "-" if amount < 0 else ""
    amount = abs(amount)
    if amount >= 1e9:
        return f"{sign}NOK {amount / 1e9:.1f} billion"
    if amount >= 1e6:
        return f"{sign}NOK {amount / 1e6:.1f} million"
    if amount >= 1e3:
        return f"{sign}NOK {amount / 1e3:.0f} thousand"
    return f"{sign}NOK {amount:.0f}"


def _parse_day(value: str) -> date | None:
    try:
        return date.fromisoformat(value[:10])
    except (TypeError, ValueError):
        return None


def build_summary(profile: dict[str, Any], today: date | None = None) -> dict[str, Any]:
    today = today or datetime.now(timezone.utc).date()
    records = profile.get("evidence", {})
    org = profile["organisation_number"]
    sentences: list[dict[str, Any]] = []
    unknowns: list[dict[str, Any]] = []

    def say(section: str, text: str, *sources: dict[str, Any] | None) -> None:
        urls = sorted({item.get("source_url") for item in sources if item and item.get("source_url")})
        sentences.append({"section": section, "text": text, "sources": urls})

    live = records.get("registry_live") if _ok(records.get("registry_live")) else records.get("registry")
    live_value = (live or {}).get("value") or {}
    name = profile.get("name") or live_value.get("name") or org
    form_code = profile.get("legal_form") or live_value.get("legal_form")
    form = LEGAL_FORMS.get(str(form_code), f"entity with legal form code {form_code}" if form_code else "registered entity")
    industry = (live_value.get("industry") or {}).get("beskrivelse") if isinstance(live_value.get("industry"), dict) else None
    industry = industry or profile.get("industry_label")
    dates = live_value.get("registry_dates") or {}
    place = profile.get("municipality") or ((live_value.get("business_address") or {}).get("kommune"))
    article = "an" if form[:1].lower() in "aeiou" else "a"
    parts = [f"{name} (org. no. {org}) is {article} {form}"]
    if place:
        parts.append(f"registered in {str(place).title()}")
    if dates.get("stiftelsesdato"):
        parts.append(f"founded {dates['stiftelsesdato']}")
    text = ", ".join(parts)
    if industry:
        text += f", whose registered activity is “{industry}”"
    say("company", text + ".", live)
    employees = live_value.get("employees", profile.get("employees"))
    if employees not in (None, ""):
        say("company", f"The register reports {employees} employees.", live)
    if profile.get("bankrupt") or live_value.get("bankrupt"):
        say("company", "The register marks the company as bankrupt.", live)
    if profile.get("liquidating") or live_value.get("liquidating"):
        say("company", "The register marks the company as under liquidation.", live)

    accounts = records.get("financials")
    rows = sorted(((accounts or {}).get("value") or {}).get("records") or [], key=lambda row: str((row.get("period") or {}).get("tilDato") or ""))
    if _ok(accounts) and rows:
        latest = rows[-1]
        period = (latest.get("period") or {}).get("tilDato")
        figures = [f"revenue {_nok(latest.get('revenue'))}" if latest.get("revenue") is not None else None,
                   f"operating result {_nok(latest.get('operating_result'))}" if latest.get("operating_result") is not None else None,
                   f"annual result {_nok(latest.get('annual_result'))}" if latest.get("annual_result") is not None else None,
                   f"equity {_nok(latest.get('equity'))}" if latest.get("equity") is not None else None]
        figures = [item for item in figures if item]
        if figures:
            say("finances", f"In the accounts for the period ending {period}, it reported " + ", ".join(figures) + ".", accounts)
        if len(rows) >= 2 and rows[-2].get("revenue") and latest.get("revenue") is not None:
            before, after = float(rows[-2]["revenue"]), float(latest["revenue"])
            change = (after - before) / abs(before) * 100 if before else None
            if change is not None:
                direction = "rose" if change > 0 else "fell" if change < 0 else "was unchanged"
                detail = f" {abs(change):.0f}%" if change else ""
                say("changes", f"Revenue {direction}{detail} from {_nok(before)} (period ending {(rows[-2].get('period') or {}).get('tilDato')}) to {_nok(after)}.", accounts)
    else:
        unknowns.append({"field": "annual_accounts", "text": "No normalized annual accounts were returned by the Register of Company Accounts."})
    history = records.get("financial_history")
    years = ((history or {}).get("value") or {}).get("years") or []
    if _ok(history) and years:
        say("finances", f"Official annual-account copies are filed for {len(years)} year(s), {years[0]} to {years[-1]}.", history)

    roles = records.get("roles")
    role_rows = [row for row in ((roles or {}).get("value") or {}).get("roles") or [] if not row.get("inactive")]
    named = []
    for code, label in (("DAGL", "general manager"), ("LEDE", "chair of the board"), ("INNH", "owner")):
        holder = next((row.get("name") for row in role_rows if row.get("role_code") == code and row.get("name")), None)
        if holder:
            named.append(f"{label} {holder}")
    board = sum(1 for row in role_rows if row.get("group_code") == "STYR")
    if _ok(roles) and (named or board):
        text = "Registered roles: " + ", ".join(named) if named else "Registered roles are on file"
        if board:
            text += f"; {board} board role(s) in total"
        say("people", text + ".", roles)
    locations = records.get("locations")
    workplaces = ((locations or {}).get("value") or {}).get("locations") or []
    if _ok(locations) and workplaces:
        towns = sorted({str((row.get("address") or {}).get("kommune") or "").title() for row in workplaces} - {""})
        say("people", f"It has {len(workplaces)} registered workplace(s)" + (f" in {', '.join(towns[:5])}" if towns else "") + ".", locations)
    group = records.get("group")
    if _ok(group):
        say("company", "The register lists it in a corporate group structure.", group)

    website = records.get("website")
    site_value = (website or {}).get("value") or {}
    if _ok(website) and (site_value.get("identity_assessment") or {}).get("publishable"):
        socials = site_value.get("social_links") or []
        text = f"Its verified website is {site_value.get('final_url')}"
        if site_value.get("description"):
            text += f", which describes it as: “{str(site_value['description'])[:200].strip()}”"
        say("online", text + ".", website)
        if socials:
            say("online", "Company-owned profiles linked from the site: " + ", ".join(sorted({item['platform'] for item in socials})) + ".", website)
        else:
            unknowns.append({"field": "social_profiles", "text": "No company-owned social profile was linked from the verified website."})
    else:
        unknowns.append({"field": "official_website", "text": "No website could be verified as this company's own (checked: registry homepage and free candidates)."})
        unknowns.append({"field": "social_profiles", "text": "Social profiles are only published from a verified website, so none are listed."})

    jobs = records.get("jobs")
    ads = ((jobs or {}).get("value") or {}).get("active_ads") or []
    if _ok(jobs) and ads:
        say("changes", f"It has {len(ads)} active job ad(s) on NAV, the latest published {str(ads[0].get('published') or '')[:10]}: “{ads[0].get('title')}”.", jobs)
    elif (jobs or {}).get("status") == "not_found":
        unknowns.append({"field": "hiring", "text": "No active job ad was found in NAV's national vacancy feed for the company or its workplaces."})

    posts = records.get("company_posts")
    post_rows = ((posts or {}).get("value") or {}).get("posts") or []
    if _ok(posts) and post_rows:
        say("changes", f"Its website feed lists {len(post_rows)} dated post(s), most recently “{post_rows[0]['title']}” on {post_rows[0]['published_at'][:10]}.", posts)

    timeline = records.get("official_timeline")
    recent = []
    for event in ((timeline or {}).get("value") or {}).get("events") or []:
        day = _parse_day(event.get("date") or "") if event.get("precision") == "day" else None
        if day and 0 <= (today - day).days <= RECENT_DAYS and "Employee count" not in event.get("event", ""):
            recent.append(event)
    if recent:
        listed = "; ".join(f"{item['date']}: {item['event']}" for item in recent[:4])
        say("changes", f"Recent register events: {listed}.", timeline)
    elif _ok(timeline):
        say("changes", "No register event in the last 18 months besides routine filings.", timeline)

    text = " ".join(item["text"] for item in sentences)
    if unknowns:
        text += " Unknown: " + " ".join(item["text"] for item in unknowns)
    sources = sorted({url for item in sentences for url in item["sources"]})
    return evidence(
        "summary",
        "available",
        "derived_from_cited_evidence",
        sources[0] if sources else "about:signalpost-summary",
        value={"text": text, "sentences": sentences, "unknowns": unknowns, "sources": sources, "method": "deterministic_template_v1"},
        source_row_key=org,
        note="Generated only from this profile's published evidence; each sentence lists its sources",
    )
