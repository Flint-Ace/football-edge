"""Cross-provider team/game matching. Providers name teams differently
(CFBD: "Ole Miss"; The Odds API: "Ole Miss Rebels"). Games are matched
by kickoff (within 36h) plus both team names. Nothing here is guessed
silently: an unmatched event is reported, never auto-created for CFB."""
import re
import unicodedata
from datetime import datetime, timedelta
from typing import Optional, List

ALIASES = {  # normalized provider school name -> normalized canonical (CFBD) name
    "ul monroe": "louisiana monroe", "ulm": "louisiana monroe",
    "appalachian state": "app state", "fiu": "florida international",
    "southern miss": "southern mississippi", "pitt": "pittsburgh",
    "usf": "south florida", "uconn": "connecticut", "cal": "california",
    "sam houston state": "sam houston", "miami fl": "miami", "miami florida": "miami",
    "hawai i": "hawaii", "utsa": "ut san antonio", "ut san antonio": "utsa",
    "central florida": "ucf", "southern california": "usc", "brigham young": "byu",
    "louisiana lafayette": "louisiana", "nevada las vegas": "unlv",
    "texas christian": "tcu", "louisiana state": "lsu", "southern methodist": "smu",
    "massachusetts": "umass", "north carolina state": "nc state",
}


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()
    s = s.lower().replace("&", " and ").replace("'", "")
    s = re.sub(r"[^a-z0-9]+", " ", s).strip()
    s = re.sub(r"\bst\b", "state", s)
    return re.sub(r"\s+", " ", s)


def team_score(canonical: str, provider_name: str) -> int:
    """How well a provider team name (may include mascot) matches a canonical
    school name. 0 = no match; higher = longer match."""
    c, p = norm(canonical), norm(provider_name)
    if not c or not p:
        return 0
    if c == p:
        return len(c.split()) + 2
    for k, v in ALIASES.items():
        if p == k or p.startswith(k + " "):
            p = v + p[len(k):]
        if c == k:
            c = v
    if c == p:
        return len(c.split()) + 2
    if p.startswith(c + " "):
        rest = p[len(c) + 1:].split()
        if rest and rest[0] in ("state", "oh", "ohio", "fl", "tech", "southern", "am", "a") and not c.endswith(rest[0]):
            return 0
        return len(c.split()) + 1
    if c.startswith(p + " "):
        return len(p.split())
    return 0


def parse_ts(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def match_game(games: List[dict], kickoff_utc: str, away: str, home: str, window_h: float = 36) -> Optional[dict]:
    """Return the best-matching stored game dict or None."""
    try:
        k = parse_ts(kickoff_utc)
    except Exception:
        return None
    best, best_score = None, 0
    for g in games:
        try:
            dt = abs((parse_ts(g["kickoff_utc"]) - k).total_seconds()) / 3600
        except Exception:
            continue
        if dt > window_h:
            continue
        a = team_score(g["away"]["name"], away)
        h = team_score(g["home"]["name"], home)
        if a and h:
            sc = a + h - (dt / 100)
            if sc > best_score:
                best, best_score = g, sc
    return best


def match_ref(kickoff_utc: str, away: str, home: str) -> str:
    return f"MATCH|{kickoff_utc}|{away}|{home}"
