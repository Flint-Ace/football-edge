from .base import Adapter, AdapterResult
from .espn import ESPNAdapter
from .odds_api import OddsAPIAdapter
from .overrides import OverrideAdapter

REGISTRY = {"espn": ESPNAdapter, "odds_api": OddsAPIAdapter, "overrides": OverrideAdapter}
