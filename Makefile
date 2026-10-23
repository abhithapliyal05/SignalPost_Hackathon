# One-command entry points. Requires Python 3.12+ and uv (https://docs.astral.sh/uv/).
INPUT ?= data/dev100.txt
OUT ?= out/run
BULK ?= cache/brreg-enheter.csv.gz
RUN_ID ?= local-$(shell date -u +%Y%m%dT%H%M%SZ)
UV ?= uv

.PHONY: install registry universe samples cache run coverage test replay clean-install-check

install:
	$(UV) sync --frozen

registry:
	mkdir -p cache
	curl -fsSL 'https://data.brreg.no/enhetsregisteret/api/enheter/lastned/csv' -o $(BULK)

universe:
	mkdir -p cache
	curl -fsSL 'https://builderr.ai/signalpost-company-universe-2025.jsonl.gz' -o cache/signalpost-universe.jsonl.gz

cache:
	$(UV) run python scripts/build_nav_cache.py

samples: universe
	$(UV) run python scripts/sample_dev_val.py

run:
	$(UV) run python scripts/run_competition_batch.py \
		--organisations $(INPUT) \
		--bulk $(BULK) \
		--profiles-output $(OUT)/profiles.jsonl \
		--output $(OUT)/envelopes.jsonl \
		--report $(OUT)/report.json \
		--run-id $(RUN_ID)
	$(UV) run python scripts/family_coverage.py --profiles $(OUT)/profiles.jsonl --output $(OUT)/family_coverage.json
	$(UV) run python scripts/build_viewer.py --profiles $(OUT)/profiles.jsonl --output $(OUT)/viewer.html

coverage:
	$(UV) run python scripts/family_coverage.py --profiles $(OUT)/profiles.jsonl --output $(OUT)/family_coverage.json

test:
	$(UV) run pytest -q

replay:
	$(UV) run python scripts/run_refresh_replay.py --manifest tests/fixtures/refresh-snapshots.json --output $(OUT)/refresh-demo.json

clean-install-check:
	bash scripts/clean_install_check.sh
