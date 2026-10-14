# Tuning round 1: accounts history, registry-declared websites, official timeline

Same 1,000-company sample as reports/step2 (seed 20260823), run on 2026-10-14.

| Family | Step 2 | Now |
|---|---:|---:|
| accounts_history (companies / facts) | 0 / 0 | 1,000 / 8,937 |
| dated_activity (companies / events) | 0 / 0 | 1,000 / 21,152 |
| official_website | 50 (48 after group rule) | 54 |
| social_profiles (companies / links) | 24 / 42 | 24 / 42 |
| hiring | 3 / 12 | 3 / 12 |

Website methods: kit name/orgnr gate 35, registry-declared rule 12, strict free-candidate proof 7.

Run: 13 min 56 s, 6,002 registry + 1,093 web requests (cap 1,900), no refusals, no HTTP 429,
1000/1000 envelopes, validation passed.

## Hand check of the 12 registry-declared sites

All 12 were declared by the company itself to the Brønnøysund register and passed every check
in IDENTITY_RESOLUTION.md (1b).

Clearly the company's own site: PRETRE AS (pretre.no), MARLO AS (marlo.no), RUNAR KVANT AS
(runarkvant.no forwards to kvant.no), GRAVITONIA AS (gravitonia.com), KYSTVINDUET & NORGESGJERDE AS
(kystvinduet.no), MODUM DYREKLINIKK AS (modumdyreklinikk.no), HMH CEMENT OSLO AS (hmhcement.no),
HAMMERSBORG BORETTSLAG (hammersborgborettslag.no), FORSKNINGSSTIFTELSEN NIFU (nifu.no),
MINTIE CORPORATION OF SCANDINAVIA AS (mintie.no).

Judgment calls, kept because the company declared them: BRADY ENERGY NORWAY AS
(bradytechnologies.com, the brand's international site) and CARLIN INVEST AS (carlin.no, the
owner's personal page). Neither is in a Norwegian group record, and neither page names another
organisation number.

Rejected by the rule and correctly so (examples): domains shared with other entities (obos.no,
usbl.no, 7-eleven.no), group members (sulland.no, peab.no), redirects to another brand
(studiox.no, insubiz.dk), an expired domain (betakst.no) and an "Index of /" page.
