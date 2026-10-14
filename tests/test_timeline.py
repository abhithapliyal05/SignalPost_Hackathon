from norway_company_agent.official import normalize_entity
from norway_company_agent.timeline import build_official_timeline


def _record(value, url):
    return {"status": "available", "value": value, "source_url": url, "retrieved_at": "2026-10-14T10:00:00Z", "content_sha256": "abc"}


def test_timeline_collects_dated_official_events_newest_first():
    live = normalize_entity({"organisasjonsnummer": "884647762", "stiftelsesdato": "2002-05-21", "vedtektsdato": "2020-04-28", "konkurs": False, "navn": "PRETRE AS"})
    profile = {
        "organisation_number": "884647762",
        "evidence": {
            "registry_live": _record(live, "https://data.brreg.no/enhetsregisteret/api/enheter/884647762"),
            "roles": _record({"roles": [
                {"group": "Styre", "last_changed": "2024-03-01"},
                {"group": "Styre", "last_changed": "2024-03-01"},
            ]}, "https://data.brreg.no/enhetsregisteret/api/enheter/884647762/roller"),
            "financials": _record({"records": [{"period": {"fraDato": "2024-01-01", "tilDato": "2024-12-31"}}]}, "https://data.brreg.no/regnskapsregisteret/regnskap/884647762"),
            "financial_history": _record({"years": ["2023", "2024"]}, "https://data.brreg.no/regnskapsregisteret/regnskap/aarsregnskap/kopi/884647762/aar"),
        },
    }
    record = build_official_timeline(profile)
    assert record["status"] == "available"
    events = record["value"]["events"]
    assert [event["date"] for event in events] == ["2024-12-31", "2024-03-01", "2024", "2023", "2020-04-28", "2002-05-21"]
    assert all(event["source_url"] and event["content_sha256"] for event in events)
    assert events[-1]["event"] == "Company founded"


def test_timeline_not_found_without_records():
    assert build_official_timeline({"organisation_number": "1", "evidence": {}})["status"] == "not_found"
