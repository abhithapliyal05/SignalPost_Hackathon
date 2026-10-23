from datetime import date

from norway_company_agent.summary import build_summary


def _rec(value, url):
    return {"status": "available", "value": value, "source_url": url}


def test_summary_cites_sources_and_lists_unknowns():
    profile = {
        "organisation_number": "925800023", "name": "SAMEIET X", "legal_form": "ESEK", "municipality": "LILLESTRØM",
        "evidence": {
            "registry_live": _rec({"industry": {"beskrivelse": "Boligsameier"}, "registry_dates": {"stiftelsesdato": "2020-09-17"}}, "https://data.brreg.no/e"),
            "financials": _rec({"records": [
                {"period": {"tilDato": "2024-12-31"}, "revenue": 1000000.0},
                {"period": {"tilDato": "2025-12-31"}, "revenue": 1100000.0, "annual_result": -5000.0},
            ]}, "https://data.brreg.no/r"),
            "jobs": {"status": "not_found", "value": {"active_ads": []}},
            "official_timeline": _rec({"events": [{"date": "2026-08-01", "precision": "day", "event": "Role group last changed: Styre"}]}, "https://data.brreg.no/e"),
        },
    }
    record = build_summary(profile, today=date(2026, 10, 23))
    value = record["value"]
    assert value["text"].startswith("SAMEIET X (org. no. 925800023) is an owner-section condominium")
    assert "Revenue rose 10%" in value["text"] and "-NOK 5 thousand" in value["text"]
    assert "2026-08-01: Role group last changed" in value["text"]
    assert all(sentence["sources"] for sentence in value["sentences"])
    assert {item["field"] for item in value["unknowns"]} >= {"official_website", "hiring"}
