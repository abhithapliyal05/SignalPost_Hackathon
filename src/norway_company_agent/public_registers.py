"""LEI, licences and food-safety inspections from the declared public-register cache.

The cache (data/cache/registers.jsonl.gz, built by scripts/build_register_cache.py) holds whole-
country files from GLEIF, Finanstilsynet, Statens vegvesen, Arbeidstilsynet, Udir,
Fiskeridirektoratet and Mattilsynet, keyed by the organisation number each register published.
A company matches on its own number, or on one of its registered workplaces (subunits from the
official ``locations`` record) for registers that list workplaces. Matching is by organisation
number only, so there is no name guessing. No request is made at run time.
"""

from __future__ import annotations

import gzip
import json
from pathlib import Path
from typing import Any

from .evidence import evidence

DEFAULT_CACHE_DIR = Path(__file__).resolve().parents[2] / "data" / "cache"
SOURCE_TYPE = "declared_public_register_cache"
MODULES = ("lei", "licences", "food_inspections")
LICENCE_REGISTERS = "Finanstilsynet, Statens vegvesen approved workshops, Arbeidstilsynet cleaning register, Udir NBR/NSR, Fiskeridirektoratet aquaculture"


class RegisterIndex:
    def __init__(self, cache_dir: str | Path = DEFAULT_CACHE_DIR) -> None:
        path = Path(cache_dir) / "registers.jsonl.gz"
        state_path = Path(cache_dir) / "registers_state.json"
        self._lines: dict[str, str] = {}
        self.state: dict[str, Any] = json.loads(state_path.read_text()) if state_path.exists() else {}
        self.available = path.exists()
        if self.available:
            with gzip.open(path, "rt", encoding="utf-8") as handle:
                for line in handle:
                    # Keep raw lines (decoded on lookup) so 100k+ organisations stay cheap in memory.
                    self._lines[line[8:17]] = line

    def summary(self) -> dict[str, Any]:
        return {"available": self.available, "organisations": len(self._lines), "built_at": self.state.get("built_at"), "entries_by_source": self.state.get("entries_by_source")}

    def entries(self, org: str) -> list[dict[str, Any]]:
        line = self._lines.get(org)
        return json.loads(line)["entries"] if line else []

    def lookup(self, profile: dict[str, Any]) -> dict[str, dict[str, Any]]:
        org = profile["organisation_number"]
        locations = ((profile.get("evidence") or {}).get("locations") or {}).get("value") or {}
        units = [str(item["organisation_number"]) for item in locations.get("locations") or [] if item.get("organisation_number")]
        own = self.entries(org)
        unit_entries = [entry for unit in units if unit != org for entry in self.entries(unit)]
        built = self.state.get("built_at")
        if not self.available:
            return {module: evidence(module, "source_error", SOURCE_TYPE, "about:signalpost-register-cache", note="Register cache missing; run make registers", source_row_key=org) for module in MODULES}
        return {
            "lei": _lei_record(org, [entry for entry in own if entry["field"] == "lei"], built),
            "licences": _list_record("licences", org, [entry for entry in own + unit_entries if entry["field"] == "licences"], f"Not listed in the cached licence registers ({LICENCE_REGISTERS}) under the company or its workplaces", built),
            "food_inspections": _list_record("food_inspections", org, [entry for entry in own + unit_entries if entry["field"] == "food_inspections"], "No food-safety inspection (Mattilsynet smilefjes) is published for the company or its workplaces", built),
        }


def _item(entry: dict[str, Any]) -> dict[str, Any]:
    return {**entry["value"], "unit_org": entry["unit_org"], "source": entry["source"], "source_url": entry["source_url"], "retrieved_at": entry["retrieved_at"], "content_sha256": entry["content_sha256"], "licence_terms": entry.get("licence")}


def _lei_record(org: str, entries: list[dict[str, Any]], built: str | None) -> dict[str, Any]:
    search = f"https://api.gleif.org/api/v1/lei-records?filter[entity.registeredAs]={org}"
    if not entries:
        return evidence("lei", "not_found", SOURCE_TYPE, search, note=f"No LEI with Brønnøysund registration {org} in the GLEIF golden copy (cache built {built})", source_row_key=org)
    # An organisation number can carry more than one LEI over time; prefer an issued one.
    entry = sorted(entries, key=lambda item: item["value"].get("registration_status") != "ISSUED")[0]
    return evidence("lei", "available", SOURCE_TYPE, entry["source_url"], value={**entry["value"], "dataset_url": entry["dataset_url"], "licence_terms": entry.get("licence")}, retrieved_at=entry["retrieved_at"], content_sha256=entry["content_sha256"], source_row_key=org, note="GLEIF golden copy, matched on the Brønnøysund registration number")


def _list_record(field: str, org: str, entries: list[dict[str, Any]], missing_note: str, built: str | None) -> dict[str, Any]:
    if not entries:
        return evidence(field, "not_found", SOURCE_TYPE, "about:signalpost-register-cache", note=f"{missing_note} (cache built {built})", source_row_key=org)
    items = sorted((_item(entry) for entry in entries), key=lambda item: (item["unit_org"] != org, item.get("source"), str(item.get("inspected") or "")), reverse=False)
    if field == "food_inspections":
        items.sort(key=lambda item: str(item.get("inspected") or ""), reverse=True)
    first = items[0]
    value = {"items": items, "count": len(items)}
    if field == "food_inspections":
        value["latest_inspection"] = first.get("inspected")
    return evidence(field, "available", SOURCE_TYPE, first["source_url"], value=value, retrieved_at=first["retrieved_at"], content_sha256=first["content_sha256"], source_row_key=org, note="Matched on organisation number in the declared public-register cache; each item carries its own source")
