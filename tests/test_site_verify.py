from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from norway_company_agent.identity_index import address_key, normalize_phone  # noqa: E402
from norway_company_agent.jobs import normalize_name  # noqa: E402
from norway_company_agent.site_verify import assess_page, orgnr_mentions, valid_orgnr  # noqa: E402

ORG = "923609016"  # Equinor ASA, a valid orgnr
OTHER = "984851006"  # DNB Bank ASA


def page(text: str) -> dict:
    return {"text": text}


def test_mod11_and_formats() -> None:
    assert valid_orgnr(ORG) and valid_orgnr(OTHER)
    assert not valid_orgnr("923609017")
    found = [item["orgnr"] for item in orgnr_mentions(f"Org.nr: NO 923 609 016 MVA. Tlf 22 33 44 55. {OTHER}")]
    assert found == [ORG, OTHER]
    assert orgnr_mentions("Konto 1234.56.78901 og tlf 12345678") == []


def test_orgnr_proof_requires_no_foreign_orgnr() -> None:
    proof = assess_page(page(f"Eksempel AS · Org.nr. {ORG}"), ORG, {ORG}, "Eksempel AS", set(), [], "eksempel.no")
    assert proof["verdict"] == "proof" and proof["proof_type"] == "orgnr"
    rejected = assess_page(page(f"Kunder: {ORG} og {OTHER}"), ORG, {ORG}, "Eksempel AS", set(), [], "eksempel.no")
    assert rejected["verdict"] == "reject"
    subunit_ok = assess_page(page(f"{ORG} avdeling {OTHER}"), ORG, {ORG, OTHER}, "Eksempel AS", set(), [], "eksempel.no")
    assert subunit_ok["verdict"] == "proof"


def test_contact_proof_needs_name_unique_contact_and_no_domain() -> None:
    text = "Velkommen til Fjord Rør AS. Ring oss på 22 33 44 55."
    proof = assess_page(page(text), ORG, {ORG}, "FJORD RØR AS", {"22334455"}, [], "fjordror.no")
    assert proof["verdict"] == "proof" and proof["proof_type"] == "legal_name_and_unique_phone"
    assert assess_page(page(text), ORG, {ORG}, "FJORD RØR AS", set(), [], "fjordror.no")["verdict"] == "no_proof"
    assert assess_page(page(text), ORG, {ORG}, "FJORD RØR AS", {"22334455"}, [], "fjordror.com")["verdict"] == "no_proof"
    address = assess_page(page("Fjord Rør AS, Storgata 5, 0155 Oslo"), ORG, {ORG}, "FJORD RØR AS", set(), [("storgata 5", "0155")], "fjordror.no")
    assert address["proof_type"] == "legal_name_and_unique_address"


def test_parked_page_rejected() -> None:
    assert assess_page(page(f"This domain is for sale {ORG}"), ORG, {ORG}, "X AS", set(), [], "x.no")["verdict"] == "reject"


def test_normalizers() -> None:
    assert normalize_phone("+47 22 33 44 55") == "22334455"
    assert normalize_name("Fjord Rør AS") == "fjord ror"
    assert address_key("Storgata 5", "0155") == "storgata 5|0155"
    assert address_key("Storgata", "0155") is None
