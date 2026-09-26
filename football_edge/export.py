"""Export the store to one JSON file per league for the UI. The UI reads
only this file; it never sees a provider payload or an API key.
Derived prices (opening, current, closing, consensus, best available,
movement) are computed here from stored observations, never from a
provider's own labels, except that a provider-reported opener is kept
as an is_open observation and preferred when present."""
import json
import statistics
from datetime import datetime, timezone
from .store import Store

PRICE_KEYS = ("spread_home", "spread_juice_home", "spread_juice_away", "ml_away", "ml_home", "total", "over_juice", "under_juice")


def _slim(o):
    return {k: o.get(k) for k in ("ts", "last_seen", "provider", "book", "origin", "is_open", "is_close", "note", *PRICE_KEYS) if o.get(k) is not None}


def _median(vals):
    vals = [v for v in vals if v is not None]
    return round(statistics.median(vals), 2) if vals else None


def derive(lines):
    """Per book: open / current / close. Then consensus and best price."""
    books = {}
    for o in lines:
        key = f"{o['provider']}|{o['book']}"
        b = books.setdefault(key, {"provider": o["provider"], "book": o["book"], "origin": o["origin"], "n": 0,
                                   "open": None, "current": None, "close": None})
        b["n"] += 1
        if o.get("is_open"):
            if b["open"] is None or o["ts"] < b["open"]["ts"]:
                b["open"] = _slim(o)
            continue
        if b["open"] is None or (b["open"].get("_first") and o["ts"] < b["open"]["ts"]):
            b["open"] = {**_slim(o), "_first": True}
        if b["current"] is None or o["ts"] >= b["current"]["ts"]:
            b["current"] = _slim(o)
        if o.get("is_close"):
            b["close"] = _slim(o)
    for b in books.values():
        if b["open"]:
            b["open"].pop("_first", None)
    auto = [b for b in books.values() if b["origin"] == "auto"]
    # A book republished by a secondary provider (CFBD's DraftKings) must not
    # double-count the same book from the primary market feed.
    primary = {b["book"].lower() for b in auto if b["provider"] == "odds_api"}
    auto = [b for b in auto if b["provider"] == "odds_api" or b["book"].lower() not in primary]
    use = auto or list(books.values())
    cur = [b["current"] for b in use if b["current"]]
    opn = [b["open"] for b in use if b["open"]]
    cls = [b["close"] for b in use if b["close"]]
    consensus = {
        "spread_home": _median([c.get("spread_home") for c in cur]), "total": _median([c.get("total") for c in cur]),
        "ml_home": _median([c.get("ml_home") for c in cur]), "ml_away": _median([c.get("ml_away") for c in cur]),
        "open_spread_home": _median([c.get("spread_home") for c in opn]), "open_total": _median([c.get("total") for c in opn]),
        "close_spread_home": _median([c.get("spread_home") for c in cls]), "close_total": _median([c.get("total") for c in cls]),
        "books": len(cur)}
    for k, a, b in (("move_spread", "spread_home", "open_spread_home"), ("move_total", "total", "open_total")):
        consensus[k] = round(consensus[a] - consensus[b], 2) if consensus[a] is not None and consensus[b] is not None else None
    best = {}

    def pick(field, fn, label, juice=None):
        cands = [(c[field], c) for c in cur if c.get(field) is not None]
        if cands:
            v, c = fn(cands, key=lambda x: x[0])
            best[label] = {"value": v, "book": c["book"], "juice": c.get(juice) if juice else None}
    pick("spread_home", max, "spread_home", "spread_juice_home")   # most points for a home bettor
    pick("spread_home", min, "spread_away", "spread_juice_away")   # fewest points laid by an away bettor
    pick("ml_home", max, "ml_home"); pick("ml_away", max, "ml_away")
    pick("total", min, "over", "over_juice"); pick("total", max, "under", "under_juice")
    return {"books": list(books.values()), "consensus": consensus, "best": best}


def grade(g, consensus):
    if g.get("status") != "final" or g.get("score_home") is None or g.get("score_away") is None:
        return None
    margin = g["score_home"] - g["score_away"]
    out = {"margin_home": margin, "total_points": g["score_home"] + g["score_away"],
           "winner": "home" if margin > 0 else ("away" if margin < 0 else "tie")}
    sp = consensus.get("close_spread_home") if consensus.get("close_spread_home") is not None else consensus.get("spread_home")
    if sp is not None:
        d = margin + sp
        out["ats_close_spread_home"] = sp
        out["ats"] = "home" if d > 0 else ("away" if d < 0 else "push")
    tt = consensus.get("close_total") if consensus.get("close_total") is not None else consensus.get("total")
    if tt is not None:
        out["close_total"] = tt
        out["ou"] = "over" if out["total_points"] > tt else ("under" if out["total_points"] < tt else "push")
    return out


def export(store: Store, league: str, out_path: str, season: int = None, splits_status=None):
    games = []
    for g in store.games(league, season):
        gid = g["id"]
        lines = store.lines(gid)
        d = derive(lines)
        games.append({**g, "lines": [_slim(o) for o in lines], "splits": store.splits(gid), "notes": store.notes(gid),
                      "market": d, "grade": grade(g, d["consensus"])})
    status = store.status(league)
    books = store.all_books(league)
    health = {"providers": status, "books_tracked": books, "books_count": len(books), "games_loaded": len(games),
              "games_with_market": sum(1 for x in games if x["market"]["consensus"]["books"]),
              "latest_market_update": store.latest_market_ts(league),
              "quota": {s["provider"]: {"remaining": s["quota_remaining"], "used": s["quota_used"]} for s in status if s["quota_remaining"] is not None},
              "errors": [e for s in status for e in s["extra"].get("errors", []) if not e.startswith("quota")][:60]}
    doc = {"league": league, "generated_at": datetime.now(timezone.utc).isoformat(), "games": games,
           "splits_status": splits_status or {"available": False, "provider": "No splits provider connected"},
           "data_health": health,
           "schema": {"spread_home": "home team number, negative = home favored", "pct_away": "percent on away side",
                      "origin": "auto = adapter, override = admin override file",
                      "open": "provider-reported opener when present, else our first stored observation",
                      "close": "last observation at or before kickoff per book, set once the game goes live"}}
    with open(out_path, "w") as f:
        json.dump(doc, f, separators=(",", ":"))
    return len(games)
