"""Dated changes from the Central Coordinating Register's public update feed.

One request per company to ``/oppdateringer/enheter`` (``includeChanges=true``) for the last
~18 months. Each update carries the register's own timestamp and JSON-patch changes; we turn
the changes into plain events ("Business address changed (to BODØ)", "Annual accounts for 2025
submitted"). Monthly employee-count refreshes become one employee series instead of a dozen
events. Street addresses, phone numbers and e-mail addresses are never copied (an ENK's address
can be the owner's home): only the fact that they changed, plus the town.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

BRREG_UPDATES = "https://data.brreg.no/enhetsregisteret/api/oppdateringer/enheter?organisasjonsnummer={org}&includeChanges=true&size=500&dato={since}"
LOOKBACK_DAYS = 548  # about 18 months; the feed carries change details from mid-2025

# Fields that are bookkeeping for another change, or too noisy to report.
SKIP_FIELDS = {
    "registreringsdatoAntallAnsatteEnhetsregisteret", "registreringsdatoAntallAnsatteNAVAaregisteret",
    "harRegistrertAntallAnsatte", "hjelpeenhetskode", "registreringsdatoMerverdiavgiftsregisteret",
    "registreringsdatoMerverdiavgiftsregisteretEnhetsregisteret", "kapital/innfortDato", "kapital/antallAksjer",
    "kapital/type", "kapital/valuta", "kapital/fulltInnbetaltBelop", "kapital/bundetKapital",
    "institusjonellSektorkode", "links", "_links", "maalform", "underAvviklingDato", "konkursdato",
}
PRIVATE_FIELDS = {"telefon", "mobil", "epostadresse"}


def updates_url(org: str, today: datetime | None = None) -> str:
    since = (today or datetime.now(timezone.utc)) - timedelta(days=LOOKBACK_DAYS)
    return BRREG_UPDATES.format(org=org, since=since.strftime("%Y-%m-%dT00:00:00.000Z"))


def _field(path: str) -> str:
    """'/forretningsadresse/adresse/0' -> 'forretningsadresse/adresse'; '/kapital/belop' -> 'kapital/belop'."""
    parts = [part for part in path.strip("/").split("/") if part and not part.isdigit() and part != "-"]
    return "/".join(parts[:2])


def _amount(value: Any) -> str | None:
    try:
        return f"NOK {float(value):,.0f}".replace(",", " ")
    except (TypeError, ValueError):
        return None


def _describe(changes: list[dict[str, Any]]) -> list[tuple[str, str]]:
    """Return (event text, source field) pairs for one update's JSON-patch operations."""
    by_top: dict[str, list[dict[str, Any]]] = {}
    for change in changes:
        field = _field(str(change.get("path") or ""))
        if not field or field in SKIP_FIELDS or field.split("/")[0] in {"antallAnsatte", "links", "_links"}:
            continue
        by_top.setdefault(field.split("/")[0], []).append({**change, "field": field})
    out: list[tuple[str, str]] = []
    for top, items in by_top.items():
        first = items[0]
        value = first.get("value")
        removed = all(item.get("op") == "remove" for item in items)
        values = {item["field"]: item.get("value") for item in items}
        if top == "navn" and isinstance(value, str):
            out.append((f"Name changed to {value}", "navn"))
        elif top == "forretningsadresse":
            town = values.get("forretningsadresse/poststed") or values.get("forretningsadresse/kommune") or (value.get("poststed") if isinstance(value, dict) else None)
            out.append(("Business address removed" if removed else f"Business address changed (to {town})" if town else "Business address changed", "forretningsadresse"))
        elif top == "postadresse":
            out.append(("Postal address removed" if removed else "Postal address changed", "postadresse"))
        elif top in {"naeringskode1", "naeringskode2", "naeringskode3"}:
            code = values.get(f"{top}/kode") or (value.get("kode") if isinstance(value, dict) else None)
            label = values.get(f"{top}/beskrivelse") or (value.get("beskrivelse") if isinstance(value, dict) else None)
            which = "Industry code" if top == "naeringskode1" else "Secondary industry code"
            if removed:
                out.append((f"{which} removed", top))
            elif code == "00.000":
                out.append((f"{which} set to unspecified (00.000)", top))
            else:
                out.append((f"{which} changed" + (f" to {code}" if code else "") + (f" ({label})" if label else ""), top))
        elif top in {"vedtektsfestetFormaal", "aktivitet"}:
            text = " ".join(str(item.get("value") or "") for item in items if item.get("op") != "remove").strip()
            what = "Stated purpose (articles)" if top == "vedtektsfestetFormaal" else "Registered activity"
            short = text if len(text) <= 160 else text[:160].rsplit(" ", 1)[0] + "…"
            out.append((f"{what} changed" + (f": “{short}”" if text else ""), top))
        elif top == "vedtektsdato":
            out.append((f"Articles of association updated (dated {value})" if value else "Articles of association updated", top))
        elif top == "kapital":
            amount = _amount(values.get("kapital/belop")) if "kapital/belop" in values else None
            out.append((f"Share capital changed to {amount}" if amount else "Share capital details changed", top))
        elif top == "sisteInnsendteAarsregnskap" and value:
            out.append((f"Annual accounts for {value} submitted", top))
        elif top == "registrertIMvaregisteret":
            out.append(("Registered in the VAT register" if value is True else "Removed from the VAT register", top))
        elif top == "registrertIForetaksregisteret":
            out.append(("Registered in the Register of Business Enterprises" if value is True else "Removed from the Register of Business Enterprises", top))
        elif top == "registrertIFrivillighetsregisteret":
            out.append(("Registered in the Register of Non-Profit Organisations" if value is True else "Removed from the Register of Non-Profit Organisations", top))
        elif top == "underAvvikling":
            out.append(("Liquidation registered" if value is True else "Liquidation no longer registered", top))
        elif top == "konkurs":
            out.append(("Bankruptcy registered" if value is True else "Bankruptcy no longer registered", top))
        elif top == "underTvangsavviklingEllerTvangsopplosning":
            out.append(("Compulsory dissolution or liquidation registered" if value is True else "Compulsory dissolution or liquidation lifted", top))
        elif top == "erIKonsern":
            out.append(("Now registered as part of a corporate group" if value is True else "No longer registered as part of a corporate group", top))
        elif top == "hjemmeside":
            out.append(("Website removed from the register" if removed else f"Website in the register set to {value}", top))
        elif top == "organisasjonsform":
            code = values.get("organisasjonsform/kode") or (value.get("kode") if isinstance(value, dict) else None)
            out.append((f"Legal form changed to {code}" if code else "Legal form changed", top))
        elif top == "overordnetEnhetIOffentligSektor":
            out.append(("Parent unit in the public sector changed", top))
        elif top in PRIVATE_FIELDS:
            out.append(("Contact details changed", top))
    seen: set[str] = set()
    return [pair for pair in out if not (pair[0] in seen or seen.add(pair[0]))]


def normalize_updates(body: Any) -> dict[str, Any]:
    """Turn the update feed into dated events plus an employee-count series (both oldest first)."""
    rows = ((body or {}).get("_embedded") or {}).get("oppdaterteEnheter") or [] if isinstance(body, dict) else []
    page = (body or {}).get("page") or {} if isinstance(body, dict) else {}
    events: list[dict[str, Any]] = []
    employees: list[dict[str, Any]] = []
    for row in sorted(rows, key=lambda item: str(item.get("dato") or "")):
        day = str(row.get("dato") or "")[:10]
        if not day:
            continue
        kind = row.get("endringstype")
        if kind == "Ny":
            events.append({"date": day, "event": "Entity registered in the Central Coordinating Register", "source_field": "endringstype", "update_id": row.get("oppdateringsid")})
        elif kind in {"Sletting", "Fjernet"}:
            events.append({"date": day, "event": "Entity deleted from the Central Coordinating Register", "source_field": "endringstype", "update_id": row.get("oppdateringsid")})
        changes = row.get("endringer") or []
        for change in changes:
            if _field(str(change.get("path") or "")) == "antallAnsatte" and change.get("op") in {"add", "replace"}:
                try:
                    employees.append({"date": day, "employees": int(float(change.get("value")))})
                except (TypeError, ValueError):
                    pass
        for text, field in _describe(changes):
            events.append({"date": day, "event": text, "source_field": f"endringer:/{field}", "update_id": row.get("oppdateringsid")})
    return {
        "events": events,
        "employee_series": employees,
        "update_count": len(rows),
        "truncated": bool(page.get("totalPages", 1) > 1),
        "lookback_days": LOOKBACK_DAYS,
    }
