import json, os, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from football_edge.adapters.espn import ESPNAdapter
from football_edge.adapters.overrides import OverrideAdapter
from football_edge.store import Store
from football_edge.ingest import ingest, detect_closes
from football_edge.export import export


class FixtureESPN(ESPNAdapter):
    def __init__(self, path, mutate=None):
        self.path, self.mutate = path, mutate
    def fetch(self, league, **kw):
        payload = json.load(open(self.path))
        if self.mutate: self.mutate(payload)
        return self.parse(league, payload)


def test_pipeline(tmpdir=None):
    d = tempfile.mkdtemp()
    db = os.path.join(d, "t.sqlite")
    store = Store(db)
    fx = os.path.join(os.path.dirname(__file__), "fixtures", "espn_min.json")
    s = ingest(store, "cfb", [FixtureESPN(fx), OverrideAdapter(os.path.join(os.path.dirname(__file__), "..", "overrides"))])
    assert s["adapters"]["espn"]["games"] == 4, s
    gid = store.resolve_game_id("cfb", "Ole Miss @ Florida 2026-09-26")
    assert gid == "cfb-2026-20260926-ole-miss-florida", gid
    L = store.lines(gid)
    assert any(o["is_open"] for o in L) and any(o["provider"] == "espn" and not o["is_open"] for o in L)
    assert len(store.splits(gid)) == 2 and len(store.notes(gid)) == 4
    # re-ingest identical: no duplicate rows
    n_before = len(L)
    ingest(store, "cfb", [FixtureESPN(fx)])
    assert len(store.lines(gid)) == n_before, "duplicate inserted on identical values"
    # price change appends
    def bump(p): p["events"][0]["competitions"][0]["odds"][0]["pointSpread"]["home"]["close"]["line"] = "-4"
    ingest(store, "cfb", [FixtureESPN(fx, bump)])
    assert len(store.lines(gid)) == n_before + 1
    # game goes live -> closing detected on last pre-kick obs
    def live(p):
        for ev in p["events"]:
            ev["competitions"][0]["status"]["type"] = {"name": "STATUS_IN_PROGRESS", "state": "in"}
    ingest(store, "cfb", [FixtureESPN(fx, live)])
    closes = [o for o in store.lines(gid) if o.get("is_close")]
    assert closes, "no close detected"
    n = export(store, "cfb", os.path.join(d, "cfb.json"))
    assert n == 4
    doc = json.load(open(os.path.join(d, "cfb.json")))
    assert doc["games"][0]["lines"]
    print("PIPELINE_OK", gid, "lines", len(store.lines(gid)), "close rows", len(closes))


if __name__ == "__main__":
    test_pipeline()
