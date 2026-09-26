"""Canonical schema. Nothing provider-specific lives here.

Conventions (identical for CFB and NFL):
- spread_home: the HOME team's number. Negative = home favored.
- ml_away / ml_home: American odds.
- *_away percentages are for the AWAY side; home is the remainder.
- over_* percentages are for the OVER.
- Every observation carries provider, book, ts (UTC ISO) and origin
  ('auto' from an adapter, 'override' from an admin override file).
"""
from dataclasses import dataclass, field, asdict
from typing import Optional, Dict, Any
import re


def slug(s: str) -> str:
    s = s.lower().replace("&", "and")
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s


def game_id(league: str, season: int, kickoff_utc: str, away: str, home: str) -> str:
    """Stable id independent of provider: league-season-date-away-home."""
    d = kickoff_utc[:10].replace("-", "")
    return f"{league}-{season}-{d}-{slug(away)}-{slug(home)}"


@dataclass
class Team:
    name: str
    abbrev: str = ""
    rank: Optional[int] = None
    record: str = ""
    conference: str = ""
    external_ids: Dict[str, str] = field(default_factory=dict)


@dataclass
class LineObservation:
    ts: str
    provider: str
    book: str
    origin: str = "auto"
    spread_home: Optional[float] = None
    spread_juice_home: Optional[int] = None
    spread_juice_away: Optional[int] = None
    ml_away: Optional[int] = None
    ml_home: Optional[int] = None
    total: Optional[float] = None
    over_juice: Optional[int] = None
    under_juice: Optional[int] = None
    is_open: bool = False
    is_close: bool = False
    note: str = ""


@dataclass
class SplitObservation:
    ts: str
    provider: str
    book: str
    origin: str = "auto"
    spread_tix_away: Optional[float] = None
    spread_hdl_away: Optional[float] = None
    ml_tix_away: Optional[float] = None
    ml_hdl_away: Optional[float] = None
    over_tix: Optional[float] = None
    over_hdl: Optional[float] = None
    source: str = ""
    note: str = ""


@dataclass
class Game:
    id: str
    league: str
    season: int
    week: Optional[int]
    kickoff_utc: str
    away: Team
    home: Team
    neutral: bool = False
    venue: str = ""
    status: str = "scheduled"
    period: Optional[int] = None
    clock: str = ""
    score_away: Optional[int] = None
    score_home: Optional[int] = None
    final_ts: Optional[str] = None
    external_ids: Dict[str, str] = field(default_factory=dict)
    weather: Dict[str, Any] = field(default_factory=dict)
    updated_at: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
