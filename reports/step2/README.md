# Step 2: identity and free sources (2026-10-14)

## What was added

- **NAV job ads** (`jobs.py`, `make cache`): declared cache of 9,715 ads active on 2026-10-14
  (99% carry an employer orgnr). The run reads the feed forward from the cache's last page,
  drops closed ads and matches ads by the company's orgnr or a subunit orgnr.
- **Registry contact index** (`identity_index.py`): phone, street+postcode and e-mail domain
  counts over all 1.18 million entities in the bulk snapshot (about 40 s per run).
- **Strict free website discovery** (`site_verify.py`, rules in `IDENTITY_RESOLUTION.md`).
- **Batch robustness**: an input missing from the registry snapshot (6 of 1,000 in the scale
  test were deleted after the universe was frozen) now gets an envelope instead of crashing the
  kit's whole batch.

## Coverage

| Family | dev100 baseline | dev100 now | 1,000-company scale test |
|---|---:|---:|---:|
| official_website | 3 | 4 | 50 (34 registry-listed + 16 discovered) |
| social_profiles | 1 | 2 | 24 companies, 42 profiles |
| hiring | 0 | 1 | 3 companies, 12 ads |
| registered_workplaces | 75 | 75 | 743 |
| group_structure | 9 | 9 | 69 |
| dated_activity | 0 | 0 | 0 |

Across the whole universe only about 2,270 of 411,160 companies (5.5 per 1,000) currently have an
active NAV ad, so hiring stays sparse for any entrant using NAV.

## Scale test (1,000 companies, seed 20260823, before the group rule below)

12.5 min wall clock (38 min guard), 5,002 registry + 1,161 web requests (cap 1,900), 1,000/1,000
envelopes, validation passed, no requests refused. p50 / p95 request latency 721 / 1,005 ms.

## Audit and rule change

Of the 16 discovered sites (`scale1000-discovered-sites.json`), two passed on contact proof but
belonged to a group or chain: backe.no for BACKE TRONDHEIM AS (group site) and
samvirkebarnehagene.no for HAUGELØKKA BARNEHAGE AS (chain site). Contact proof is now refused for
group members and for domains that do not carry the legal name; both cases are now rejected.
Expected discovered sites at the same rate: about 14 per 1,000.

## Not done

- OSM `ref:NO:orgnr`: overpass-api.de, its mirrors and download.geofabrik.de all reset the
  connection from the build environment.
- Brønnøysund announcements (dated official activity) exist per orgnr at w2.brreg.no, but its
  robots.txt disallows `/kunngjoring/`, so they are not used.
