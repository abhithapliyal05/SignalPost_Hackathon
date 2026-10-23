"""Dated company activity built only from official Brønnøysund records.

Every event is a date taken verbatim from a fetched register response (live entity, roles,
accounts, filed-accounts years and the register's update feed), with that response's URL,
retrieval time and content hash, and the source field that carried the date. Only the update
feed (``registry_changes``) is fetched for the timeline; nothing is inferred: an event says what
the register recorded on that date, not why."""

from __future__ import annotations

from typing import Any

from .evidence import evidence

REGISTRY_DATE_LABELS = {
    "stiftelsesdato": "Company founded",
    "registreringsdatoEnhetsregisteret": "Registered in the Central Coordinating Register for Legal Entities",
    "registreringsdatoForetaksregisteret": "Registered in the Register of Business Enterprises",
    "registreringsdatoMerverdiavgiftsregisteret": "Registered in the VAT register",
    "registreringsdatoFrivilligMerverdiavgiftsregisteret": "Voluntarily registered in the VAT register",
    "registreringsdatoMerverdiavgiftsregisteretEnhetsregisteret": "VAT registration recorded in the Central Coordinating Register",
    "registreringsdatoFrivillighetsregisteret": "Registered in the Register of Non-Profit Organisations",
    "vedtektsdato": "Articles of association dated (latest version)",
    "registreringsdatoAntallAnsatteEnhetsregisteret": "Employee count updated in the register",
    "registreringsdatoAntallAnsatteNAVAaregisteret": "Employee count updated from NAV's employer register",
    "konkursdato": "Bankruptcy registered",
    "underAvviklingDato": "Liquidation registered",
    "tvangsavvikletPgaManglendeSlettingDato": "Compulsory liquidation registered (not deleted after dissolution)",
    "tvangsopplostPgaManglendeDagligLederDato": "Compulsory dissolution registered (no general manager)",
    "tvangsopplostPgaManglendeRevisorDato": "Compulsory dissolution registered (no auditor)",
    "tvangsopplostPgaManglendeRegnskapDato": "Compulsory dissolution registered (accounts not filed)",
    "tvangsopplostPgaMangelfulltStyreDato": "Compulsory dissolution registered (incomplete board)",
}


def _source(record: dict[str, Any]) -> dict[str, Any]:
    return {key: record.get(key) for key in ("source_url", "retrieved_at", "content_sha256")}


def build_official_timeline(profile: dict[str, Any]) -> dict[str, Any]:
    """Return the ``official_timeline`` evidence record for one company, newest event first."""
    org = profile["organisation_number"]
    records = profile.get("evidence", {})
    events: list[dict[str, Any]] = []

    live = records.get("registry_live") or {}
    if live.get("status") == "available":
        for key, date in ((live.get("value") or {}).get("registry_dates") or {}).items():
            events.append({"date": date, "precision": "day", "event": REGISTRY_DATE_LABELS.get(key, f"Register date field {key}"), "source_field": key, **_source(live)})

    roles = records.get("roles") or {}
    if roles.get("status") == "available":
        seen: set[tuple[str, str]] = set()
        for role in (roles.get("value") or {}).get("roles") or []:
            group, date = role.get("group") or role.get("group_code"), role.get("last_changed")
            if group and date and (group, date) not in seen:
                seen.add((group, date))
                events.append({"date": date, "precision": "day", "event": f"Role group last changed: {group}", "source_field": "rollegrupper[].sistEndret", **_source(roles)})

    accounts = records.get("financials") or {}
    if accounts.get("status") == "available":
        for item in (accounts.get("value") or {}).get("records") or []:
            period = item.get("period") or {}
            if period.get("tilDato"):
                events.append({"date": period["tilDato"], "precision": "day", "event": f"Annual accounts period ended ({period.get('fraDato')} to {period['tilDato']}); accounts published in the register", "source_field": "regnskapsperiode.tilDato", **_source(accounts)})

    history = records.get("financial_history") or {}
    if history.get("status") == "available":
        for year in (history.get("value") or {}).get("years") or []:
            events.append({"date": str(year), "precision": "year", "event": f"Annual accounts for {year} filed; official copy available", "source_field": "aarsregnskap/kopi/aar", **_source(history)})

    changes = records.get("registry_changes") or {}
    if changes.get("status") == "available":
        value = changes.get("value") or {}
        for item in value.get("events") or []:
            events.append({"date": item["date"], "precision": "day", "event": item["event"], "source_field": item["source_field"], "update_id": item.get("update_id"), **_source(changes)})
        series = value.get("employee_series") or []
        if len(series) >= 2 and series[0]["employees"] != series[-1]["employees"]:
            first, last = series[0], series[-1]
            events.append({"date": last["date"], "precision": "day", "event": f"Employee count in the register changed from {first['employees']} ({first['date']}) to {last['employees']}", "source_field": "endringer:/antallAnsatte", **_source(changes)})

    events.sort(key=lambda item: (item["date"], item["event"]), reverse=True)
    source_url = live.get("source_url") or f"https://data.brreg.no/enhetsregisteret/api/enheter/{org}"
    if not events:
        return evidence("official_timeline", "not_found", "official_registry_dates", source_url, note="No dated events in the fetched official records", source_row_key=org)
    latest = max((item["retrieved_at"] for item in events if item.get("retrieved_at")), default=None)
    return evidence(
        "official_timeline",
        "available",
        "official_registry_dates",
        source_url,
        value={"events": events, "latest_event_date": events[0]["date"], "event_count": len(events)},
        retrieved_at=latest,
        source_row_key=org,
        note="Dates recorded by the Brønnøysund registers, each with the response that carried it",
    )
