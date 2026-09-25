"""Model registry: models/registry.json, validated when it loads.

A malformed entry, an adapter module that does not import, or a finding with no
urgency weight is a RegistryError at startup, not a surprise on the first study.
"""
from __future__ import annotations

import importlib
import json
from pathlib import Path
from types import ModuleType
from typing import Any

import triage
from core.types import Findings

PATH = Path(__file__).resolve().parents[1] / "models" / "registry.json"

# Required keys and their types, then extra keys per output_type.
SCHEMA = {
    "id": str, "modality": str, "reading_pool": str, "input": dict, "runtime": str,
    "output_type": str, "adapter": str, "urgency": dict,
}
BY_OUTPUT = {
    "multilabel": {"reference": str, "z_anchor": list},
    "segmentation-probability": {"output_channels": list, "anchors": dict,
                                 "min_tumor_ml": (int, float)},
}
RUNTIMES = {"lambda", "sagemaker-async", "in-process"}


class RegistryError(ValueError):
    pass


def _check(entry: dict, i: int) -> None:
    where = f"registry entry {i} ({entry.get('id', '?')})"
    kind = entry.get("output_type")
    if kind not in BY_OUTPUT:
        raise RegistryError(f"{where}: unknown output_type {kind!r}")
    for key, typ in {**SCHEMA, **BY_OUTPUT[kind]}.items():
        if key not in entry:
            raise RegistryError(f"{where}: missing {key!r}")
        if not isinstance(entry[key], typ):
            raise RegistryError(f"{where}: {key!r} has type {type(entry[key]).__name__}")
    if entry["runtime"] not in RUNTIMES:
        raise RegistryError(f"{where}: unknown runtime {entry['runtime']!r}")
    for name, w in entry["urgency"].items():
        if not isinstance(w, (int, float)) or not 0 <= w <= 1:
            raise RegistryError(f"{where}: urgency {name!r} = {w!r}, expected 0 to 1")
    for name, pair in entry.get("anchors", {}).items():
        if not (isinstance(pair, list) and len(pair) == 2 and pair[0] < pair[1]):
            raise RegistryError(f"{where}: anchor {name!r} must be [floor, ceiling], floor < ceiling")


class Registry:
    def __init__(self, path: Path | str = PATH):
        raw = json.loads(Path(path).read_text())
        self.entries: dict[str, dict] = {}
        self.adapters: dict[str, ModuleType] = {}
        for i, entry in enumerate(raw["models"]):
            _check(entry, i)
            if entry["id"] in self.entries:
                raise RegistryError(f"duplicate model id {entry['id']!r}")
            try:
                mod = importlib.import_module(entry["adapter"])
            except ImportError as e:
                raise RegistryError(f"{entry['id']}: adapter {entry['adapter']!r} "
                                    f"does not import: {e}") from e
            if not (callable(getattr(mod, "adapt", None))
                    and callable(getattr(mod, "finding_names", None))):
                raise RegistryError(f"{entry['id']}: {entry['adapter']} lacks adapt "
                                    f"or finding_names")
            if entry["input"].get("format") == "nifti" and not callable(
                    getattr(mod, "resolve_channels", None)):
                raise RegistryError(f"{entry['id']}: multi-series input needs "
                                    f"{entry['adapter']}.resolve_channels")
            missing = [f for f in mod.finding_names(entry) if f not in entry["urgency"]]
            if missing:
                raise RegistryError(f"{entry['id']}: no urgency weight for {missing}")
            self.entries[entry["id"]] = entry
            self.adapters[entry["id"]] = mod

    def get(self, model_id: str) -> dict:
        return self.entries[model_id]

    def for_modality(self, modality: str) -> dict:
        hits = [e for e in self.entries.values() if e["modality"] == modality]
        if len(hits) != 1:
            raise LookupError(f"{len(hits)} registered models for modality {modality!r}")
        return hits[0]

    def adapter(self, entry: dict) -> ModuleType:
        return self.adapters[entry["id"]]


def rank(findings: Findings, entry: dict) -> dict[str, Any]:
    """Findings -> triage decision, with the entry's urgency weights.

    Confidence and raw values are passed through only when the adapter supplied
    them (the chest model does, the brain model has none).
    """
    return triage.rank(findings.findings, entry["urgency"],
                       confidence=findings.meta.get("confidence"),
                       raw=findings.meta.get("raw"))
