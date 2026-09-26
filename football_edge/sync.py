"""CLI. Examples:
  python -m football_edge.sync --league cfb --date 20260926
  python -m football_edge.sync --league nfl --week 3
  python -m football_edge.sync --league cfb --adapters espn,overrides --export
Environment: ODDS_API_KEY (optional), FE_DB (default football_edge.sqlite)"""
import argparse
import json
import os
from .store import Store
from .ingest import ingest
from .export import export
from .adapters import REGISTRY


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--league", choices=["cfb", "nfl"], required=True)
    ap.add_argument("--date", help="YYYYMMDD for ESPN")
    ap.add_argument("--week", type=int)
    ap.add_argument("--adapters", default="espn,odds_api,overrides")
    ap.add_argument("--export", action="store_true")
    ap.add_argument("--db", default=os.environ.get("FE_DB", "football_edge.sqlite"))
    a = ap.parse_args()
    if not a.date and not a.week:
        # default: yesterday through +6 days, US Eastern, as an ESPN date range
        from datetime import datetime, timedelta, timezone
        et = datetime.now(timezone.utc) - timedelta(hours=4)
        a.date = f"{(et - timedelta(days=1)):%Y%m%d}-{(et + timedelta(days=6)):%Y%m%d}"
    store = Store(a.db)
    adapters = [REGISTRY[n]() for n in a.adapters.split(",") if n]
    summary = ingest(store, a.league, adapters, date=a.date, week=a.week)
    if a.export:
        os.makedirs("site/data", exist_ok=True)
        summary["exported_games"] = export(store, a.league, f"site/data/{a.league}.json")
    summary["date_arg"] = a.date
    print(json.dumps(summary, indent=2))
    if a.export:
        with open(f"site/data/sync_{a.league}.json", "w") as f:
            json.dump(summary, f, indent=2)


if __name__ == "__main__":
    main()
