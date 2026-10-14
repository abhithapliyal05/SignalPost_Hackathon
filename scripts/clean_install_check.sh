#!/usr/bin/env bash
# Clone this repo at HEAD into a temp folder, install with only the declared step
# (`make install`, i.e. `uv sync --frozen`), then run the tests, the offline refresh
# replay and a small live smoke run. Exits non-zero on any failure.
#
# Env: BULK=<path to Brreg bulk CSV (.csv.gz)>  defaults to this repo's cache/brreg-enheter.csv.gz
#      SMOKE_COUNT=<companies for the live smoke> defaults to 5; set 0 to skip the live run.
set -euo pipefail

REPO="$(git -C "$(dirname "$0")/.." rev-parse --show-toplevel)"
HEAD="$(git -C "$REPO" rev-parse HEAD)"
BULK="${BULK:-$REPO/cache/brreg-enheter.csv.gz}"
SMOKE_COUNT="${SMOKE_COUNT:-5}"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

if [ -n "$(git -C "$REPO" status --porcelain --untracked-files=no)" ]; then
  echo "note: uncommitted changes are NOT part of this check (it tests HEAD $HEAD)"
fi

echo "== clone $HEAD"
git clone --quiet --no-local "$REPO" "$WORK/repo"
cd "$WORK/repo"
git checkout --quiet "$HEAD"

echo "== install (fresh venv)"
export UV_PROJECT_ENVIRONMENT="$WORK/repo/.venv"
make install

echo "== tests"
make test

echo "== offline refresh replay"
make replay OUT="$WORK/out"
python3 -c "import json,sys; r=json.load(open(sys.argv[1])); assert r['qualification_passed'], r; print('replay qualification_passed: True')" "$WORK/out/refresh-demo.json"

if [ "$SMOKE_COUNT" != "0" ]; then
  if [ ! -f "$BULK" ]; then
    echo "missing Brreg bulk file at $BULK (run 'make registry' or set BULK=...)" >&2
    exit 1
  fi
  echo "== live smoke on $SMOKE_COUNT companies"
  head -n "$SMOKE_COUNT" data/dev100.txt > "$WORK/smoke.txt"
  make run INPUT="$WORK/smoke.txt" OUT="$WORK/smoke" BULK="$BULK" RUN_ID="clean-install-check"
  python3 - "$WORK/smoke" "$SMOKE_COUNT" <<'PY'
import json, sys
out, n = sys.argv[1], int(sys.argv[2])
envelopes = [json.loads(line) for line in open(f"{out}/envelopes.jsonl") if line.strip()]
report = json.load(open(f"{out}/report.json"))
assert len(envelopes) == n, (len(envelopes), n)
assert report["validation"]["passed"], report["validation"]
print(f"smoke: {len(envelopes)} envelopes for {n} inputs, {report['gate']['total_requests']} requests")
PY
fi

echo "== clean install check passed for $HEAD"
