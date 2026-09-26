"""Admin Override adapter. Reads overrides/*.json. This is the only
manual path into the store and it goes through the same normalized
schema as every automated adapter. Use it for splits that have no API
(Action Network, VSIN, SBD, your own book's app), always with source
and timestamp.

File format:
{
  "league": "cfb",
  "lines":   { "<game id>": [ {LineObservation fields} ] },
  "splits":  { "<game id>": [ {SplitObservation fields} ] },
  "results": { "<game id>": {"away_score": 0, "home_score": 0} },
  "notes":   { "<game id>": [ {"ts": "...", "kind": "...", "text": "..."} ] }
}
A game id may also be written as "Away @ Home YYYY-MM-DD"; ingest
resolves it against the store by team names and kickoff date."""
import glob
import json
from .base import Adapter, AdapterResult
from ..schema import LineObservation, SplitObservation


class OverrideAdapter(Adapter):
    name = "overrides"
    provides = ("lines", "splits", "results", "notes")

    def __init__(self, folder="overrides"):
        self.folder = folder

    def fetch(self, league: str, **kw) -> AdapterResult:
        out = AdapterResult()
        out.notes = {}
        for path in sorted(glob.glob(f"{self.folder}/*.json")):
            with open(path) as f:
                doc = json.load(f)
            if doc.get("league") != league:
                continue
            for gid, obs in (doc.get("lines") or {}).items():
                out.lines.setdefault(gid, []).extend(LineObservation(**{**o, "origin": "override"}) for o in obs)
            for gid, obs in (doc.get("splits") or {}).items():
                out.splits.setdefault(gid, []).extend(SplitObservation(**{**o, "origin": "override"}) for o in obs)
            out.results.update(doc.get("results") or {})
            for gid, notes in (doc.get("notes") or {}).items():
                out.notes.setdefault(gid, []).extend(notes)
        return out

    def parse(self, league, payload, **kw):
        raise NotImplementedError("overrides are read from disk")
