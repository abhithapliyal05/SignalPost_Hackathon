"""Shared outbound-request gate and wall-clock guard.

Every outbound HTTP request in the agent asks this gate first. The gate:

- counts registry (Brønnøysund) requests and all other ("web") requests separately;
- refuses web requests once the web cap is spent, and every request once the optional
  registry cap is spent;
- refuses every request once the wall-clock deadline has passed;
- spaces requests to the same non-registry host at least ``host_interval`` seconds apart;
- keeps per-company counts so the run log can say which company spent what.

A refusal raises nothing by itself: ``acquire`` returns the refusal reason and the caller turns it
into a ``blocked`` evidence record whose note starts with ``budget_exhausted``.
"""

from __future__ import annotations

import os
import threading
import time
import urllib.parse
from collections import defaultdict
from typing import Any, Callable

REGISTRY_HOSTS = frozenset({"data.brreg.no"})
BUDGET_PREFIX = "budget_exhausted"
REQUEST_TIMEOUT_S = 10.0  # urllib applies one socket timeout to connect and each read
MAX_ATTEMPTS = 2  # one retry at most


class BudgetExhausted(Exception):
    """Raised by gated openers when the gate refuses a request."""


def _env_int(name: str, default: int | None) -> int | None:
    value = os.environ.get(name, "").strip()
    return int(value) if value else default


class RequestGate:
    def __init__(
        self,
        *,
        web_cap: int | None = 1900,
        registry_cap: int | None = None,
        total_cap: int | None = None,
        deadline_s: float | None = None,
        host_interval: float = 1.0,
        clock: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        self._lock = threading.Lock()
        self._local = threading.local()
        self._clock = clock
        self._sleeper = sleeper
        self.configure(web_cap=web_cap, registry_cap=registry_cap, total_cap=total_cap, deadline_s=deadline_s, host_interval=host_interval)

    def configure(
        self,
        *,
        web_cap: int | None = 1900,
        registry_cap: int | None = None,
        total_cap: int | None = None,
        deadline_s: float | None = None,
        host_interval: float = 1.0,
        started_at: float | None = None,
    ) -> None:
        with self._lock:
            self.web_cap = web_cap
            self.registry_cap = registry_cap
            self.total_cap = total_cap
            self.host_interval = host_interval
            self.started_at = self._clock() if started_at is None else started_at
            self.deadline_at = None if deadline_s is None else self.started_at + deadline_s
            self.deadline_s = deadline_s
            self.registry_requests = 0
            self.web_requests = 0
            self.refused: dict[str, int] = defaultdict(int)
            self.deadline_hit = False
            self.cap_hit = False
            self._host_next: dict[str, float] = {}
            self._per_company: dict[str, dict[str, int]] = defaultdict(lambda: {"registry_requests": 0, "web_requests": 0, "refused": 0})

    # -- per-company attribution -------------------------------------------------------------
    def begin_company(self, org: str | None) -> None:
        self._local.org = org

    def company_counts(self, org: str) -> dict[str, int]:
        with self._lock:
            return dict(self._per_company.get(org) or {"registry_requests": 0, "web_requests": 0, "refused": 0})

    # -- deadline ---------------------------------------------------------------------------
    def remaining_s(self) -> float | None:
        if self.deadline_at is None:
            return None
        return self.deadline_at - self._clock()

    def past_deadline(self) -> bool:
        remaining = self.remaining_s()
        return remaining is not None and remaining <= 0

    # -- the gate ---------------------------------------------------------------------------
    def acquire(self, url: str) -> str | None:
        """Reserve one request to ``url``. Return ``None`` if allowed, else the refusal reason."""
        host = (urllib.parse.urlparse(url).hostname or "").lower()
        registry = host in REGISTRY_HOSTS
        org = getattr(self._local, "org", None)
        wait = 0.0
        with self._lock:
            reason = None
            if self.past_deadline():
                self.deadline_hit = True
                reason = f"{BUDGET_PREFIX}: wall-clock deadline reached"
            elif self.total_cap is not None and self.registry_requests + self.web_requests >= self.total_cap:
                self.cap_hit = True
                reason = f"{BUDGET_PREFIX}: total request cap {self.total_cap} spent"
            elif registry and self.registry_cap is not None and self.registry_requests >= self.registry_cap:
                self.cap_hit = True
                reason = f"{BUDGET_PREFIX}: registry request cap {self.registry_cap} spent"
            elif not registry and self.web_cap is not None and self.web_requests >= self.web_cap:
                self.cap_hit = True
                reason = f"{BUDGET_PREFIX}: web request cap {self.web_cap} spent"
            if reason:
                self.refused[reason.split(": ", 1)[1]] += 1
                if org:
                    self._per_company[org]["refused"] += 1
                return reason
            now = self._clock()
            if not registry and self.host_interval > 0 and host:
                slot = max(now, self._host_next.get(host, now))
                self._host_next[host] = slot + self.host_interval
                wait = slot - now
                if self.deadline_at is not None and slot >= self.deadline_at:
                    self.deadline_hit = True
                    self.refused["wall-clock deadline reached"] += 1
                    if org:
                        self._per_company[org]["refused"] += 1
                    return f"{BUDGET_PREFIX}: wall-clock deadline reached"
            if registry:
                self.registry_requests += 1
            else:
                self.web_requests += 1
            if org:
                self._per_company[org]["registry_requests" if registry else "web_requests"] += 1
        if wait > 0:
            self._sleeper(wait)
        return None

    def summary(self) -> dict[str, Any]:
        with self._lock:
            return {
                "registry_requests": self.registry_requests,
                "web_requests": self.web_requests,
                "total_requests": self.registry_requests + self.web_requests,
                "web_cap": self.web_cap,
                "registry_cap": self.registry_cap,
                "total_cap": self.total_cap,
                "refused": dict(self.refused),
                "cap_hit": self.cap_hit,
                "deadline_s": self.deadline_s,
                "deadline_hit": self.deadline_hit,
                "host_interval_s": self.host_interval,
                "request_timeout_s": REQUEST_TIMEOUT_S,
                "max_attempts": MAX_ATTEMPTS,
            }


def is_budget_note(note: Any) -> bool:
    return str(note or "").startswith(BUDGET_PREFIX)


GATE = RequestGate(
    web_cap=_env_int("SIGNALPOST_WEB_REQUEST_CAP", 1900),
    registry_cap=_env_int("SIGNALPOST_REGISTRY_REQUEST_CAP", None),
    total_cap=_env_int("SIGNALPOST_TOTAL_REQUEST_CAP", None),
)
