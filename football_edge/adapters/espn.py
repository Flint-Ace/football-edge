"""ESPN public scoreboard adapter.

Provides schedule, scores, status, rankings, records, weather, and the
lines ESPN embeds (DraftKings, with ESPN's reported opener and current).
No public splits. No key required.

  CFB: .../football/college-football/scoreboard?groups=80&dates=YYYYMMDD&limit=300
  NFL: .../football/nfl/scoreboard?dates=YYYYMMDD
"""
from datetime import datetime, timezone
from typing import Optional
import json
import urllib.request

from .base import Adapter, AdapterResult
from ..schema import Game, Team, LineObservation, game_id

BASE = "https://site.api.espn.com/apis/site/v2/sports/football/{league}/scoreboard"
LEAGUE_PATH = {"cfb": "college-football", "nfl": "nfl"}


def _num(v) -> Optional[float]:
    if v in (None, "", "OFF"):
        return None
    if v == "EVEN":
        return 0.0
    try:
        return float(str(v).replace("o", "").replace("u", "").replace("+", ""))
    except ValueError:
        return None


def _ml(v) -> Optional[int]:
    if v == "EVEN":
        return 100
    n = _num(v)
    return None if n is None else int(n)


def _pick(d, *path):
    for p in path:
        if not isinstance(d, dict):
            return None
        d = d.get(p)
    return d


class ESPNAdapter(Adapter):
    name = "espn"
    provides = ("schedule", "scores", "lines", "weather")

    def url(self, league: str, date: str = None, week: int = None) -> str:
        u = BASE.format(league=LEAGUE_PATH[league]) + "?limit=300"
        if league == "cfb":
            u += "&groups=80"
        if date:
            u += f"&dates={date}"
        if week:
            u += f"&week={week}"
        return u

    HOSTS = [
        "https://site.api.espn.com/apis/site/v2/sports/football/{league}/scoreboard",
        "https://site.web.api.espn.com/apis/site/v2/sports/football/{league}/scoreboard",
        "https://cdn.espn.com/core/{league}/scoreboard",
    ]

    def fetch(self, league: str, date: str = None, week: int = None, **kw) -> AdapterResult:
        q = "?limit=300" + ("&groups=80" if league == "cfb" else "")
        if date:
            q += f"&dates={date}"
        if week:
            q += f"&week={week}"
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36",
                   "Accept": "application/json,text/plain,*/*", "Accept-Language": "en-US,en;q=0.9",
                   "Referer": "https://www.espn.com/"}
        errors = []
        for host in self.HOSTS:
            u = host.format(league=LEAGUE_PATH[league]) + q
            if "cdn.espn.com" in host:
                u += "&xhr=1"
            try:
                req = urllib.request.Request(u, headers=headers)
                with urllib.request.urlopen(req, timeout=30) as r:
                    payload = json.load(r)
                if "cdn.espn.com" in host:
                    payload = payload.get("content", {}).get("sbData", payload)
                res = self.parse(league, payload)
                res.errors.append(f"source host: {host.split('/')[2]}")
                return res
            except Exception as e:
                errors.append(f"{host.split('/')[2]}: {e}")
        raise RuntimeError("; ".join(errors))

    def parse(self, league: str, payload, **kw) -> AdapterResult:
        out = AdapterResult()
        now = datetime.now(timezone.utc).isoformat()
        season = int(_pick(payload, "season", "year") or 0)
        for ev in payload.get("events", []):
            try:
                comp = ev["competitions"][0]
                teams = {c["homeAway"]: c for c in comp["competitors"]}
                away, home = teams["away"], teams["home"]

                def team(c):
                    t = c["team"]
                    rank = _pick(c, "curatedRank", "current")
                    rank = int(rank) if rank and int(rank) < 99 else None
                    rec = next((r["summary"] for r in c.get("records", []) if r.get("type") == "total"), "")
                    return Team(name=t.get("shortDisplayName") or t["displayName"], abbrev=t.get("abbreviation", ""),
                                rank=rank, record=rec, conference=str(t.get("conferenceId", "")),
                                external_ids={"espn": str(t["id"])})

                a, h = team(away), team(home)
                kickoff = ev["date"].replace("Z", "+00:00")
                gid = game_id(league, season, kickoff, a.name, h.name)
                st = comp["status"]["type"]
                state = st.get("state")
                status = {"pre": "scheduled", "in": "in_progress", "post": "final"}.get(state, "scheduled")
                if st.get("name") == "STATUS_POSTPONED":
                    status = "postponed"
                if st.get("name") == "STATUS_CANCELED":
                    status = "canceled"
                sa = int(away.get("score") or 0) if state != "pre" else None
                sh = int(home.get("score") or 0) if state != "pre" else None
                g = Game(id=gid, league=league, season=season, week=_pick(ev, "week", "number"),
                         kickoff_utc=kickoff, away=a, home=h, neutral=bool(comp.get("neutralSite")),
                         venue=_pick(comp, "venue", "fullName") or "", status=status,
                         period=comp["status"].get("period"), clock=comp["status"].get("displayClock", ""),
                         score_away=sa, score_home=sh, final_ts=now if status == "final" else None,
                         external_ids={"espn": str(ev["id"])},
                         weather={"summary": _pick(comp, "weather", "displayValue"), "temp": _pick(comp, "weather", "temperature")} if comp.get("weather") else {},
                         updated_at=now)
                out.games.append(g)

                for o in comp.get("odds", []):
                    book = _pick(o, "provider", "name") or "unknown"
                    ps, ml, tot = o.get("pointSpread") or {}, o.get("moneyline") or {}, o.get("total") or {}
                    cur = LineObservation(ts=now, provider="espn", book=book,
                                          spread_home=_num(_pick(ps, "home", "close", "line")),
                                          spread_juice_home=_ml(_pick(ps, "home", "close", "odds")),
                                          spread_juice_away=_ml(_pick(ps, "away", "close", "odds")),
                                          ml_away=_ml(_pick(ml, "away", "close", "odds")),
                                          ml_home=_ml(_pick(ml, "home", "close", "odds")),
                                          total=_num(_pick(tot, "over", "close", "line")),
                                          over_juice=_ml(_pick(tot, "over", "close", "odds")),
                                          under_juice=_ml(_pick(tot, "under", "close", "odds")))
                    if cur.spread_home is None and o.get("spread") is not None:
                        fav_home = bool(_pick(o, "homeTeamOdds", "favorite"))
                        cur.spread_home = -abs(float(o["spread"])) if fav_home else abs(float(o["spread"]))
                    if cur.total is None and o.get("overUnder") is not None:
                        cur.total = float(o["overUnder"])
                    opn = LineObservation(ts=kickoff[:10] + "T00:00:00+00:00", provider="espn", book=book, is_open=True,
                                          note="opener as reported by ESPN; ESPN gives no opening timestamp",
                                          spread_home=_num(_pick(ps, "home", "open", "line")),
                                          spread_juice_home=_ml(_pick(ps, "home", "open", "odds")),
                                          spread_juice_away=_ml(_pick(ps, "away", "open", "odds")),
                                          ml_away=_ml(_pick(ml, "away", "open", "odds")),
                                          ml_home=_ml(_pick(ml, "home", "open", "odds")),
                                          total=_num(_pick(tot, "over", "open", "line")),
                                          over_juice=_ml(_pick(tot, "over", "open", "odds")),
                                          under_juice=_ml(_pick(tot, "under", "open", "odds")))
                    obs = [cur]
                    if any(v is not None for v in (opn.spread_home, opn.ml_away, opn.ml_home, opn.total)):
                        obs.insert(0, opn)
                    out.lines.setdefault(gid, []).extend(obs)
            except Exception as e:
                out.errors.append(f"espn parse {ev.get('id')}: {e}")
        return out
