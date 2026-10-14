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
