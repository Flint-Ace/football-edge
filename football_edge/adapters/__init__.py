from .base import Adapter, AdapterResult
from .espn import ESPNAdapter
from .odds_api import OddsAPIAdapter
from .cfbd import CFBDAdapter
from .overrides import OverrideAdapter
from .splits import NullSplitsProvider, SplitsProvider

REGISTRY = {"espn": ESPNAdapter, "odds_api": OddsAPIAdapter, "cfbd": CFBDAdapter,
            "overrides": OverrideAdapter, "splits_none": NullSplitsProvider}
