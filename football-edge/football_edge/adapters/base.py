"""Adapter contract. An adapter turns provider payloads into canonical
objects and nothing else. It never touches the store or the UI."""
from dataclasses import dataclass, field
from typing import List, Dict
from ..schema import Game, LineObservation, SplitObservation


@dataclass
class AdapterResult:
    games: List[Game] = field(default_factory=list)
    lines: Dict[str, List[LineObservation]] = field(default_factory=dict)
    splits: Dict[str, List[SplitObservation]] = field(default_factory=dict)
    results: Dict[str, dict] = field(default_factory=dict)
    errors: List[str] = field(default_factory=list)


class Adapter:
    name = "base"
    provides = ()

    def fetch(self, league: str, **kwargs) -> AdapterResult:
        raise NotImplementedError

    def parse(self, league: str, payload, **kwargs) -> AdapterResult:
        raise NotImplementedError
