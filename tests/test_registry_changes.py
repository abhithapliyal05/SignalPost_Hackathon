from datetime import date

from norway_company_agent.registry_changes import normalize_updates
from norway_company_agent.summary import build_summary
from norway_company_agent.timeline import build_official_timeline

FEED = {
    "_embedded": {"oppdaterteEnheter": [
        {"oppdateringsid": 3, "dato": "2026-10-14T05:00:00Z", "endringstype": "Endring", "endringer": [
            {"op": "replace", "path": "/forretningsadresse/adresse/0", "value": "Storgata 1"},
            {"op": "replace", "path": "/forretningsadresse/poststed", "value": "BODØ"},
            {"op": "replace", "path": "/telefon", "value": "99999999"},
        ]},
        {"oppdateringsid": 1, "dato": "2025-09-13T05:00:00Z", "endringstype": "Endring", "endringer": [
            {"op": "replace", "path": "/registreringsdatoAntallAnsatteEnhetsregisteret", "value": "2025-09-13"},
            {"op": "replace", "path": "/antallAnsatte", "value": 421},
        ]},
        {"oppdateringsid": 2, "dato": "2026-06-10T05:00:00Z", "endringstype": "Endring", "endringer": [
            {"op": "replace", "path": "/sisteInnsendteAarsregnskap", "value": "2025"},
            {"op": "replace", "path": "/antallAnsatte", "value": 391},
            {"op": "replace", "path": "/kapital/belop", "value": 150000.0},
            {"op": "replace", "path": "/kapital/antallAksjer", "value": 150.0},
        ]},
        {"oppdateringsid": 4, "dato": "2026-10-15T05:00:00Z", "endringstype": "Ukjent", "endringer": []},
    ]},
    "page": {"totalPages": 1},
}


def test_update_feed_becomes_events_without_private_values():
    value = normalize_updates(FEED)
    texts = [item["event"] for item in value["events"]]
    assert texts == ["Annual accounts for 2025 submitted", "Share capital changed to NOK 150 000", "Business address changed (to BODØ)", "Contact details changed"]
    assert value["employee_series"] == [{"date": "2025-09-13", "employees": 421}, {"date": "2026-06-10", "employees": 391}]
    assert "Storgata" not in str(value["events"]) and "99999999" not in str(value["events"])


def test_timeline_and_summary_use_update_feed():
    changes = {"status": "available", "value": normalize_updates(FEED), "source_url": "https://data.brreg.no/enhetsregisteret/api/oppdateringer/enheter?organisasjonsnummer=1", "retrieved_at": "2026-10-23T00:00:00Z", "content_sha256": "x"}
    profile = {"organisation_number": "1", "name": "X AS", "legal_form": "AS", "evidence": {"registry_changes": changes}}
    profile["evidence"]["official_timeline"] = build_official_timeline(profile)
    events = profile["evidence"]["official_timeline"]["value"]["events"]
    assert events[0]["event"] == "Contact details changed" and events[0]["source_url"] == changes["source_url"]
    text = build_summary(profile, today=date(2026, 10, 23))["value"]["text"]
    assert "employee count fell from 421 (2025-09-13) to 391 (2026-06-10)" in text
    # Substantive changes are listed before the routine filing.
    assert text.index("Business address changed") < text.index("Annual accounts for 2025 submitted")
