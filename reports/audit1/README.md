# Fixes after Builderr's audit of version 1 (2026-10-23)

Same 1,000-company sample as earlier reports. Audit points and what we did:

1. **Website is the company's own, not a parent group's.** New `site_scope.py` guard withholds a
   site (and its social links) when two or more registry entities declare the same domain or the
   page is a country section of a non-.no domain. Withheld on this sample: Bestseller AS
   (bestseller.com, 7 entities), Backe Trondheim AS (backe.no, 14), Alna Venstre (venstre.no, 123),
   Steinly Hydraulikk AS (steinly.no, 3), Rittal AS (rittal.com/no-no/).
2. **Social links belong to the company.** Handle test tightened (short tokens inside long handles
   no longer count). ROM AS's two links were dropped. Links of withheld sites are not published.
3. **News.** None published; dated activity is only the register's own event dates.
4. **Jobs.** Every ad is a single NAV ad matched by employer orgnr (company or its subunit); each
   carries its own `ad_url`, and an employer link is kept only if it is that ad.
5. **Requests.** Registry, retries and redirects all count, so the gate now enforces a total cap
   of 19 per company (Builderr: 2,000 per 100). This run used 7,104 of 19,000.

| Family | Before | After |
|---|---:|---:|
| official_website | 54 | 48 |
| social_profiles (companies / links) | 24 / 42 | 20 / 33 |
| hiring (companies / ads) | 3 / 12 | 6 / 15 (live NAV feed moved since the cache was built) |
| accounts_history / dated_activity | 1000 / 1000 | 1000 / 1000 |

14 min 20 s, 1000/1000 envelopes, validation passed, no cap hit. 132 tests pass.
