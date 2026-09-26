"""Betting-splits provider interface. There is no free, legitimate API
for ticket and handle percentages today. This module defines the
contract a real provider (Sportradar, Action Network, a book's own
feed) must satisfy, plus a Null provider that reports UNAVAILABLE.
Nothing here ever estimates or fabricates a percentage."""
from .base import Adapter, AdapterResult


class SplitsProvider(Adapter):
    """Contract: fetch() returns AdapterResult.splits keyed by canonical
    game id or a MATCH|kickoff|away|home ref, each SplitObservation with
    provider, book, ts, and whichever of the six percentages the source
    actually publishes. Unpublished fields stay None (UNKNOWN)."""
    name = "splits_base"
    provides = ("splits",)
    available = False
    display_name = "none"

    def status(self):
        return {"available": self.available, "provider": self.display_name}


class NullSplitsProvider(SplitsProvider):
    name = "splits_none"
    display_name = "No splits provider connected"

    def fetch(self, league: str, **kw) -> AdapterResult:
        r = AdapterResult()
        r.errors.append("splits UNAVAILABLE: no splits provider connected (overrides only)")
        return r
