#!/usr/bin/env python3
"""Per-company, per-field-family coverage report for a batch run.

Reads the profiles JSONL written by scripts/run_competition_batch.py and reports,
for every field family, how many companies have at least one published fact
(company coverage), how many facts were published, and the evidence states seen.
This is a local proxy for the organiser's recall families, not the official score.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any, Callable

# Field families from the Signalpost brief. Families with no connector yet are
# listed so the report shows the gap instead of hiding it.
FAMILIES: list[tuple[str, str | None]] = [
    ("legal_identity", "registry_live"),
    ("annual_accounts", "financials"),
    ("accounts_history", "financial_history"),
    ("leadership_roles", "roles"),
    ("group_structure", "group"),
    ("registered_workplaces", "locations"),
    ("official_website", "website"),
    ("social_profiles", "website"),
    ("hiring", "jobs"),
    ("dated_activity", None),
]


def _value(profile: dict[str, Any], module: str) -> tuple[str, Any]:
    record = profile.get("evidence", {}).get(module)
    if not record:
        return "not_run", None
    return str(record.get("status")), record.get("value")


def _facts(family: str, profile: dict[str, Any]) -> int:
    module = dict(FAMILIES)[family]
    if module is None:
        return 0
    status, value = _value(profile, module)
    if status != "available" or value is None:
        return 0
    counters: dict[str, Callable[[Any], int]] = {
        "legal_identity": lambda v: int(bool(v.get("name"))),
        "annual_accounts": lambda v: len(v.get("records") or []),
        "accounts_history": lambda v: len(v.get("years") or []),
        "leadership_roles": lambda v: sum(1 for role in v.get("roles") or [] if not role.get("inactive")),
        "group_structure": lambda v: int(bool(v)),
        "registered_workplaces": lambda v: len(v.get("locations") or []),
        "official_website": lambda v: int(bool((v.get("identity_assessment") or {}).get("publishable"))),
        "social_profiles": lambda v: len(v.get("social_links") or []) if (v.get("identity_assessment") or {}).get("publishable") else 0,
        "hiring": lambda v: len(v.get("active_ads") or []),
    }
    return counters[family](value)


def build_report(profiles: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(profiles)
    families: dict[str, Any] = {}
    for family, module in FAMILIES:
        facts = [_facts(family, profile) for profile in profiles]
        states = Counter(_value(profile, module)[0] if module else "no_connector" for profile in profiles)
        covered = sum(1 for count in facts if count > 0)
        families[family] = {
            "module": module,
            "companies_covered": covered,
            "company_coverage": round(covered / n, 3) if n else 0.0,
            "facts": sum(facts),
            "states": dict(sorted(states.items())),
        }
    per_company = []
    for profile in profiles:
        metrics = profile.get("run_metrics") or {}
        per_company.append({
            "organisation_number": profile["organisation_number"],
            "requests": metrics.get("requests"),
            "registry_requests": metrics.get("registry_requests"),
            "web_requests": metrics.get("web_requests"),
            "families": {family: _facts(family, profile) for family, _ in FAMILIES},
            "states": {module: status for module, status in ((m, _value(profile, m)[0]) for m in sorted({m for _, m in FAMILIES if m}))},
        })
    proof_types = Counter(
        ((profile.get("evidence", {}).get("website") or {}).get("value") or {}).get("identity_assessment", {}).get("method", "none")
        for profile in profiles
        if _facts("official_website", profile)
    )
    website_registered = sum(1 for profile in profiles if str(profile.get("website") or "").strip())
    return {
        "companies": n,
        "registry_website_listed": website_registered,
        "total_requests": sum(item["requests"] or 0 for item in per_company),
        "website_publication_methods": dict(proof_types),
        "families": families,
        "per_company": per_company,
    }


def markdown_table(report: dict[str, Any]) -> str:
    lines = [
        "| Family | Companies covered | Facts | States |",
        "|---|---:|---:|---|",
    ]
    for family, row in report["families"].items():
        states = ", ".join(f"{key} {value}" for key, value in row["states"].items())
        lines.append(f"| {family} | {row['companies_covered']}/{report['companies']} | {row['facts']} | {states} |")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profiles", required=True)
    parser.add_argument("--output", required=True, help="JSON report path")
    args = parser.parse_args()
    profiles = [json.loads(line) for line in Path(args.profiles).read_text(encoding="utf-8").splitlines() if line.strip()]
    report = build_report(profiles)
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(markdown_table(report))
    print(f"\nCompanies: {report['companies']}  registry website listed: {report['registry_website_listed']}  total requests: {report['total_requests']}")


if __name__ == "__main__":
    main()
