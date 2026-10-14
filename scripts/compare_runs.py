#!/usr/bin/env python3
"""Compare two runs' profiles: module states and evidence values, ignoring run-time stamps.

Used to prove a change is behaviour-preserving (e.g. adding logging or the request gate).
Live sources can legitimately change between runs; differences are listed, not hidden.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

VOLATILE = {"retrieved_at", "run_metrics", "latencies_ms"}


def strip(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: strip(child) for key, child in value.items() if key not in VOLATILE}
    if isinstance(value, list):
        return [strip(child) for child in value]
    return value


def load(path: str) -> dict[str, dict[str, Any]]:
    rows = [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]
    return {row["organisation_number"]: row for row in rows}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("before")
    parser.add_argument("after")
    args = parser.parse_args()
    before, after = load(args.before), load(args.after)
    report: dict[str, Any] = {
        "same_companies": sorted(before) == sorted(after),
        "companies": len(after),
        "state_differences": [],
        "value_differences": [],
    }
    for org in sorted(set(before) & set(after)):
        modules = sorted(set(before[org].get("evidence", {})) | set(after[org].get("evidence", {})))
        for module in modules:
            old = before[org].get("evidence", {}).get(module) or {}
            new = after[org].get("evidence", {}).get(module) or {}
            if old.get("status") != new.get("status"):
                report["state_differences"].append({"organisation_number": org, "module": module, "before": old.get("status"), "after": new.get("status")})
            elif strip(old) != strip(new):
                report["value_differences"].append({"organisation_number": org, "module": module})
    report["identical"] = report["same_companies"] and not report["state_differences"] and not report["value_differences"]
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
