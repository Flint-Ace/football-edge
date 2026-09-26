"""The Odds API adapter (the-odds-api.com). Needs ODDS_API_KEY.
The market/odds layer for both divisions: every pregame spread, moneyline
and total from every US book the key can see. Openers are never taken
from this feed; the store's first snapshot is the opener.
For NFL it is also, for now, the schedule and scores layer (the /scores
endpoint) until a dedicated NFL data adapter is connected.
Credits: /odds with three markets costs 3 per league; /scores costs 2.
Quota headers are captured and stored; the sync skips this adapter when
remaining credits fall below ODDS_RESERVE (default 25)."""
import json
import os
import urllib.request
from datetime import datetime, timezone

from .base import Adapter, AdapterResult
from ..schema import Game, Team, LineObservation, game_id
from ..matching import match_ref

SPORT = {"cfb": "americanfootball_ncaaf", "nfl": "americanfootball_nfl"}
ODDS = "https://api.the-odds-api.com/v4/sports/{sport}/odds/?regions=us&markets=h2h,spreads,totals&oddsFormat=american&apiKey={key}"
SCORES = "https://api.the-odds-api.com/v4/sports/{sport}/scores/?daysFrom=3&apiKey={key}"


class OddsAPIAdapter(Adapter):
    name = "odds_api"
    provides = ("lines", "schedule_nfl", "scores_nfl")
    quota = {}

    def _get(self, url):
        req = urllib.request.Request(url, headers={"User-Agent": "football-edge/0.3"})
        with urllib.request.urlopen(req, timeout=60) as r:
            self.quota = {"remaining": _i(r.headers.get("x-requests-remaining")), "used": _i(r.headers.get("x-requests-used")),
                          "last_cost": _i(r.headers.get("x-requests-last"))}
            return json.load(r)

    def fetch(self, league: str, season=None, **kw) -> AdapterResult:
        key = os.environ.get("ODDS_API_KEY")
        if not key:
            r = AdapterResult(); r.errors.append("ODDS_API_KEY not set; odds_api skipped"); return r
        odds = self._get(ODDS.format(sport=SPORT[league], key=key))
        scores = []
        if league == "nfl":
            try:
                scores = self._get(SCORES.format(sport=SPORT[league], key=key))
            except Exception as e:
                scores = []
                err = f"odds_api /scores failed: {e}"
            else:
                err = None
        else:
            err = None
        out = self.parse(league, {"odds": odds, "scores": scores}, season=season)
        if err:
            out.errors.append(err)
        out.errors.append(f"quota: {json.dumps(self.quota)}")
        return out

    def parse(self, league: str, payload, season=None, **kw) -> AdapterResult:
        out = AdapterResult()
        now = datetime.now(timezone.utc).isoformat()
        odds = payload.get("odds", []) if isinstance(payload, dict) else payload
        scores = payload.get("scores", []) if isinstance(payload, dict) else []
        for ev in odds:
            try:
                kickoff = ev["commence_time"].replace("Z", "+00:00")
                away_n, home_n = ev["away_team"], ev["home_team"]
                ref = match_ref(kickoff, away_n, home_n)
                if league == "nfl":
                    yr = season or _season(kickoff)
                    out.games.append(Game(id=game_id(league, yr, kickoff, away_n, home_n), league=league, season=yr, week=None,
                                          kickoff_utc=kickoff, away=Team(name=away_n), home=Team(name=home_n),
                                          status="scheduled" if kickoff > now else "in_progress",
                                          external_ids={"odds_api": ev.get("id", "")}, updated_at=now))
                    ref = game_id(league, yr, kickoff, away_n, home_n)
                for bm in ev.get("bookmakers", []):
                    ob = LineObservation(ts=(bm.get("last_update") or now).replace("Z", "+00:00"), provider="odds_api", book=bm["title"])
                    for m in bm.get("markets", []):
                        oc = {o["name"]: o for o in m["outcomes"]}
                        if m["key"] == "h2h" and away_n in oc and home_n in oc:
                            ob.ml_away = int(oc[away_n]["price"]); ob.ml_home = int(oc[home_n]["price"])
                        elif m["key"] == "spreads" and home_n in oc:
                            ob.spread_home = float(oc[home_n]["point"])
                            ob.spread_juice_home = int(oc[home_n]["price"]); ob.spread_juice_away = int(oc[away_n]["price"])
                        elif m["key"] == "totals" and "Over" in oc:
                            ob.total = float(oc["Over"]["point"]); ob.over_juice = int(oc["Over"]["price"]); ob.under_juice = int(oc["Under"]["price"])
                    out.lines.setdefault(ref, []).append(ob)
            except Exception as e:
                out.errors.append(f"odds_api parse {ev.get('id')}: {e}")
        for ev in scores:
            try:
                if league != "nfl":
                    continue
                kickoff = ev["commence_time"].replace("Z", "+00:00")
                yr = season or _season(kickoff)
                gid = game_id(league, yr, kickoff, ev["away_team"], ev["home_team"])
                sc = {s["name"]: s["score"] for s in (ev.get("scores") or [])}
                sa, sh = _i(sc.get(ev["away_team"])), _i(sc.get(ev["home_team"]))
                completed = bool(ev.get("completed"))
                status = "final" if completed else ("in_progress" if kickoff <= now else "scheduled")
                out.games.append(Game(id=gid, league=league, season=yr, week=None, kickoff_utc=kickoff,
                                      away=Team(name=ev["away_team"]), home=Team(name=ev["home_team"]), status=status,
                                      score_away=sa, score_home=sh, final_ts=(ev.get("last_update") or now) if completed else None,
                                      external_ids={"odds_api": ev.get("id", "")}, updated_at=now))
            except Exception as e:
                out.errors.append(f"odds_api score parse {ev.get('id')}: {e}")
        return out


def _season(kickoff):
    y, m = int(kickoff[:4]), int(kickoff[5:7])
    return y if m >= 7 else y - 1


def _i(v):
    try:
        return None if v is None else int(v)
    except Exception:
        return None
