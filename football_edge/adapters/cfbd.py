"""CollegeFootballData adapter (collegefootballdata.com). CFB only.
Needs CFBD_API_KEY (Bearer). The CFB game/data layer: every FBS game for
the season with kickoff, venue, conference, status and scores, plus the
lines CFBD republishes (multiple providers, with openers where CFBD has
them). Two calls per sync: /games and /lines for the whole season.
Free tier is metered monthly, so cadence lives in the workflow."""
import json
import os
import urllib.request
from datetime import datetime, timezone

from .base import Adapter, AdapterResult
from ..schema import Game, Team, LineObservation, game_id

BASE = "https://api.collegefootballdata.com"


def _g(d, *keys, default=None):
    for k in keys:
        if k in d and d[k] is not None:
            return d[k]
    return default


def season_for(now=None):
    now = now or datetime.now(timezone.utc)
    return now.year if now.month >= 7 else now.year - 1


class CFBDAdapter(Adapter):
    name = "cfbd"
    provides = ("schedule", "scores", "lines")

    def _get(self, path, key):
        req = urllib.request.Request(BASE + path, headers={"Authorization": f"Bearer {key}", "Accept": "application/json",
                                                           "User-Agent": "football-edge/0.3"})
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.load(r)

    def fetch(self, league: str, season=None, **kw) -> AdapterResult:
        if league != "cfb":
            r = AdapterResult(); r.errors.append("cfbd covers CFB only; skipped"); return r
        key = os.environ.get("CFBD_API_KEY")
        if not key:
            r = AdapterResult(); r.errors.append("CFBD_API_KEY not set; cfbd skipped"); return r
        yr = season or season_for()
        games = self._get(f"/games?year={yr}&seasonType=regular&division=fbs", key)
        try:
            lines = self._get(f"/lines?year={yr}&seasonType=regular", key)
        except Exception as e:
            lines = []
            err = f"cfbd /lines failed: {e}"
        else:
            err = None
        out = self.parse(league, {"games": games, "lines": lines}, season=yr)
        if err:
            out.errors.append(err)
        return out

    def parse(self, league: str, payload, season=None, **kw) -> AdapterResult:
        out = AdapterResult()
        now = datetime.now(timezone.utc).isoformat()
        games = payload.get("games", []) if isinstance(payload, dict) else payload
        lines = payload.get("lines", []) if isinstance(payload, dict) else []
        by_cfbd_id = {}
        for ev in games:
            try:
                kickoff = _g(ev, "startDate", "start_date")
                if not kickoff:
                    continue
                kickoff = kickoff.replace("Z", "+00:00")
                yr = int(_g(ev, "season", default=season or kickoff[:4]))
                away_n, home_n = _g(ev, "awayTeam", "away_team"), _g(ev, "homeTeam", "home_team")
                gid = game_id(league, yr, kickoff, away_n, home_n)
                completed = bool(_g(ev, "completed", default=False))
                sa, sh = _g(ev, "awayPoints", "away_points"), _g(ev, "homePoints", "home_points")
                status = "final" if completed else ("in_progress" if (sa is not None or sh is not None) and kickoff <= now else "scheduled")
                g = Game(id=gid, league=league, season=yr, week=_g(ev, "week"), kickoff_utc=kickoff,
                         away=Team(name=away_n, conference=_g(ev, "awayConference", "away_conference", default="") or "",
                                   external_ids={"cfbd": str(_g(ev, "awayId", "away_id", default=""))}),
                         home=Team(name=home_n, conference=_g(ev, "homeConference", "home_conference", default="") or "",
                                   external_ids={"cfbd": str(_g(ev, "homeId", "home_id", default=""))}),
                         neutral=bool(_g(ev, "neutralSite", "neutral_site", default=False)),
                         venue=_g(ev, "venue", default="") or "", status=status,
                         score_away=sa if sa is None else int(sa), score_home=sh if sh is None else int(sh),
                         final_ts=now if completed else None,
                         external_ids={"cfbd": str(_g(ev, "id"))}, updated_at=now)
                out.games.append(g)
                by_cfbd_id[str(_g(ev, "id"))] = gid
            except Exception as e:
                out.errors.append(f"cfbd game parse {_g(ev, 'id')}: {e}")
        for ev in lines:
            try:
                gid = by_cfbd_id.get(str(_g(ev, "id")))
                if not gid:
                    continue
                for ln in ev.get("lines", []) or []:
                    book = _g(ln, "provider", default="unknown")
                    cur = LineObservation(ts=now, provider="cfbd", book=book,
                                          spread_home=_f(_g(ln, "spread")), total=_f(_g(ln, "overUnder", "over_under")),
                                          ml_away=_i(_g(ln, "awayMoneyline", "away_moneyline")), ml_home=_i(_g(ln, "homeMoneyline", "home_moneyline")))
                    op_s, op_t = _f(_g(ln, "spreadOpen", "spread_open")), _f(_g(ln, "overUnderOpen", "over_under_open"))
                    if op_s is not None or op_t is not None:
                        out.lines.setdefault(gid, []).append(LineObservation(
                            ts=now, provider="cfbd", book=book, spread_home=op_s, total=op_t, is_open=True,
                            note="opener as reported by CFBD; timestamp is our first sight of it"))
                    out.lines.setdefault(gid, []).append(cur)
            except Exception as e:
                out.errors.append(f"cfbd line parse {_g(ev, 'id')}: {e}")
        return out


def _f(v):
    try:
        return None if v is None or v == "" else float(v)
    except Exception:
        return None


def _i(v):
    try:
        return None if v is None or v == "" else int(v)
    except Exception:
        return None
