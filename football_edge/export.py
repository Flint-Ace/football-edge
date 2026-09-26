"""Export the store to one JSON file per league for the UI. The UI reads
only this file; it never sees a provider payload."""
import json
from datetime import datetime, timezone
from .store import Store


def export(store: Store, league: str, out_path: str, season: int = None):
    games = []
    for g in store.games(league, season):
        gid = g["id"]
        games.append({**g, "lines": store.lines(gid), "splits": store.splits(gid), "notes": store.notes(gid)})
    doc = {"league": league, "generated_at": datetime.now(timezone.utc).isoformat(), "games": games,
           "schema": {"spread_home": "home team number, negative = home favored", "pct_away": "percent on away side",
                      "origin": "auto = adapter, override = admin override file"}}
    with open(out_path, "w") as f:
        json.dump(doc, f, separators=(",", ":"))
    return len(games)
