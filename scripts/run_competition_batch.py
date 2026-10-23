#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout, as_completed
from pathlib import Path

PROCESS_STARTED = time.monotonic()

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from norway_company_agent.batch import profile_complete_for_modules, profiles_from_bulk, read_organisation_inputs, terminal_envelope, validate_envelopes  # noqa: E402
from norway_company_agent.evidence import evidence, utc_now  # noqa: E402
from norway_company_agent.gate import BUDGET_PREFIX, GATE  # noqa: E402
from norway_company_agent.identity import apply_website_identity_gate  # noqa: E402
from norway_company_agent.identity_index import IdentityIndex  # noqa: E402
from norway_company_agent.jobs import JobsIndex, normalize_name  # noqa: E402
from norway_company_agent.site_verify import discover_website, publish_discovered_site  # noqa: E402
from norway_company_agent.official import fetch_official_modules  # noqa: E402
from norway_company_agent.registry_site import apply_registry_declared_rule  # noqa: E402
from norway_company_agent.timeline import build_official_timeline  # noqa: E402
from norway_company_agent.site_scope import apply_site_scope_guard  # noqa: E402
from norway_company_agent.website import fetch_website  # noqa: E402


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
    temporary.replace(path)


def _env_number(name: str, default: float | None) -> float | None:
    value = os.environ.get(name, "").strip()
    return float(value) if value else default


# Modules not fetched by fetch_official_modules; they are built later in _enrich.
DERIVED_MODULES = ("website", "jobs", "website_discovery", "official_timeline")


def unfinished_profile(profile: dict, fetch_modules: set[str], requested_modules: list[str], note: str, status: str = "blocked") -> dict:
    """Give a company that was not (fully) processed an honest terminal record for every module."""
    records = profile.setdefault("evidence", {})
    for module in [*sorted(fetch_modules), *[name for name in DERIVED_MODULES if name in requested_modules]]:
        if module not in records:
            records[module] = evidence(module, status, "run_guard", "about:signalpost-run-guard", note=note)
    profile.setdefault("run_metrics", {"requests": 0, "bytes": 0, "latencies_ms": []})
    return profile


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluator-owned Signalpost batch contract")
    parser.add_argument("--organisations", required=True, help="JSON, JSONL, or text organisation-number list")
    parser.add_argument("--bulk", required=True, help="Frozen Brreg entity snapshot")
    parser.add_argument("--output", required=True, help="Terminal envelope JSONL")
    parser.add_argument("--profiles-output", required=True)
    parser.add_argument("--report", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--expected-count", type=int, default=None, help="Defaults to the number of input organisations")
    parser.add_argument("--deadline-seconds", type=float, default=_env_number("SIGNALPOST_DEADLINE_SECONDS", 38 * 60), help="Stop fetching this long after process start (default 38 min)")
    parser.add_argument("--hard-stop-grace-seconds", type=float, default=60.0, help="After the deadline, wait this long for in-flight companies before writing envelopes anyway")
    parser.add_argument("--web-request-cap", type=int, default=int(os.environ["SIGNALPOST_WEB_REQUEST_CAP"]) if os.environ.get("SIGNALPOST_WEB_REQUEST_CAP") else None, help="Optional non-registry outbound request cap (env SIGNALPOST_WEB_REQUEST_CAP); the total cap always applies")
    parser.add_argument("--total-request-cap", type=int, default=GATE.total_cap, help="All outbound requests (registry, web, retries, redirects) per run; default 19 per company (Builderr counts 2,000 per 100; env SIGNALPOST_TOTAL_REQUEST_CAP)")
    parser.add_argument("--registry-request-cap", type=int, default=GATE.registry_cap, help="Optional registry request cap (env SIGNALPOST_REGISTRY_REQUEST_CAP)")
    parser.add_argument("--host-interval-seconds", type=float, default=1.0, help="Minimum gap between requests to one non-registry host")
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--checkpoint-every", type=int, default=25)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--modules", default="registry,accounting_obligation,registry_live,financials,financial_history,roles,group,locations,website,jobs,website_discovery,official_timeline")
    parser.add_argument("--cache-dir", default=str(ROOT / "data" / "cache"), help="Declared cache directory (NAV ads)")
    parser.add_argument("--nav-max-pages", type=int, default=60, help="Max NAV feed pages read at run start to bring the cache up to date")
    args = parser.parse_args()

    started_at = utc_now()
    organisation_inputs = read_organisation_inputs(args.organisations)
    orgs = [item["organisation_number"] for item in organisation_inputs]
    if args.expected_count is None:
        args.expected_count = len(orgs)
    if len(orgs) != args.expected_count:
        raise SystemExit(f"Expected {args.expected_count} organisations, received {len(orgs)}")
    profiles, registry_metadata = profiles_from_bulk(args.bulk, orgs)
    annotations = {item["organisation_number"]: item for item in organisation_inputs}
    for profile in profiles:
        for key in ("evaluation_split", "sample_slice"):
            if key in annotations[profile["organisation_number"]]:
                profile[key] = annotations[profile["organisation_number"]][key]
    requested_modules = [item.strip() for item in args.modules.split(",") if item.strip()]
    fetch_modules = set(requested_modules) - {"registry", "accounting_obligation", *DERIVED_MODULES}
    operations = {"requests": 0, "bytes": 0, "latencies_ms": []}
    GATE.configure(
        web_cap=args.web_request_cap,
        registry_cap=args.registry_request_cap,
        total_cap=args.total_request_cap if args.total_request_cap is not None else 19 * len(orgs),
        deadline_s=args.deadline_seconds,
        host_interval=args.host_interval_seconds,
        started_at=PROCESS_STARTED,
    )

    run_setup: dict = {}
    identity_index = None
    if {"website", "website_discovery"} & set(requested_modules):
        setup_started = time.monotonic()
        identity_index = IdentityIndex.from_bulk(args.bulk)
        run_setup["identity_index"] = {**identity_index.summary(), "seconds": round(time.monotonic() - setup_started, 1)}
    jobs_index = None
    if "jobs" in requested_modules:
        setup_started = time.monotonic()
        jobs_index = JobsIndex(args.cache_dir)
        run_setup["nav_feed"] = {**jobs_index.refresh(max_pages=args.nav_max_pages), "seconds": round(time.monotonic() - setup_started, 1)}

    def enrich(profile: dict) -> tuple[dict, dict]:
        GATE.begin_company(profile["organisation_number"])
        try:
            return _enrich(profile)
        except Exception as exc:  # one company's crash must never cost the batch its envelopes
            unfinished_profile(profile, fetch_modules, requested_modules, f"agent error: {type(exc).__name__}: {str(exc)[:160]}", status="source_error")
            profile["run_metrics"].update(GATE.company_counts(profile["organisation_number"]))
            return profile, profile["run_metrics"]
        finally:
            GATE.begin_company(None)

    def _enrich(profile: dict) -> tuple[dict, dict]:
        records, metrics = fetch_official_modules(profile["organisation_number"], fetch_modules)
        profile["evidence"].update(records)
        website_metrics = {"requests": 0, "bytes": 0, "latencies_ms": []}
        if "website" in requested_modules:
            website_record, website_metrics = fetch_website(profile.get("website"))
            profile["evidence"]["website"] = apply_website_identity_gate(profile, website_record)["website"]
            if identity_index is not None:
                apply_registry_declared_rule(profile, profile["evidence"]["website"], identity_index)
        jobs_record = None
        if jobs_index is not None:
            locations = (profile["evidence"].get("locations") or {}).get("value") or {}
            subunits = {str(item["organisation_number"]): item.get("name") for item in locations.get("locations") or [] if item.get("organisation_number")}
            names = {normalize_name(name): orgnr for orgnr, name in subunits.items() if normalize_name(name)}
            names[normalize_name(profile.get("name"))] = profile["organisation_number"]
            jobs_record = jobs_index.lookup(profile["organisation_number"], names, subunits)
            profile["evidence"]["jobs"] = jobs_record
        if "website_discovery" in requested_modules and identity_index is not None:
            discovery = discover_website(profile, identity_index, jobs_record)
            profile["evidence"]["website_discovery"] = discovery
            if discovery["status"] == "available":
                site_record, site_metrics = fetch_website(discovery["value"]["verified_url"], max_secondary_pages=2)
                website_metrics = {key: website_metrics[key] + site_metrics[key] for key in ("requests", "bytes", "latencies_ms")}
                if site_record["status"] == "available":
                    discovery["value"]["replaced_website_record"] = {key: (profile["evidence"].get("website") or {}).get(key) for key in ("status", "source_url", "note")}
                    profile["evidence"]["website"] = publish_discovered_site(profile, site_record, discovery)
        if identity_index is not None and "website" in requested_modules:
            apply_site_scope_guard(profile["evidence"]["website"], identity_index, profile)
        if "official_timeline" in requested_modules:
            profile["evidence"]["official_timeline"] = build_official_timeline(profile)
        metric = {
            "requests": len(metrics) + website_metrics["requests"],
            "bytes": sum(item.bytes_received for item in metrics) + website_metrics["bytes"],
            "latencies_ms": [item.elapsed_ms for item in metrics] + website_metrics["latencies_ms"],
        }
        metric.update(GATE.company_counts(profile["organisation_number"]))
        profile["run_metrics"] = metric
        return profile, metric

    state: dict[str, dict] = {}
    resumed_profiles = 0
    profiles_output = Path(args.profiles_output)
    if args.resume and profiles_output.exists():
        prior = [json.loads(line) for line in profiles_output.read_text(encoding="utf-8").splitlines() if line.strip()]
        if not set(item["organisation_number"] for item in prior).issubset(set(orgs)):
            raise SystemExit("Resume profile membership is not a subset of this batch")
        state = {
            item["organisation_number"]: item
            for item in prior
            if profile_complete_for_modules(item, requested_modules)
        }
        resumed_profiles = len(state)
    pending_profiles = [profile for profile in profiles if profile["organisation_number"] not in state]
    hard_stopped = False
    pool = ThreadPoolExecutor(max_workers=args.workers)
    futures = {pool.submit(enrich, profile): profile["organisation_number"] for profile in pending_profiles}
    hard_stop_after = None
    if args.deadline_seconds is not None:
        hard_stop_after = max(0.0, args.deadline_seconds + args.hard_stop_grace_seconds - (time.monotonic() - PROCESS_STARTED))
    try:
        for index, future in enumerate(as_completed(futures, timeout=hard_stop_after), 1):
            profile, metric = future.result()
            state[profile["organisation_number"]] = profile
            operations["requests"] += metric["requests"]
            operations["bytes"] += metric["bytes"]
            operations["latencies_ms"].extend(metric["latencies_ms"])
            if index % args.checkpoint_every == 0 or index == len(pending_profiles):
                checkpoint = [state[org] for org in orgs if org in state]
                write_jsonl(profiles_output, checkpoint)
    except FuturesTimeout:
        hard_stopped = True
    pool.shutdown(wait=not hard_stopped, cancel_futures=True)
    by_org = {profile["organisation_number"]: profile for profile in pending_profiles}
    for org in orgs:
        if org not in state:
            # Still running or never started when the hard stop fired: write an honest record now.
            # Copy so a still-running worker thread cannot mutate what we serialise.
            profile = json.loads(json.dumps({key: value for key, value in by_org[org].items() if key != "evidence"}))
            profile["evidence"] = dict(by_org[org].get("evidence", {}))
            state[org] = unfinished_profile(profile, fetch_modules, requested_modules, f"{BUDGET_PREFIX}: wall-clock hard stop before this company finished")

    completed_at = utc_now()
    ordered_profiles = [state[org] for org in orgs]
    envelopes = [
        terminal_envelope(profile, run_id=args.run_id, modules=requested_modules, started_at=started_at, completed_at=completed_at)
        for profile in ordered_profiles
    ]
    validation = validate_envelopes(envelopes, args.expected_count)
    assert len(envelopes) == len(orgs) and [item["organisation_number"] for item in envelopes] == orgs, "envelope count must equal input count"

    write_jsonl(profiles_output, ordered_profiles)
    write_jsonl(Path(args.output), envelopes)
    latencies = sorted(operations.pop("latencies_ms"))
    operations["p50_ms"] = latencies[len(latencies) // 2] if latencies else None
    operations["p95_ms"] = latencies[min(len(latencies) - 1, int(len(latencies) * 0.95))] if latencies else None
    report = {
        "run_id": args.run_id,
        "started_at": started_at,
        "completed_at": completed_at,
        "expected_count": args.expected_count,
        "emitted_envelopes": len(envelopes),
        "resumed_profiles": resumed_profiles,
        "profiles_fetched_this_run": len(pending_profiles),
        "modules": requested_modules,
        "registry": registry_metadata,
        "operations": operations,
        "run_setup": run_setup,
        "gate": {**GATE.summary(), "hard_stopped": hard_stopped, "elapsed_s": round(time.monotonic() - PROCESS_STARTED, 1)},
        "module_states": {
            module: dict(sorted(Counter(envelope["modules"][module]["state"] for envelope in envelopes).items()))
            for module in requested_modules
        },
        "validation": validation,
    }
    Path(args.report).parent.mkdir(parents=True, exist_ok=True)
    Path(args.report).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    code = 0 if validation["passed"] else 1
    if hard_stopped:
        # Worker threads may still be blocked on sockets; outputs are written, so leave now.
        sys.stdout.flush()
        os._exit(code)
    raise SystemExit(code)


if __name__ == "__main__":
    main()
