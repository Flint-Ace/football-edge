import json, os
from football_edge.store import Store
from football_edge.ingest import ingest
from football_edge.export import export
from football_edge.adapters.cfbd import CFBDAdapter
from football_edge.adapters.odds_api import OddsAPIAdapter
from football_edge.adapters.splits import NullSplitsProvider
from football_edge.adapters.base import AdapterResult

HERE = os.path.dirname(__file__)


class Fixture:
    quota = {}
    def __init__(self, ad, path, name):
        self.ad, self.path, self.name, self.provides = ad, path, name, ad.provides
    def fetch(self, league, **kw):
        return self.ad.parse(league, json.load(open(self.path)), **kw)


def test_cfbd_then_odds_match_and_derive(tmp_path):
    db = tmp_path / "t.sqlite"
    cf = Fixture(CFBDAdapter(), f"{HERE}/fixtures/cfbd_min.json", "cfbd")
    od = Fixture(OddsAPIAdapter(), f"{HERE}/fixtures/odds_min.json", "odds_api")
    s = Store(str(db))
    summ = ingest(s, "cfb", [cf, od, NullSplitsProvider()])
    assert summ["adapters"]["cfbd"]["games"] == 2
    assert summ["adapters"]["odds_api"]["new_lines"] == 2          # two books matched to Florida game
    assert any("unresolved" in e for e in summ["adapters"]["odds_api"]["errors"])  # ghost game not auto-created for CFB
    gid = "cfb-2026-20260926-ole-miss-florida"
    assert s.get_game(gid)["venue"] == "Ben Hill Griffin Stadium"
    out = tmp_path / "cfb.json"
    export(s, "cfb", str(out))
    doc = json.load(open(out))
    g = next(x for x in doc["games"] if x["id"] == gid)
    c = g["market"]["consensus"]
    assert c["spread_home"] == -3.25 and c["total"] == 60.75 and c["books"] == 2
    assert g["market"]["best"]["spread_away"]["value"] == -3.5 and g["market"]["best"]["spread_away"]["book"] == "DraftKings"
    assert g["market"]["best"]["spread_home"]["value"] == -3 and g["market"]["best"]["spread_home"]["book"] == "FanDuel"
    # cfbd opener kept separately, cfbd current recorded
    books = {b["book"]: b for b in g["market"]["books"] if b["provider"] == "cfbd"}
    assert books["DraftKings"]["open"]["spread_home"] == -3 and books["DraftKings"]["current"]["spread_home"] == -3.5
    # graded final game
    m = next(x for x in doc["games"] if x["id"].endswith("iowa-michigan"))
    assert m["grade"]["winner"] == "home" and m["grade"]["ats"] == "home" and m["grade"]["ou"] == "over"
    assert doc["splits_status"]["available"] is False
    h = doc["data_health"]
    assert h["games_loaded"] == 2 and "DraftKings" in h["books_tracked"]
    assert any(p["provider"] == "splits_none" and not p["ok"] for p in h["providers"])


def test_repeat_sync_dedupes(tmp_path):
    s = Store(str(tmp_path / "t.sqlite"))
    od = Fixture(OddsAPIAdapter(), f"{HERE}/fixtures/odds_min.json", "odds_api")
    cf = Fixture(CFBDAdapter(), f"{HERE}/fixtures/cfbd_min.json", "cfbd")
    ingest(s, "cfb", [cf, od]); summ = ingest(s, "cfb", [cf, od])
    assert summ["adapters"]["odds_api"]["new_lines"] == 0 and summ["adapters"]["cfbd"]["new_lines"] == 0
