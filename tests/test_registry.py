"""The registry refuses to load a bad entry. Startup error, not runtime surprise."""
import copy
import json

import pytest

from core.registry import PATH, Registry, RegistryError

GOOD = json.loads(PATH.read_text())


def _load(tmp_path, mutate):
    reg = copy.deepcopy(GOOD)
    mutate(reg["models"])
    p = tmp_path / "registry.json"
    p.write_text(json.dumps(reg))
    return Registry(p)


def test_shipped_registry_loads():
    r = Registry()
    assert r.for_modality("CR")["id"] == "cxr-densenet-v1"
    assert r.for_modality("MR")["id"] == "brain-brats-monai-v0.5.4"


@pytest.mark.parametrize("mutate, message", [
    (lambda m: m[0].update(adapter="adapters.no_such_adapter"), "does not import"),
    (lambda m: m[1]["urgency"].pop("mass_effect"), "no urgency weight"),
    (lambda m: m[0]["urgency"].pop("Pneumothorax"), "no urgency weight"),
    (lambda m: m[0].pop("urgency"), "missing 'urgency'"),
    (lambda m: m[1].update(output_type="label-map"), "unknown output_type"),
    (lambda m: m[1]["anchors"].update(edema_volume=[100, 5]), "floor < ceiling"),
    (lambda m: m[1]["urgency"].update(mass_effect=1.5), "expected 0 to 1"),
    (lambda m: m.append(copy.deepcopy(m[0])), "duplicate model id"),
])
def test_bad_entry_is_a_load_error(tmp_path, mutate, message):
    with pytest.raises(RegistryError, match=message):
        _load(tmp_path, mutate)
