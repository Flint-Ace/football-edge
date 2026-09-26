# Football Edge

Market-intelligence research platform for college football (CFB) and NFL, kept as two divisions on one architecture. Provider adapters write into a normalized, append-only store; the UI reads only the exported canonical JSON. No API key ever reaches the browser.

## Layers
- CFB game/data layer: CollegeFootballData (`football_edge/adapters/cfbd.py`). Every FBS game for the season: kickoff, venue, conference, status, scores, plus the lines CFBD republishes with reported openers. Needs `CFBD_API_KEY`.
- Market/odds layer, both divisions: The Odds API (`adapters/odds_api.py`). Every pregame spread, moneyline and total from every US book on the key. For NFL it is also, for now, the schedule and scores layer. Needs `ODDS_API_KEY`. Quota headers are stored; the sync skips this adapter when remaining credits fall under `ODDS_RESERVE` (default 25).
- Betting splits: `adapters/splits.py` defines the provider interface. No provider is connected; `NullSplitsProvider` reports UNAVAILABLE and nothing is estimated. Plug Sportradar or another source in by subclassing `SplitsProvider` and adding it to `REGISTRY` and `DEFAULT` in `sync.py`.
- Admin Override: `adapters/overrides.py` reads `overrides/*.json`. The only manual path. Same schema, origin = override.
- NFL data adapter: not yet written. `sync.DEFAULT["nfl"]` is where it plugs in. Until then NFL schedule and scores come from The Odds API.
- ESPN adapter remains for local use; ESPN blocks GitHub-hosted runners.

## Store rules
`store.py`: games are merged (never blindly replaced; status never regresses); line and split observations are appended, never updated or deleted; identical re-reads bump `last_seen` only. `ingest.detect_closes` marks the last pre-kickoff observation per provider+book as the close once a game goes live. `export.py` derives open (reported opener if present, else first stored), current, close, consensus (median across books, a republished book never double-counted), best available price and movement since open, and grades finals ATS and over/under at the consensus close.

## Secrets (repository Settings, Secrets and variables, Actions)
- `ODDS_API_KEY` from the-odds-api.com
- `CFBD_API_KEY` from collegefootballdata.com
Never commit a key. The workflow reads them as environment variables only.

## Cadence (`.github/workflows/sync.yml`)
- Data sync (CFBD only): every 2 hours, plus every hour on Saturday afternoon and night (US). About 850 CFBD calls a month, under the free tier.
- Market sync (CFBD + The Odds API): 05:00 and 17:00 UTC daily. About 8 credits per run, roughly 480 a month, under the 500 free credits. Move to a paid Odds API tier to sync markets hourly on game days.
- Manual: Actions, football-edge-sync, Run workflow (tick "odds" to include The Odds API).

## Local
```
export CFBD_API_KEY=... ODDS_API_KEY=...
python -m football_edge.sync --league cfb --export
python -m football_edge.sync --league nfl --export
python -m pytest -q tests
```
Site: open `site/index.html` over HTTP (GitHub Pages serves the repo root; `/index.html` forwards to `/site/`).

## UI
Board (command center with filters), Edge Radar, Market Pulse, Public Money, Line Lab, Game Lab (market timeline charts), Paper Book (locked positions, model versions, FE estimates, CLV), Performance Lab, Research Lab, Data Health, Admin Override. Paper Book data lives in the browser's local storage per division; export it from the page.
