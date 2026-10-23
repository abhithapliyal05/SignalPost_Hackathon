# Version 3: more results without search keys (2026-10-23)

Same 1,000-company sample as the earlier reports. Everything here is keyless and stays inside
Builderr's request budget (every request counts, 2,000 per 100 companies).

| Family | Audit fixes (v2) | Version 3 |
|---|---:|---:|
| official_website | 48 | 73 |
| social_profiles (companies / links) | 20 / 33 | 32 / 61 |
| company_posts (companies / dated posts) | 0 | 15 / 117 |
| hiring (companies / ads) | 6 / 15 | 6 / 15 |
| dated_activity (events) | 1000 (21,152) | 1000 (22,918) |
| lei_and_parents | 0 | 134 |
| licences_permits | 0 | 46 |
| food_inspections | 0 | 19 |
| summary with cited sources | 0 | 1000 |

What was added:

1. **Name-based website candidates.** Domains spelled from the legal name, kept only if they
   resolve and no other entity declares them, then the same strict proof as before (orgnr, or
   legal name plus a unique phone or address on the site).
2. **Company posts.** Dated items from the verified site's own RSS/Atom feed; publish dates only,
   placeholder posts ("Hello world!", "Protected: …") dropped.
3. **Register changes.** Brønnøysund's update feed, one request per company: address, name,
   industry, purpose, capital, VAT, liquidation and group changes, plus an employee-count trend
   (310 companies had a change besides filing; 109 an employee-count change).
4. **Declared public-register cache** (no run-time requests): GLEIF LEI and parents,
   Finanstilsynet licences, Statens vegvesen workshops, Arbeidstilsynet cleaning register, Udir
   kindergartens and schools, Fiskeridirektoratet aquaculture, Mattilsynet food inspections.
5. **Summary** for every company, each sentence citing its sources, plus what is unknown.
6. **viewer.html** written by every run: search, filter, compare two companies, open every source;
   checked at 1280 px and 390 px with no horizontal scroll.
7. **Stricter filters** after hand-checks: foreign parent-brand sites (Brady), domain-named social
   handles of group members, placeholder feed posts.

Run: 21 min 15 s, 9,127 requests (7,002 registry, 2,125 web) of the 19,000 cap, 1000/1000
envelopes, validation passed. Versus the previous run, two sites were lost to timeouts
(veriscan.no, centevo.se) and Brady's parent-brand site was rejected on purpose. 140 tests pass.
