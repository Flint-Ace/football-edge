"""Normalized permanent store (SQLite). Append-only for observations.

Rules enforced here, not in adapters or UI:
- A game row is upserted (schedule/score/status can change).
- Line and split observations are never updated or deleted. If a new
  observation from the same provider+book has identical values to the
  latest one, we do not insert a duplicate; we bump last_seen so the
  freshness is still known. Any value change inserts a new row.
- Closing lines are detected here (see ingest.detect_closes).
"""
import hashlib
import json
import sqlite3
from dataclasses import asdict
from typing import Iterable, List, Optional

from .schema import Game, LineObservation, SplitObservation
from .matching import match_game

SCHEMA = """
CREATE TABLE IF NOT EXISTS games (
  id TEXT PRIMARY KEY, league TEXT, season INT, week INT, kickoff_utc TEXT,
  status TEXT, json TEXT, updated_at TEXT);
CREATE TABLE IF NOT EXISTS line_obs (
  rowid INTEGER PRIMARY KEY, game_id TEXT, ts TEXT, last_seen TEXT, provider TEXT, book TEXT,
  origin TEXT, is_open INT, is_close INT, vhash TEXT, json TEXT);
CREATE INDEX IF NOT EXISTS ix_line_game ON line_obs(game_id, provider, book, ts);
CREATE TABLE IF NOT EXISTS split_obs (
  rowid INTEGER PRIMARY KEY, game_id TEXT, ts TEXT, last_seen TEXT, provider TEXT, book TEXT,
  origin TEXT, vhash TEXT, json TEXT);
CREATE INDEX IF NOT EXISTS ix_split_game ON split_obs(game_id, provider, book, ts);
CREATE TABLE IF NOT EXISTS notes (
  rowid INTEGER PRIMARY KEY, game_id TEXT, ts TEXT, kind TEXT, text TEXT, origin TEXT);
CREATE TABLE IF NOT EXISTS provider_status (
  provider TEXT, league TEXT, last_attempt TEXT, last_success TEXT, ok INT, error TEXT,
  games INT, lines INT, splits INT, quota_remaining INT, quota_used INT, extra TEXT,
  PRIMARY KEY(provider, league));
CREATE TABLE IF NOT EXISTS sync_log (
  rowid INTEGER PRIMARY KEY, ts TEXT, league TEXT, adapter TEXT, games INT, lines INT, splits INT, errors TEXT);
"""

VALUE_FIELDS_LINE = ("spread_home", "spread_juice_home", "spread_juice_away", "ml_away", "ml_home",
                     "total", "over_juice", "under_juice", "is_open", "is_close")
VALUE_FIELDS_SPLIT = ("spread_tix_away", "spread_hdl_away", "ml_tix_away", "ml_hdl_away", "over_tix", "over_hdl")


def _vhash(obj, fields) -> str:
    d = asdict(obj)
    return hashlib.sha1(json.dumps([d.get(f) for f in fields]).encode()).hexdigest()[:16]


class Store:
    def __init__(self, path="football_edge.sqlite"):
        self.conn = sqlite3.connect(path)
        self.conn.executescript(SCHEMA)

    # ---- games ----
    RANK = {"scheduled": 0, "in_progress": 1, "final": 2}

    def upsert_game(self, g: Game):
        """Merge, never blindly replace: a later provider with less detail
        must not erase scores, week, venue or conference from an earlier one,
        and status never regresses (final stays final)."""
        old = self.get_game(g.id)
        if old:
            new = g.to_dict()
            for k, v in list(new.items()):
                if v in (None, "", {}, []) and old.get(k) not in (None, "", {}, []):
                    new[k] = old[k]
            for side in ("away", "home"):
                for k, v in list(new[side].items()):
                    if v in (None, "", {}) and old[side].get(k) not in (None, "", {}):
                        new[side][k] = old[side][k]
                new[side]["external_ids"] = {**old[side].get("external_ids", {}), **(g.to_dict()[side].get("external_ids") or {})}
            new["external_ids"] = {**old.get("external_ids", {}), **(g.external_ids or {})}
            if self.RANK.get(new["status"], 0) < self.RANK.get(old.get("status"), 0):
                new["status"] = old["status"]
                if old.get("score_away") is not None:
                    new["score_away"], new["score_home"], new["final_ts"] = old["score_away"], old["score_home"], old.get("final_ts")
            self.conn.execute("UPDATE games SET league=?,season=?,week=?,kickoff_utc=?,status=?,json=?,updated_at=? WHERE id=?",
                              (new["league"], new["season"], new["week"], new["kickoff_utc"], new["status"], json.dumps(new), new["updated_at"], g.id))
            return
        self.conn.execute(
            "INSERT INTO games(id,league,season,week,kickoff_utc,status,json,updated_at) VALUES(?,?,?,?,?,?,?,?) "
            "ON CONFLICT(id) DO UPDATE SET league=excluded.league, season=excluded.season, week=excluded.week, "
            "kickoff_utc=excluded.kickoff_utc, status=excluded.status, json=excluded.json, updated_at=excluded.updated_at",
            (g.id, g.league, g.season, g.week, g.kickoff_utc, g.status, json.dumps(g.to_dict()), g.updated_at))

    def get_game(self, gid: str) -> Optional[dict]:
        r = self.conn.execute("SELECT json FROM games WHERE id=?", (gid,)).fetchone()
        return json.loads(r[0]) if r else None

    def games(self, league: str, season: int = None) -> List[dict]:
        q, p = "SELECT json FROM games WHERE league=?", [league]
        if season:
            q += " AND season=?"; p.append(season)
        return [json.loads(r[0]) for r in self.conn.execute(q + " ORDER BY kickoff_utc", p)]

    def resolve_game_id(self, league: str, ref: str) -> Optional[str]:
        """Accept a canonical id or 'Away @ Home YYYY-MM-DD'."""
        if self.get_game(ref):
            return ref
        if ref.startswith("MATCH|"):
            _, kick, away, home = ref.split("|", 3)
            g = match_game(self.games(league), kick, away, home)
            return g["id"] if g else None
        if "@" in ref:
            teams, _, date = ref.rpartition(" ")
            away, _, home = teams.partition("@")
            away, home = away.strip().lower(), home.strip().lower()
            for g in self.games(league):
                if g["kickoff_utc"][:10] == date and away in g["away"]["name"].lower() and home in g["home"]["name"].lower():
                    return g["id"]
        return None

    # ---- observations ----
    def add_line(self, gid: str, o: LineObservation) -> bool:
        h = _vhash(o, VALUE_FIELDS_LINE)
        last = self.conn.execute(
            "SELECT rowid, vhash FROM line_obs WHERE game_id=? AND provider=? AND book=? AND is_open=? ORDER BY ts DESC LIMIT 1",
            (gid, o.provider, o.book, int(o.is_open))).fetchone()
        if last and last[1] == h:
            self.conn.execute("UPDATE line_obs SET last_seen=? WHERE rowid=?", (o.ts, last[0]))
            return False
        self.conn.execute(
            "INSERT INTO line_obs(game_id,ts,last_seen,provider,book,origin,is_open,is_close,vhash,json) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (gid, o.ts, o.ts, o.provider, o.book, o.origin, int(o.is_open), int(o.is_close), h, json.dumps(asdict(o))))
        return True

    def add_split(self, gid: str, o: SplitObservation) -> bool:
        h = _vhash(o, VALUE_FIELDS_SPLIT)
        last = self.conn.execute(
            "SELECT rowid, vhash FROM split_obs WHERE game_id=? AND provider=? AND book=? ORDER BY ts DESC LIMIT 1",
            (gid, o.provider, o.book)).fetchone()
        if last and last[1] == h:
            self.conn.execute("UPDATE split_obs SET last_seen=? WHERE rowid=?", (o.ts, last[0]))
            return False
        self.conn.execute(
            "INSERT INTO split_obs(game_id,ts,last_seen,provider,book,origin,vhash,json) VALUES(?,?,?,?,?,?,?,?)",
            (gid, o.ts, o.ts, o.provider, o.book, o.origin, h, json.dumps(asdict(o))))
        return True

    def add_note(self, gid: str, ts: str, kind: str, text: str, origin="override"):
        if self.conn.execute("SELECT 1 FROM notes WHERE game_id=? AND ts=? AND kind=? AND text=?", (gid, ts, kind, text)).fetchone():
            return False
        self.conn.execute("INSERT INTO notes(game_id,ts,kind,text,origin) VALUES(?,?,?,?,?)", (gid, ts, kind, text, origin))
        return True

    def lines(self, gid: str) -> List[dict]:
        rows = self.conn.execute("SELECT json, last_seen, is_close FROM line_obs WHERE game_id=? ORDER BY ts", (gid,)).fetchall()
        out = []
        for j, seen, is_close in rows:
            d = json.loads(j); d["last_seen"] = seen; d["is_close"] = bool(is_close); out.append(d)
        return out

    def splits(self, gid: str) -> List[dict]:
        rows = self.conn.execute("SELECT json, last_seen FROM split_obs WHERE game_id=? ORDER BY ts", (gid,)).fetchall()
        out = []
        for j, seen in rows:
            d = json.loads(j); d["last_seen"] = seen; out.append(d)
        return out

    def notes(self, gid: str) -> List[dict]:
        return [dict(ts=r[0], kind=r[1], text=r[2], origin=r[3]) for r in
                self.conn.execute("SELECT ts,kind,text,origin FROM notes WHERE game_id=? ORDER BY ts", (gid,))]

    def mark_close(self, rowid: int):
        self.conn.execute("UPDATE line_obs SET is_close=1 WHERE rowid=?", (rowid,))

    def has_close(self, gid: str, provider: str, book: str) -> bool:
        return bool(self.conn.execute("SELECT 1 FROM line_obs WHERE game_id=? AND provider=? AND book=? AND is_close=1",
                                      (gid, provider, book)).fetchone())

    def latest_pre_kickoff(self, gid: str, provider: str, book: str, kickoff: str):
        return self.conn.execute(
            "SELECT rowid FROM line_obs WHERE game_id=? AND provider=? AND book=? AND is_open=0 AND ts<=? ORDER BY ts DESC LIMIT 1",
            (gid, provider, book, kickoff)).fetchone()

    def latest_any(self, gid: str, provider: str, book: str):
        return self.conn.execute(
            "SELECT rowid FROM line_obs WHERE game_id=? AND provider=? AND book=? AND is_open=0 ORDER BY ts DESC LIMIT 1",
            (gid, provider, book)).fetchone()

    def books_for(self, gid: str):
        return self.conn.execute("SELECT DISTINCT provider, book FROM line_obs WHERE game_id=?", (gid,)).fetchall()

    def set_status(self, provider, league, ts, ok, error="", games=0, lines=0, splits=0,
                   quota_remaining=None, quota_used=None, extra=None):
        prev = self.conn.execute("SELECT last_success, quota_remaining, quota_used FROM provider_status WHERE provider=? AND league=?",
                                 (provider, league)).fetchone()
        last_success = ts if ok else (prev[0] if prev else None)
        if quota_remaining is None and prev:
            quota_remaining, quota_used = prev[1], prev[2]
        self.conn.execute(
            "INSERT OR REPLACE INTO provider_status(provider,league,last_attempt,last_success,ok,error,games,lines,splits,quota_remaining,quota_used,extra) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (provider, league, ts, last_success, int(ok), error, games, lines, splits, quota_remaining, quota_used, json.dumps(extra or {})))

    def status(self, league):
        cols = ["provider", "league", "last_attempt", "last_success", "ok", "error", "games", "lines", "splits", "quota_remaining", "quota_used", "extra"]
        out = []
        for r in self.conn.execute("SELECT * FROM provider_status WHERE league=? ORDER BY provider", (league,)):
            d = dict(zip(cols, r)); d["ok"] = bool(d["ok"]); d["extra"] = json.loads(d["extra"] or "{}"); out.append(d)
        return out

    def quota(self, provider):
        r = self.conn.execute("SELECT quota_remaining FROM provider_status WHERE provider=? AND quota_remaining IS NOT NULL ORDER BY last_attempt DESC LIMIT 1", (provider,)).fetchone()
        return r[0] if r else None

    def all_books(self, league):
        return [r[0] for r in self.conn.execute(
            "SELECT DISTINCT l.book FROM line_obs l JOIN games g ON g.id=l.game_id WHERE g.league=? AND l.origin='auto'", (league,))]

    def latest_market_ts(self, league):
        r = self.conn.execute("SELECT MAX(l.last_seen) FROM line_obs l JOIN games g ON g.id=l.game_id WHERE g.league=? AND l.origin='auto'", (league,)).fetchone()
        return r[0] if r else None

    def log(self, ts, league, adapter, games, lines, splits, errors):
        self.conn.execute("INSERT INTO sync_log(ts,league,adapter,games,lines,splits,errors) VALUES(?,?,?,?,?,?,?)",
                          (ts, league, adapter, games, lines, splits, json.dumps(errors)))

    def commit(self):
        self.conn.commit()
