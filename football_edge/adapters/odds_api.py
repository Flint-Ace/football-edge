"""The Odds API adapter (the-odds-api.com). Needs ODDS_API_KEY.
Multi-book current prices for spread, ML and total. No splits. Openers
come from our own first snapshot, never from this feed.
Free tier: 500 credits a month; one league sync with three markets
costs three credits, so a 30 minute Saturday cadence fits."""
import json
import os
import urllib.request
from datetime import datetime, timezone

from .base import Adapter, AdapterResult
from ..schema import LineObservation, game_id

SPORT = {"cfb": "americanfootball_ncaaf", "nfl": "americanfootball_nfl"}
URL = "https://api.the-odds-api.com/v4/sports/{sport}/odds/?regions=us&markets=h2h,spreads,totals&oddsFormat=american&apiKey={key}"


class OddsAPIAdapter(Adapter):
    name = "odds_api"
    provides = ("lines",)

    def fetch(self, league: str, season=None, **kw) -> AdapterResult:
        key = os.environ.get("ODDS_API_KEY")
        if not key:
            r = AdapterResult()
            r.errors.append("ODDS_API_KEY not set; odds_api skipped")
            return r
        req = urllib.request.Request(URL.format(sport=SPORT[league], key=key))
        with urllib.request.urlopen(req, timeout=30) as resp:
            payload = json.load(resp)
        return self.parse(league, payload, season=season)

    def parse(self, league: str, payload, season=None, **kw) -> AdapterResult:
        out = AdapterResult()
        now = datetime.now(timezone.utc).isoformat()
        for ev in payload:
            try:
                kickoff = ev["commence_time"].replace("Z", "+00:00")
                yr = season or int(kickoff[:4])
                gid = game_id(league, yr, kickoff, ev["away_team"], ev["home_team"])
                for bm in ev.get("bookmakers", []):
                    ob = LineObservation(ts=(bm.get("last_update") or now).replace("Z", "+00:00"), provider="odds_api", book=bm["title"])
                    for m in bm.get("markets", []):
                        oc = {o["name"]: o for o in m["outcomes"]}
                        if m["key"] == "h2h":
                            ob.ml_away = int(oc[ev["away_team"]]["price"]); ob.ml_home = int(oc[ev["home_team"]]["price"])
                        elif m["key"] == "spreads":
                            ob.spread_home = float(oc[ev["home_team"]]["point"])
                            ob.spread_juice_home = int(oc[ev["home_team"]]["price"]); ob.spread_juice_away = int(oc[ev["away_team"]]["price"])
                        elif m["key"] == "totals":
                            ob.total = float(oc["Over"]["point"]); ob.over_juice = int(oc["Over"]["price"]); ob.under_juice = int(oc["Under"]["price"])
                    out.lines.setdefault(gid, []).append(ob)
            except Exception as e:
                out.errors.append(f"odds_api parse {ev.get('id')}: {e}")
        return out
