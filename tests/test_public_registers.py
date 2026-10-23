import gzip
import json

from norway_company_agent.public_registers import RegisterIndex
from norway_company_agent.summary import build_summary


def _entry(source, field, org, value, url):
    return {"source": source, "field": field, "unit_org": org, "value": value, "source_url": url, "dataset_url": "https://example.org/d", "retrieved_at": "2026-10-23T08:00:00Z", "content_sha256": "h", "licence": "NLOD 2.0"}


def test_lookup_matches_company_and_workplaces(tmp_path):
    rows = [
        {"org": "111111111", "entries": [
            _entry("gleif_lei", "lei", "111111111", {"lei": "LEI1", "registration_status": "ISSUED", "direct_parent": {"lei": "P", "name": "PARENT AB", "country": "SE"}, "ultimate_parent": {"lei": "P", "name": "PARENT AB", "country": "SE"}}, "https://api.gleif.org/api/v1/lei-records/LEI1"),
            _entry("finanstilsynet", "licences", "111111111", {"licence": "External accounting firm", "granted": "2007-12-10", "register": "Finanstilsynet"}, "https://www.finanstilsynet.no/virksomhetsregisteret/detalj/?id=1"),
        ]},
        {"org": "222222222", "entries": [_entry("mattilsynet_inspections", "food_inspections", "222222222", {"premises": "Kafe X", "town": "Oslo", "inspected": "2026-05-01", "result": "smile (no remarks)"}, "https://smilefjes.mattilsynet.no/api/tilsyn.csv#tilsynid=1")]},
    ]
    with gzip.open(tmp_path / "registers.jsonl.gz", "wt") as out:
        for row in rows:
            out.write(json.dumps(row, separators=(",", ":")) + "\n")
    (tmp_path / "registers_state.json").write_text('{"built_at": "2026-10-23T09:00:00Z"}')
    index = RegisterIndex(tmp_path)
    profile = {"organisation_number": "111111111", "name": "X AS", "legal_form": "AS", "evidence": {"locations": {"status": "available", "value": {"locations": [{"organisation_number": "222222222"}]}}}}
    records = index.lookup(profile)
    assert records["lei"]["status"] == "available" and records["lei"]["source_url"].endswith("LEI1")
    assert records["licences"]["value"]["count"] == 1
    assert records["food_inspections"]["value"]["items"][0]["unit_org"] == "222222222"
    assert index.lookup({"organisation_number": "333333333", "evidence": {}})["lei"]["status"] == "not_found"
    profile["evidence"].update(records)
    text = build_summary(profile)["value"]["text"]
    assert "parent PARENT AB (SE), also its ultimate parent" in text
    assert "External accounting firm since 2007-12-10" in text and "Kafe X (Oslo) on 2026-05-01 gave a smile (no remarks)" in text
