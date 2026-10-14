# Step 1: baseline and safety rails (dev100, 2026-10-14)

Inputs: `data/dev100.txt` (100 random orgnrs from the public universe, seed 20261014).
`data/val100.txt` is a disjoint hold-out and has not been run.
Registry: Brreg bulk CSV downloaded 2026-10-14 (sha256 `18834432…3d72`).
Universe archive sha256 matches the evaluation contract (`1c89710e…0384`).

## Baseline coverage (starter kit unchanged)

| Family | Companies covered | Facts | Module states |
|---|---:|---:|---|
| legal_identity | 100/100 | 100 | available 100 |
| annual_accounts | 100/100 | 284 | available 100 |
| accounts_history | 0/100 | 0 | module not in default run |
| leadership_roles | 100/100 | 362 | available 100 |
| group_structure | 9/100 | 9 | available 9, not_found 91 |
| registered_workplaces | 75/100 | 92 | available 100 |
| official_website | 3/100 | 3 | registry lists a site for 6; 3 pass the identity gate |
| social_profiles | 1/100 | 2 | from the 3 verified sites |
| hiring | 0/100 | 0 | no connector |
| dated_activity | 0/100 | 0 | no connector |

Runtime 77 s for 100 companies with 8 workers (about 20 s of that is scanning the bulk CSV).
Requests: 500 registry (5 per company) + 48 web = 548 (the kit's own counter said 542; it misses redirects).

## Safety rails

- `src/norway_company_agent/gate.py`: every outbound request goes through one gate. Web cap 1,900 by default
  (`--web-request-cap`, `SIGNALPOST_WEB_REQUEST_CAP`), optional registry cap, 1 s spacing per non-registry
  host, 10 s socket timeout, at most one retry. Refused requests become `blocked` evidence and the module's
  terminal state is `budget_exhausted`.
- Wall-clock guard in `scripts/run_competition_batch.py`: fetching stops 38 min after process start
  (`--deadline-seconds`, `SIGNALPOST_DEADLINE_SECONDS`). After a further 60 s grace, envelopes are written for
  every company anyway. A crash inside one company becomes `source_error` for that company only. The run
  asserts one envelope per input before writing.
- `scripts/clean_install_check.sh` (`make clean-install-check`): clones HEAD, `uv sync --frozen` into a fresh
  venv, runs the tests, the offline refresh replay and a 5-company live smoke.

## Checks

| Check | Result |
|---|---|
| dev100 rerun with gate vs baseline | same companies, zero state differences; 5 website records differ only in page content hashes (dynamic HTML), extracted values identical |
| Web cap 5 + 60 s deadline | 100/100 envelopes, validation passed, 64 refused requests, modules marked `budget_exhausted` |
| 1 s deadline, no grace (hard-stop path) | 100/100 envelopes, validation passed |
| Clean install at HEAD | passed (tests, replay, 5-company live smoke) |

## Findings that matter for later steps

1. Only 6 of 100 companies list a website in the registry, so website discovery is where recall comes from.
2. If registry calls count toward the 2,000-request limit, the starter kit alone needs about 5,000 for a
   1,000-company batch. This needs the organisers' answer; the gate can cap registry calls, but doing so
   would leave most registry modules `budget_exhausted`.
3. Live pages change their bytes between runs (5 of 6 sites), so refresh change detection must compare
   extracted values, not page hashes, or it will report false changes.
4. Runtime scales to roughly 12 to 13 min per 1,000 companies at this request mix, well inside 38 min.
