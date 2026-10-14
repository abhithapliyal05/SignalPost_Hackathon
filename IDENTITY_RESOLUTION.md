# Identity resolution

The organisation number is the only identity key. Names, domains and handles are candidates until
they are tied back to that number.

## Websites

1. **Registry-listed homepage.** Fetched and judged by the starter kit's gate (organisation number
   or full legal-name tokens in homepage identity text). Unchanged from the kit.
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
