import sys
import pytest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture(autouse=True)
def _fixture_annotations_copy(tmp_path_factory, monkeypatch):
    """Notes written through the fixture table go to a copy, never to the
    committed fixtures/annotations.json. Kept out of the test's own tmp_path,
    which some tests list."""
    import shutil
    from core.providers.fixture import ANNOTATIONS
    copy = tmp_path_factory.mktemp("notes") / "annotations.json"
    if ANNOTATIONS.exists():
        shutil.copyfile(ANNOTATIONS, copy)
    monkeypatch.setenv("AURALANE_FIXTURE_ANNOTATIONS", str(copy))
