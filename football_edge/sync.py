"""CLI. Examples:
  python -m football_edge.sync --league cfb --export
  python -m football_edge.sync --league nfl --adapters odds_api,overrides --export
Environment: ODDS_API_KEY, CFBD_API_KEY (repository secrets; never in
client code), ODDS_RESERVE (credits to keep in hand, default 25),
FE_DB (default football_edge.sqlite)."""
import argparse
import json
import os
from .store import Store
from .ingest import ingest
from .export import export
from .adapters import REGISTRY

DEFAULT = {"cfb": "cfbd,odds_api,splits_none,overrides", "nfl": "odds_api,splits_none,overrides"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--league", choices=["cfb", "nfl"], required=True)
    ap.add_argument("--season", type=int)
    ap.add_argument("--adapters", default=None)
    ap.add_argument("--no-odds", action="store_true", help="skip odds_api this run (quota management)")
    ap.add_argument("--export", action="store_true")
    ap.add_argument("--db", default=os.environ.get("FE_DB", "football_edge.sqlite"))
    a = ap.parse_args()
    store = Store(a.db)
    names = [n for n in (a.adapters or DEFAULT[a.league]).split(",") if n]
    skipped = []
    reserve = int(os.environ.get("ODDS_RESERVE", "25"))
    if "odds_api" in names:
        rem = store.quota("odds_api")
        if a.no_odds:
            names.remove("odds_api"); skipped.append("odds_api: skipped by --no-odds")
        elif rem is not None and rem < reserve:
            names.remove("odds_api"); skipped.append(f"odds_api: skipped, {rem} credits left, reserve {reserve}")
    adapters = [REGISTRY[n]() for n in names]
    summary = ingest(store, a.league, adapters, season=a.season)
    summary["skipped"] = skipped
    splits_status = None
    for ad in adapters:
        if hasattr(ad, "status") and ad.provides == ("splits",):
            splits_status = ad.status()
    if a.export:
        os.makedirs("site/data", exist_ok=True)
        summary["exported_games"] = export(store, a.league, f"site/data/{a.league}.json", season=a.season, splits_status=splits_status)
        with open(f"site/data/sync_{a.league}.json", "w") as f:
            json.dump(summary, f, indent=2)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
