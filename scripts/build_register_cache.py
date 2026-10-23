#!/usr/bin/env python3
"""Build the declared public-register cache (data/cache/registers.jsonl.gz).

Open Norwegian registers that publish a whole-country file, read once before a run so a batch
spends no requests on them:

- GLEIF LEI golden copy (CC0) and its relationship file: LEI, status and direct/ultimate parents
  of every legal entity registered with Brønnøysund (RA000472).
- Finanstilsynet's register of licensed entities (own licences only, never agent links).
- Statens vegvesen's approved vehicle workshops (NLOD).
- Arbeidstilsynet's register of cleaning companies (NLOD).
- Udir's kindergarten (NBR) and school (NSR) registers (NLOD), active units and owners.
- Fiskeridirektoratet's aquaculture register (NLOD), legal entities only.
- Mattilsynet's food-safety inspection results (smilefjes, NLOD), latest inspection per premises.

Each cached entry keeps the organisation number it was published under (company or workplace),
a per-record URL when the publisher has one (else the dataset URL plus the record key), the time
the source file was downloaded and the SHA-256 of the record as published. No personal data:
sole-proprietor rows from the aquaculture register are dropped, and street addresses, phone
numbers and contact names are not stored.

Usage: build_register_cache.py [--sources-dir DIR] [--output data/cache/registers.jsonl.gz]
With --sources-dir, files already downloaded there are reused (their mtime is the retrieval time).
"""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import io
import json
import time
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

ROOT = Path(__file__).resolve().parents[1]
USER_AGENT = "SignalPost-Fjordlight/1.0 (Builderr hackathon; register cache)"
GLEIF_LATEST = "https://goldencopy.gleif.org/api/v2/golden-copies/publishes/latest"
BRREG_RA = "RA000472"

SOURCES = {
    "gleif_lei": {"file": "gleif/lei2.csv.zip", "licence": "CC0 1.0"},
    "gleif_rr": {"file": "gleif-rr/rr.csv.zip", "licence": "CC0 1.0"},
    "finanstilsynet": {"file": "finanstilsynet/companies.jsonl", "url": "https://api.finanstilsynet.no/registry/v2/legal-entities/filter?countryCodes=NOR&entityType=Company&pageSize=50&page={page}", "licence": "NLOD 2.0"},
    "vegvesen_workshops": {"file": "vegvesen-verksted/export.csv", "url": "https://pkkvr-finn-godkjent-verksted-backend.atlas.vegvesen.no/export-csv?query=__ALL__", "licence": "NLOD 2.0"},
    "arbeidstilsynet_cleaning": {"file": "arbeidstilsynet/renhold.xml", "url": "https://registerdata.arbeidstilsynet.no/renhold_register.xml", "licence": "NLOD 2.0"},
    "udir_kindergartens": {"file": "udir-nbr/enheter.jsonl", "url": "https://data-nbr.udir.no/v4/enheter?sidenummer={page}&antallPerSide=5000", "licence": "NLOD 2.0"},
    "udir_schools": {"file": "udir-nsr/enheter.jsonl", "url": "https://data-nsr.udir.no/v4/enheter?sidenummer={page}&antallPerSide=5000", "licence": "NLOD 2.0"},
    "fiskeridir_aquaculture": {"file": "fiskeridir-aqua/entities_nonperson.json", "url": "https://api.fiskeridir.no/pub-aqua/api/v1/entities?range={start}-{end}", "licence": "NLOD 2.0"},
    "mattilsynet_inspections": {"file": "smilefjes/tilsyn.csv", "url": "https://smilefjes.mattilsynet.no/api/tilsyn.csv", "licence": "NLOD 2.0"},
}
SMILEY = {"0": "smile (no remarks)", "1": "smile (minor remarks)", "2": "straight mouth (improvement ordered)", "3": "sad mouth (serious breaches)"}


def _get(url: str, timeout: float = 300) -> bytes:
    last: Exception | None = None
    for attempt in range(4):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.read()
        except Exception as exc:  # retried, then raised
            last = exc
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"download failed: {url}: {last}")


def _sha(value: Any) -> str:
    raw = value if isinstance(value, bytes) else json.dumps(value, ensure_ascii=False, sort_keys=True).encode()
    return hashlib.sha256(raw).hexdigest()


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def download(name: str, target: Path) -> None:
    """Download one source into ``target`` (only called when it is not already there)."""
    target.parent.mkdir(parents=True, exist_ok=True)
    spec = SOURCES[name]
    if name in {"gleif_lei", "gleif_rr"}:
        latest = json.loads(_get(GLEIF_LATEST))["data"]
        key = "lei2" if name == "gleif_lei" else "rr"
        target.write_bytes(_get(latest[key]["full_file"]["csv"]["url"], timeout=1800))
    elif name == "finanstilsynet":
        with target.open("w") as out:
            page = 1
            while True:
                body = json.loads(_get(spec["url"].format(page=page)))
                for row in body.get("legalEntities") or []:
                    out.write(json.dumps(row, ensure_ascii=False) + "\n")
                if not body.get("legalEntities") or page * 50 >= body.get("total", 0):
                    break
                page += 1
                time.sleep(0.2)
    elif name in {"udir_kindergartens", "udir_schools"}:
        with target.open("w") as out:
            page = 1
            while True:
                body = json.loads(_get(spec["url"].format(page=page)))
                for row in body.get("EnhetListe") or []:
                    out.write(json.dumps(row, ensure_ascii=False) + "\n")
                if page >= body.get("AntallSider", 1):
                    break
                page += 1
    elif name == "fiskeridir_aquaculture":
        rows, start = [], 0
        while True:
            batch = json.loads(_get(spec["url"].format(start=start, end=start + 99)))
            rows += [row for row in batch if row.get("typeValue") != "Person"]
            if len(batch) < 100:
                break
            start += 100
        target.write_text(json.dumps(rows, ensure_ascii=False))
    else:
        target.write_bytes(_get(spec["url"]))


def _csv_rows(path: Path) -> Iterator[list[str]]:
    archive = zipfile.ZipFile(path)
    yield from csv.reader(io.TextIOWrapper(archive.open(archive.namelist()[0]), encoding="utf-8"))


def gleif_entries(lei_path: Path, rr_path: Path, retrieved: dict[str, str]) -> Iterator[tuple[str, dict[str, Any]]]:
    rows = _csv_rows(lei_path)
    header = {key: index for index, key in enumerate(next(rows))}
    col = lambda row, key: row[header[key]]  # noqa: E731
    norwegian: dict[str, dict[str, Any]] = {}
    for row in rows:
        if col(row, "Entity.RegistrationAuthority.RegistrationAuthorityID") != BRREG_RA:
            continue
        org = "".join(ch for ch in col(row, "Entity.RegistrationAuthority.RegistrationAuthorityEntityID") if ch.isdigit())
        if len(org) != 9:
            continue
        norwegian[row[0]] = {
            "org": org,
            "lei": row[0],
            "legal_name": col(row, "Entity.LegalName"),
            "entity_status": col(row, "Entity.EntityStatus"),
            "registration_status": col(row, "Registration.RegistrationStatus"),
            "initial_registration": col(row, "Registration.InitialRegistrationDate")[:10],
            "last_update": col(row, "Registration.LastUpdateDate")[:10],
            "next_renewal": col(row, "Registration.NextRenewalDate")[:10],
        }
    parents: dict[str, dict[str, str]] = defaultdict(dict)
    rr = _csv_rows(rr_path)
    rr_header = {key: index for index, key in enumerate(next(rr))}
    for row in rr:
        child, kind = row[rr_header["Relationship.StartNode.NodeID"]], row[rr_header["Relationship.RelationshipType"]]
        if child in norwegian and row[rr_header["Relationship.RelationshipStatus"]] == "ACTIVE" and kind in {"IS_DIRECTLY_CONSOLIDATED_BY", "IS_ULTIMATELY_CONSOLIDATED_BY"}:
            parents[child]["direct_parent" if kind.startswith("IS_DIRECTLY") else "ultimate_parent"] = row[rr_header["Relationship.EndNode.NodeID"]]
    wanted = {lei for links in parents.values() for lei in links.values()}
    names: dict[str, dict[str, str]] = {}
    rows = _csv_rows(lei_path)
    next(rows)
    for row in rows:
        if row[0] in wanted:
            names[row[0]] = {"lei": row[0], "name": col(row, "Entity.LegalName"), "country": col(row, "Entity.LegalAddress.Country")}
    for lei, record in norwegian.items():
        org = record.pop("org")
        for role, parent in parents.get(lei, {}).items():
            record[role] = names.get(parent, {"lei": parent})
        yield org, {
            "source": "gleif_lei", "field": "lei", "unit_org": org, "value": record,
            "source_url": f"https://api.gleif.org/api/v1/lei-records/{lei}", "dataset_url": "https://www.gleif.org/en/lei-data/gleif-golden-copy",
            "retrieved_at": retrieved["gleif_lei"], "content_sha256": _sha(record), "licence": "CC0 1.0",
        }


def _entry(source: str, field: str, org: str, value: dict[str, Any], url: str, retrieved: dict[str, str], raw: Any) -> tuple[str, dict[str, Any]]:
    return org, {
        "source": source, "field": field, "unit_org": org, "value": value, "source_url": url,
        "dataset_url": SOURCES[source]["url"].split("?")[0], "retrieved_at": retrieved[source],
        "content_sha256": _sha(raw), "licence": SOURCES[source]["licence"],
    }


def licence_entries(base: Path, retrieved: dict[str, str]) -> Iterator[tuple[str, dict[str, Any]]]:
    for line in (base / SOURCES["finanstilsynet"]["file"]).open():
        row = json.loads(line)
        org = str(row.get("organisationNumber") or "")
        if len(org) != 9:
            continue
        for licence in row.get("licences") or []:
            licensed = (licence.get("licensedEntity") or {}).get("legalEntityId")
            if licence.get("serviceProviderType") == "Agent" or licensed != row.get("legalEntityId"):
                continue  # agent links name another firm's licence
            kind = (licence.get("licenceType") or {}).get("name") or {}
            value = {"register": "Finanstilsynet register of licensed entities", "authority": "Finanstilsynet", "licence": kind.get("english") or kind.get("norwegian"), "licence_no": kind.get("norwegian"), "granted": str(licence.get("registeredDate") or "")[:10] or None, "status": "registered"}
            yield _entry("finanstilsynet", "licences", org, value, f"https://www.finanstilsynet.no/virksomhetsregisteret/detalj/?id={row.get('legalEntityId')}", retrieved, licence)

    text = (base / SOURCES["vegvesen_workshops"]["file"]).read_text(encoding="utf-8-sig")
    reader = csv.reader(io.StringIO(text), delimiter=";")
    header = [cell.strip() for cell in next(reader)]
    for cells in reader:
        row = dict(zip(header, (cell.strip() for cell in cells)))
        org = row.get("Organisasjonsnummer", "")
        if len(org) == 9 and org.isdigit():
            value = {"register": "Statens vegvesen approved workshops", "authority": "Statens vegvesen", "licence": "Approved vehicle workshop", "approval_types": [item.strip() for item in row.get("Godkjenningstyper", "").split(",") if item.strip()], "approval_no": row.get("Godkjenningsnummer") or None, "status": "approved"}
            yield _entry("vegvesen_workshops", "licences", org, value, SOURCES["vegvesen_workshops"]["url"] + f"#org={org}", retrieved, row)

    root = ET.parse(base / SOURCES["arbeidstilsynet_cleaning"]["file"]).getroot()
    for node in root:
        org = (node.findtext("Organisasjonsnummer") or "").strip()
        status = (node.findtext("Status") or "").strip()
        if len(org) != 9:
            continue
        value = {"register": "Arbeidstilsynet register of cleaning companies", "authority": "Arbeidstilsynet", "licence": "Approved cleaning company" if status.startswith("Godkjent") else "Cleaning company (not approved)", "status": status, "workplaces": sorted({(unit.findtext("Organisasjonsnummer") or "").strip() for unit in node.iter("Avdeling")} - {""})}
        yield _entry("arbeidstilsynet_cleaning", "licences", org, value, SOURCES["arbeidstilsynet_cleaning"]["url"] + f"#org={org}", retrieved, ET.tostring(node))

    for source, unit_flag, owner_flag, unit_label, owner_label, host in (
        ("udir_kindergartens", "ErBarnehage", "ErBarnehageeier", "Kindergarten in Udir's kindergarten register (NBR)", "Kindergarten owner in Udir's kindergarten register (NBR)", "data-nbr.udir.no"),
        ("udir_schools", "ErSkole", "ErSkoleeier", "School in Udir's school register (NSR)", "School owner in Udir's school register (NSR)", "data-nsr.udir.no"),
    ):
        for line in (base / SOURCES[source]["file"]).open():
            row = json.loads(line)
            org = row.get("Organisasjonsnummer") or ""
            if not (len(org) == 9 and org.isdigit()) or not (row.get(owner_flag) or (row.get(unit_flag) and row.get("ErAktiv"))):
                continue
            categories = [item.get("Navn") for item in (row.get("Barnehagekategorier") or row.get("Skolekategorier") or []) if item.get("Navn")]
            value = {"register": unit_label.split(" in ")[1], "authority": "Utdanningsdirektoratet", "licence": owner_label.split(" in ")[0] if row.get(owner_flag) else unit_label.split(" in ")[0], "name": row.get("FulltNavn") or row.get("Navn"), "categories": categories, "active": bool(row.get("ErAktiv")), "status": "active" if row.get("ErAktiv") else "owner", "changed": str(row.get("DatoEndret") or "")[:10] or None}
            yield _entry(source, "licences", org, value, f"https://{host}/v4/enhet/{org}", retrieved, row)

    for row in json.loads((base / SOURCES["fiskeridir_aquaculture"]["file"]).read_text()):
        org = str(row.get("openNr") or "")
        if len(org) != 9 or row.get("typeValue") == "Person" or row.get("status") != "ACTIVE":
            continue
        types = [item.get("name") for item in row.get("businessTypes") or [] if item.get("value") == "Aquaculture"]
        if not types:
            continue
        value = {"register": "Fiskeridirektoratet aquaculture register", "authority": "Fiskeridirektoratet", "licence": "Registered aquaculture operator", "status": "active", "valid_from": str(row.get("versionValidFrom") or "")[:10] or None}
        yield _entry("fiskeridir_aquaculture", "licences", org, value, f"https://api.fiskeridir.no/pub-aqua/api/v1/entities/{row.get('id')}", retrieved, row)


def inspection_entries(base: Path, retrieved: dict[str, str]) -> Iterator[tuple[str, dict[str, Any]]]:
    text = (base / SOURCES["mattilsynet_inspections"]["file"]).read_text(encoding="utf-8-sig")
    reader = csv.reader(io.StringIO(text), delimiter=";")
    header = next(reader)
    latest: dict[str, dict[str, str]] = {}
    for cells in reader:
        if len(cells) != len(header):
            continue  # a stray semicolon in a name shifts the columns; skip rather than misread
        row = dict(zip(header, cells))
        day = row.get("dato", "")
        if len(row.get("orgnummer", "")) != 9 or len(day) != 8 or row.get("total_karakter") not in SMILEY:
            continue
        row["iso_date"] = f"{day[4:]}-{day[2:4]}-{day[:2]}"
        key = row["tilsynsobjektid"]
        if key not in latest or row["iso_date"] > latest[key]["iso_date"]:
            latest[key] = row
    for row in latest.values():
        value = {"premises": row.get("navn"), "town": (row.get("poststed") or "").title() or None, "inspected": row["iso_date"], "grade": int(row["total_karakter"]), "result": SMILEY[row["total_karakter"]], "inspection_id": row.get("tilsynid")}
        raw = {key: row.get(key) for key in header if key not in {"adrlinje1", "adrlinje2"}}
        yield _entry("mattilsynet_inspections", "food_inspections", row["orgnummer"], value, SOURCES["mattilsynet_inspections"]["url"] + f"#tilsynid={row.get('tilsynid')}", retrieved, raw)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--sources-dir", default=str(ROOT / "cache" / "register_sources"))
    parser.add_argument("--output", default=str(ROOT / "data" / "cache" / "registers.jsonl.gz"))
    args = parser.parse_args()
    base = Path(args.sources_dir)
    retrieved, file_hashes = {}, {}
    for name, spec in SOURCES.items():
        path = base / spec["file"]
        if not path.exists():
            print(f"downloading {name}", flush=True)
            download(name, path)
        retrieved[name] = _iso(path.stat().st_mtime)
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1 << 20), b""):
                digest.update(chunk)
        file_hashes[name] = digest.hexdigest()
    entries: dict[str, list[dict[str, Any]]] = defaultdict(list)
    counts: dict[str, int] = defaultdict(int)
    for producer in (gleif_entries(base / SOURCES["gleif_lei"]["file"], base / SOURCES["gleif_rr"]["file"], retrieved), licence_entries(base, retrieved), inspection_entries(base, retrieved)):
        for org, entry in producer:
            entries[org].append(entry)
            counts[entry["source"]] += 1
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(output, "wt", encoding="utf-8") as out:
        for org in sorted(entries):
            out.write(json.dumps({"org": org, "entries": entries[org]}, ensure_ascii=False, separators=(",", ":")) + "\n")
    state = {
        "built_at": _iso(time.time()),
        "organisations": len(entries),
        "entries_by_source": dict(sorted(counts.items())),
        "sources": {name: {"file_retrieved_at": retrieved[name], "file_sha256": file_hashes[name], "licence": spec["licence"], "url": spec.get("url", GLEIF_LATEST)} for name, spec in SOURCES.items()},
    }
    (output.parent / "registers_state.json").write_text(json.dumps(state, indent=2) + "\n")
    print(json.dumps(state["entries_by_source"]), len(entries), "organisations")


if __name__ == "__main__":
    main()
