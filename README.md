# Football Edge

Provider adapters write into a normalized, append-only store. The UI reads only the exported canonical JSON. Manual entry exists only as Admin Override, through the same schema.

## Layout
- football_edge/schema.py      canonical models (Game, Team, LineObservation, SplitObservation)
- football_edge/adapters/      one file per provider; adapters only translate payloads
    espn.py       schedule, scores, status, rankings, records, weather, DraftKings lines with ESPN's reported opener (no key)
    odds_api.py   multi-book prices from The Odds API (ODDS_API_KEY)
    overrides.py  Admin Override files in overrides/*.json
- football_edge/store.py       SQLite; observations never updated or deleted; identical re-reads bump last_seen only
- football_edge/ingest.py      adapters -> store; closing-line detection; results
- football_edge/export.py      store -> site/data/{league}.json
- football_edge/sync.py        CLI
- site/index.html              UI (reads site/data only)
- .github/workflows/sync.yml   cron every 30 minutes, commits the sqlite file and exports

## Run
    python -m football_edge.sync --league cfb --date 20260926 --export
    python -m football_edge.sync --league nfl --export
    python tests/test_pipeline.py

Serve site/ with any static host (GitHub Pages works: enable Pages on the repo, folder /site).

## Phase map
1 schedule, scores, odds: espn adapter (done). Multi-book: odds_api adapter (done, needs key).
2 line history and closing lines: store + detect_closes (done). History depth is set by the cron cadence.
3 splits: no free API exists. Overrides today; a scraper adapter for public consensus pages is the next adapter to add, kept separate and labeled by source.
4 historical import: run espn with --date for past days (ESPN keeps finals and its openers), or add a CSV adapter for a purchased dataset.
5 to 7: engine, models, injuries and weather build on top of the same store.

## Rules the code enforces
- No provider field names reach the UI. The export is the contract.
- Splits from different books are never merged; each observation carries provider and book.
- A missing value is null and the UI prints UNKNOWN. Nothing is estimated.
- Closing line = last non-opener observation at or before kickoff, per provider and book, set once the game goes live.
