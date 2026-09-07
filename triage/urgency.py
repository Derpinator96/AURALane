"""Clinical urgency weighting tables.

Loaded from config/urgency.json. Each modality has its own table mapping
finding names to urgency weights in [0, 1]. A weight is NOT a probability —
it encodes how fast the finding needs a human. Pneumothorax at 0.6 outranks
cardiomegaly at 0.9.
"""
import json
import os

_CONFIG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "config", "urgency.json"
)
_cache = None


def _load():
    global _cache
    if _cache is None:
        with open(_CONFIG_PATH) as f:
            _cache = json.load(f)
    return _cache


def get_weights(modality: str) -> dict[str, float]:
    """Return {finding_name: urgency_weight} for the given modality."""
    data = _load()
    return data.get(modality, {})


def get_default() -> float:
    """Default urgency weight for findings not in the table."""
    data = _load()
    return data.get("_default", 0.15)
