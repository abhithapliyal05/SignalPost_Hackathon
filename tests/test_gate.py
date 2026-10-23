from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from norway_company_agent.batch import evidence_terminal_state  # noqa: E402
from norway_company_agent.gate import RequestGate, is_budget_note  # noqa: E402
from norway_company_agent.http import FetchResult  # noqa: E402
from norway_company_agent.official import fetch_official_modules  # noqa: E402


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0
        self.slept: list[float] = []

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds


def make_gate(**kwargs) -> tuple[RequestGate, FakeClock]:
    clock = FakeClock()
    gate = RequestGate(clock=clock, sleeper=clock.sleep, **kwargs)
    return gate, clock


def test_web_cap_refuses_after_spend_and_registry_counts_separately() -> None:
    gate, _ = make_gate(web_cap=2, host_interval=0)
    assert gate.acquire("https://a.no/") is None
    assert gate.acquire("https://b.no/") is None
    refusal = gate.acquire("https://c.no/")
    assert refusal and is_budget_note(refusal) and "web request cap 2" in refusal
    assert gate.acquire("https://data.brreg.no/enhetsregisteret/api/enheter/123456789") is None
    summary = gate.summary()
    assert (summary["web_requests"], summary["registry_requests"], summary["cap_hit"]) == (2, 1, True)


def test_registry_cap_is_optional() -> None:
    gate, _ = make_gate(web_cap=None, registry_cap=1)
    assert gate.acquire("https://data.brreg.no/x") is None
    assert "registry request cap" in (gate.acquire("https://data.brreg.no/y") or "")


def test_deadline_refuses_everything() -> None:
    gate, clock = make_gate(web_cap=None, deadline_s=10)
    assert gate.acquire("https://data.brreg.no/x") is None
    clock.now += 11
    assert "wall-clock deadline" in (gate.acquire("https://data.brreg.no/x") or "")
    assert "wall-clock deadline" in (gate.acquire("https://a.no/") or "")
    assert gate.summary()["deadline_hit"] is True


def test_same_host_requests_are_spaced() -> None:
    gate, clock = make_gate(web_cap=None, host_interval=1.0)
    gate.acquire("https://a.no/")
    gate.acquire("https://a.no/robots.txt")
    gate.acquire("https://b.no/")
    assert clock.slept == [1.0]


def test_per_company_attribution() -> None:
    gate, _ = make_gate(web_cap=1, host_interval=0)
    gate.begin_company("123456789")
    gate.acquire("https://data.brreg.no/x")
    gate.acquire("https://a.no/")
    gate.acquire("https://b.no/")
    assert gate.company_counts("123456789") == {"registry_requests": 1, "web_requests": 1, "refused": 1}


def test_refused_registry_call_becomes_budget_exhausted_state() -> None:
    def refused(url: str) -> FetchResult:
        return FetchResult(url, 0, 0, 0, error="budget_exhausted: wall-clock deadline reached")

    records, _ = fetch_official_modules("123456789", {"roles"}, fetcher=refused)
    assert records["roles"]["status"] == "blocked"
    assert evidence_terminal_state(records["roles"]) == "budget_exhausted"


def test_total_cap_counts_registry_and_web_requests_together():
    gate, _ = make_gate(web_cap=None, total_cap=3, host_interval=0)
    assert gate.acquire("https://data.brreg.no/a") is None
    assert gate.acquire("https://example.no/") is None
    assert gate.acquire("https://data.brreg.no/b") is None
    reason = gate.acquire("https://example.no/2")
    assert reason and is_budget_note(reason) and "total request cap 3" in reason
    assert gate.summary()["total_cap"] == 3
