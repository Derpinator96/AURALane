"""The client tests' worklist fixture is exactly what the API returns for fixtures/."""
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("export", ROOT / "scripts" / "export_client_fixture.py")
export = importlib.util.module_from_spec(spec)
spec.loader.exec_module(export)


def test_client_fixture_matches_the_api():
    assert export.OUT.read_text() == export.render(export.current()), (
        "client/src/test/worklist.api.json is stale; run python scripts/export_client_fixture.py")


def test_client_study_fixture_matches_the_api():
    assert export.STUDY_OUT.read_text() == export.render(export.current_study()), (
        "client/src/test/study.api.json is stale; run python scripts/export_client_fixture.py")
