# Signalpost entry (built on the Builderr reference agent)

This repository is an entry for Builderr's Signalpost challenge. It starts from the official
starter kit (imported unchanged in the first commit) and adds safety rails, NAV job ads and
strictly verified website discovery. The kit's own README follows below this section.

## Install and run

Requires Python 3.12+ and [uv](https://docs.astral.sh/uv/).

```bash
make install                      # uv sync --frozen (pinned by uv.lock)
make run INPUT=<batch file> OUT=<output dir> BULK=<frozen Brreg bulk CSV (.csv.gz)>
```

`INPUT` is a JSON, JSONL or text list of organisation numbers. Outputs in `OUT`:
`envelopes.jsonl` (one terminal envelope per input), `profiles.jsonl`, `report.json`
(runtime, request counts, gate and module states) and `family_coverage.json`.
`make registry` downloads the current Brreg bulk file to `cache/brreg-enheter.csv.gz` for local runs.

## Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `NAV_FEED_TOKEN` | unset | Private NAV job-feed token. Unset: NAV's public token is fetched at run start. |
| `SIGNALPOST_WEB_REQUEST_CAP` | 1900 | Cap on non-registry outbound requests per run. |
| `SIGNALPOST_REGISTRY_REQUEST_CAP` | unset | Optional cap on Brønnøysund API requests. |
| `SIGNALPOST_DEADLINE_SECONDS` | 2280 | Stop fetching this long after start (38 min); envelopes are always written. |

## Declared cache

`data/cache/nav_ads.jsonl.gz` holds the NAV job ads that were active when it was built
(`make cache`, see `data/cache/nav_feed_state.json` for build time and counts). Each ad keeps its
own detail URL, real retrieval time and content hash. Contact details and ad descriptions are not
stored. At run start the feed is read forward from the cache's last page, so ads that have since
closed are dropped and new ads can still be matched.

## Sources, licences and cost

| Source | Use | Terms |
|---|---|---|
| Brønnøysundregistrene (Enhetsregisteret, Regnskapsregisteret) | identity, accounts, roles, subunits, contact index | NLOD 2.0 |
| NAV job vacancy feed (pam-stilling-feed) | active job ads matched by employer orgnr | NAV API terms of use |
| Company websites | only after strict identity proof, robots.txt respected | per-site robots/terms |

No LLM and no paid API are used. Expected third-party cost per official run: $0.

## Safety rails

Every outbound request goes through one gate (`src/norway_company_agent/gate.py`): web cap,
optional registry cap, 1 s spacing per host, 10 s timeout, one retry. Fetching stops at the
deadline and every input still gets an envelope (`budget_exhausted` where work was cut short).
Website identity rules are in `IDENTITY_RESOLUTION.md`. `make clean-install-check` clones HEAD
into a temp folder, installs into a fresh venv and runs tests, the refresh replay and a live smoke.

---

# Signalpost reference agent

This is a runnable starting point for the Signalpost company-research challenge. It is intentionally a solid baseline, not a winning submission.

The public universe contains 411,160 eligible companies. Run the starter on 100 companies before submitting. Larger local tests, including 1,000 or more companies, are encouraged but their precomputed profiles are not submitted or scored.

## What it already does

- reads a batch of Norwegian organisation numbers;
- anchors identity in the Brønnøysund bulk registry;
- fetches official financials, roles, group links and registered workplaces;
- visits the registry-listed website and rejects weak entity matches;
- emits one terminal JSONL envelope per input;
- records sources, retrieval times, content hashes, request counts and latency;
- supports checkpoint/resume and a deterministic refresh replay;
- includes examples for external-footprint discovery and an evidence-bounded research agent.

## First run: try one saved example

Requires Python 3.12+. Open a terminal inside this extracted folder.

Before downloading company data or running a full crawl, try the bundled public
sample. It uses saved responses: no API key, registry download or live web requests.

```bash
python3 scripts/run_refresh_replay.py \
  --manifest tests/fixtures/refresh-snapshots.json \
  --output out/refresh-demo.json
```

Open `out/refresh-demo.json`. The `events` list shows what changed between two
versions of one company profile and the source evidence for each change. The sample
should find two expected changes, no false changes, and no extra changes when the
same data is checked again.

The report's `qualification_passed` field refers only to this public sample check.
It does not qualify an entry for the competition or prove live information coverage.
The printed request counts are reads from saved responses, not network calls.

## Next: research live companies

Requires Python 3.12+ and `uv`. This step downloads data and makes live requests.
The manifest selector can create a local test batch of any size. Use 100 rows for the recommended smoke test before trying a larger batch.

```bash
uv sync
curl -L 'https://data.brreg.no/enhetsregisteret/api/enheter/lastned/csv' -o brreg-enheter.csv
curl -L 'https://builderr.ai/signalpost-company-universe-2025.jsonl.gz' -o signalpost-universe.jsonl.gz

uv run python select_entry_batch.py \
  --universe signalpost-universe.jsonl.gz \
  --count 100 \
  --output entry-companies.jsonl

# Use the 100-company batch as your smoke test.
cp entry-companies.jsonl smoke-companies.jsonl

uv run python scripts/run_competition_batch.py \
  --organisations smoke-companies.jsonl \
  --bulk brreg-enheter.csv \
  --profiles-output out/smoke-profiles.jsonl \
  --output out/smoke-envelopes.jsonl \
  --report out/smoke-report.json \
  --run-id smoke-001 \
  --expected-count 100

# You may test at larger scale locally, but Builderr supplies the official batch for scoring.
uv run python scripts/run_competition_batch.py \
  --organisations entry-companies.jsonl \
  --bulk brreg-enheter.csv \
  --profiles-output out/profiles.jsonl \
  --output out/envelopes.jsonl \
  --report out/run-report.json \
  --run-id local-001 \
  --expected-count 1000

uv run --with pytest pytest -q
```

The published archive was clean-room verified on August 24, 2026: 104 tests and 5 subtests passed, followed by a one-company live BRREG smoke run with one terminal envelope, five requests and zero silent drops.

Increase `--count` and `--expected-count` together for a larger local test. The 100-row smoke test above is practice only; Builderr supplies the companies for every official run.

## The improvement loop

1. Treat the organisation number as the anchor.
2. Generate site/profile candidates from official data, the company site, lawful search providers and named people.
3. Save every candidate and the evidence for or against it.
4. Publish only exact-entity matches. Parent, brand, franchise and similarly named companies are not exact.
5. Crawl static HTML first. Escalate to a browser only when a deterministic completeness check fails.
6. Measure added supported coverage, wrong-company claims, runtime, requests and cost.
7. Promote a strategy only when it improves coverage without weakening the accuracy gates.
8. Freeze strategies and thresholds before the daily evaluation run.

The strongest differentiator is external evidence that remains exact and auditable: official company pages, company-owned profiles, jobs, dated activity, ratings/reviews and permitted public signals. Do not trade accuracy for volume.

## Important source rule

Open-source code does not grant permission to scrape a platform. Follow each source's terms, robots policy, rate limits and licence. LinkedIn, Meta and Indeed are useful identity/discovery targets, but direct automated collection may be restricted. Use permitted APIs, licensed providers, company-owned outbound links, or return `blocked`/`not_available`.

Read `docs/competition-control-loop.md`, `docs/external-connectors.md` and the public source policy before adding connectors.

## Submission contract

Submit a repository with:

- a 100-company smoke-test result or report;
- one documented command that accepts a JSONL batch of organisation numbers;
- exactly one terminal envelope per input;
- pinned dependencies and reproducible setup;
- a previous-snapshot input and material-change output;
- a machine-readable run report with runtime, request count and third-party cost;
- declared models, APIs, licences and source-rights assumptions.

Email the repository URL, run command, models/APIs and expected cost per 100-company run to `submit@builderr.ai`.
