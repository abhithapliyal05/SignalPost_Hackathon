# Identity resolution

The organisation number is the only identity key. Names, domains and handles are candidates until
they are tied back to that number.

## Websites

1. **Registry-listed homepage.** Fetched and judged by the starter kit's gate (organisation number
   or full legal-name tokens in homepage identity text). Unchanged from the kit.
1b. **Registry-declared homepage** (`registry_declared_unique_domain_v1`,
   `src/norway_company_agent/registry_site.py`). When the kit's name test fails on a fetched,
   registry-listed homepage, the site is still published if the company declared it to the
   register and all of these hold on the snapshot already fetched (no extra requests): no other
   entity in the bulk lists the same registrable domain; the company is not a group member; the
   page stays on the declared domain (or forwards to a domain no entity declares that also
   carries the name); the page is not parked, expired, for-sale or an empty server page and has
   at least 150 characters of captured text; no organisation number other than the company's or
   its subunits' appears; and a distinctive legal-name token (generic words such as invest,
   holding, eiendom, norge, group, consulting, trading excluded), or the whole compacted name,
   is in the domain label. The kit's original verdict is kept as `kit_identity_assessment` and
   every check as `registry_declared_check`.
2. **Free candidates**, tried only when (1) is missing or not publishable, at most three per company:
   the registry homepage the kit could not confirm, the registry e-mail domain (not a free-mail
   provider and used by at most five registered entities), homepages of the company's registered
   subunits, and the employer homepage on the company's own NAV ads. Directories, platforms,
   website builders and `kommune.no` hosts are never candidates.
3. **Proof.** A candidate is published only when a page fetched from it (homepage, then one
   contact/about page) shows one of:
   - **orgnr proof**: the company's exact organisation number (`123456789`, `123 456 789`,
     `NO 123 456 789 MVA`) and no other valid (mod-11) organisation number, except the company's
     own subunits;
   - **contact proof** (`.no` domains only): the full legal name plus a registry phone number or
     street+postcode that belongs to exactly one entity in the frozen registry snapshot.
4. **Rejected**: parked, for-sale or placeholder pages; pages naming another organisation number;
   redirects to a directory or platform; robots.txt disallow. The candidate, verdict and reason
   are kept in the `website_discovery` evidence record. Proof records the page URL, retrieval
   time, content hash, character span in the visible text and a snippet.

## Job ads

A NAV ad is attached only when its employer organisation number equals the company's or one of
its registered subunits'. New ads seen during the run are fetched only when their business name
exactly matches the company or a subunit name, and published only when the detail's employer
organisation number confirms it.

Contact proof is further restricted: it is not accepted for members of a corporate group
(registry `erIKonsern` or a group-structure record), where a shared group or brand site is
likely, and the domain label must contain the first distinctive token of the legal name.
Without both, only orgnr proof can publish a site. (Added after a 1,000-company audit found a
group site and a kindergarten-chain site passing on contact proof alone.)

## Shared and group sites, social links, job ads (added after Builderr's audit, 2026-10-23)

- **Shared or group site** (`site_scope.py`, `shared_or_group_site_guard_v1`). After any rule has
  published a website, it is withheld, with its social links, when two or more registry entities
  declare the same registrable domain, or when the page is a country section (`/no-no/`, `/nb/`) of
  a non-`.no` domain. The record keeps `withheld_by` and `site_scope_check` for audit.
- **Social links.** On top of the kit's handle test, a link is published only when its handle
  carries the whole legal name (five or more characters, or an exact match), a distinctive token of
  five or more characters, or two name tokens one of which has four or more. Dropped links are kept
  in `social_links_dropped_weak_handle`.
- **News.** None is published. The only dated activity is the official register timeline, whose
  dates are the register's own event dates, never a feed's "updated" time.
- **Job ads.** One record per NAV ad, matched by the employer organisation number of the company or
  one of its registered subunits. Each carries `ad_url`, the ad's own NAV page; an
  employer link is kept only when it is that same ad page, so careers pages and search links are
  never published.
- **Request budget.** Builderr counts every outbound request (registry included, retries and
  redirects included) against 2,000 per 100 companies. The gate enforces a total cap of 19 per
  company by default (`SIGNALPOST_TOTAL_REQUEST_CAP`).

## Additions in version 3 (2026-10-23)

- **Name-based domain candidates.** After the free candidates, discovery tries `<name>.no` and
  `<na-me>.no` built from the legal name (label of five or more characters), only when the domain
  resolves in DNS and no registry entity declares it as its homepage. A guessed domain is a
  candidate like any other: it publishes nothing without orgnr proof or legal-name-plus-unique-
  contact proof on the fetched page. On the 1,000-company sample 26 sites were added this way, all
  hand-checked (24 orgnr proof, 2 name plus unique phone or address).
- **Foreign parent sites.** The registry-declared rule also rejects a company whose name carries a
  national suffix (Norway, Norge, Nordic, Scandinavia) declaring a non-`.no` domain: that is the
  foreign parent's international site.
- **Social links.** JSON-LD `sameAs` profiles on the verified site are collected too. A handle that
  spells the verified domain (facebook.com/nordanger.no for nordanger.no) is kept for sites proven
  on the page, never for registry-declared sites or group members.
- **Company posts.** Dated items from the verified site's own RSS/Atom feed (declared on the
  homepage, same registered domain). Each date is the item's own `pubDate`/`published`, never an
  "updated" or `lastBuildDate` time; undated, off-domain, future-dated and placeholder items
  ("Hello world!", "Protected: …", template headlines) are dropped. Withheld or unverified sites
  get no posts.
