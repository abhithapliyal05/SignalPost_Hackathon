"""Registry-wide counts used to decide whether a contact detail identifies exactly one entity.

Built once per run from the same frozen Brreg bulk snapshot the run anchors identity on. For each
normalized phone number, street+postcode and e-mail domain it counts how many registered entities
carry it. A contact detail is identifying only when its count is 1.
"""

from __future__ import annotations

import csv
import gzip
import re
from collections import Counter
from pathlib import Path
from typing import Any

from .jobs import normalize_name


def normalize_phone(value: Any) -> str | None:
    digits = re.sub(r"\D", "", str(value or ""))
    if digits.startswith("0047"):
        digits = digits[4:]
    elif digits.startswith("47") and len(digits) == 10:
        digits = digits[2:]
    return digits if len(digits) == 8 else None


def normalize_street(value: Any) -> str:
    return normalize_name(value)


def address_key(street: Any, postcode: Any) -> str | None:
    street_key = normalize_street(street)
    postcode = re.sub(r"\D", "", str(postcode or ""))
    if not street_key or len(postcode) != 4 or not re.search(r"\d", street_key):
        return None  # a street without a house number does not identify a building
    return f"{street_key}|{postcode}"


def email_domain(value: Any) -> str | None:
    text = str(value or "").strip().casefold()
    if "@" not in text:
        return None
    domain = text.rsplit("@", 1)[1].strip(". ")
    return domain or None


def entity_contacts(row: dict[str, Any]) -> dict[str, Any]:
    phones = sorted({phone for phone in (normalize_phone(row.get("telefon")), normalize_phone(row.get("mobil"))) if phone})
    addresses = sorted({
        key for key in (
            address_key(row.get("forretningsadresse.adresse"), row.get("forretningsadresse.postnummer")),
            address_key(row.get("postadresse.adresse"), row.get("postadresse.postnummer")),
        ) if key
    })
    return {"phones": phones, "addresses": addresses, "email_domain": email_domain(row.get("epostadresse"))}


class IdentityIndex:
    def __init__(self) -> None:
        self.phones: Counter[str] = Counter()
        self.addresses: Counter[str] = Counter()
        self.email_domains: Counter[str] = Counter()
        self.names: Counter[str] = Counter()
        self.rows = 0

    @classmethod
    def from_bulk(cls, path: str | Path) -> "IdentityIndex":
        index = cls()
        with gzip.open(path, "rt", encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                index.rows += 1
                contacts = entity_contacts(row)
                index.phones.update(contacts["phones"])
                index.addresses.update(contacts["addresses"])
                if contacts["email_domain"]:
                    index.email_domains[contacts["email_domain"]] += 1
                index.names[normalize_name(row.get("navn"))] += 1
        return index

    def summary(self) -> dict[str, int]:
        return {
            "entities": self.rows,
            "distinct_phones": len(self.phones),
            "distinct_addresses": len(self.addresses),
            "distinct_email_domains": len(self.email_domains),
        }
