"""Makes every skip visible at the end of a run.

A suite that goes green because the privacy tests quietly skipped is worse than
a red one. Every skip is listed with its reason, and privacy skips are counted
on their own line. Skip reasons in this repository say what was NOT verified.

tests/test_privacy_gate.py fails outright when the chest corpus or Tesseract is
missing, unless AURALANE_ALLOW_SKIP=1 is set, and this summary says when it was.

Markers (registered in pyproject.toml):
    privacy     de-identification checks
    local_data  needs data that is not in git (images/, data/ corpora)
    slow        minutes, not seconds; skipped unless AURALANE_RUN_SLOW=1, and
                the skip is listed like any other
"""
import os
import shutil

TESSERACT = shutil.which("tesseract") is not None


def pytest_collection_modifyitems(config, items):
    if os.environ.get("AURALANE_RUN_SLOW") == "1":
        return
    import pytest
    for item in items:
        if "slow" in item.keywords:
            item.add_marker(pytest.mark.skip(
                reason="slow; set AURALANE_RUN_SLOW=1. NOT VERIFIED in this run: "
                       + (item.function.__doc__ or item.name).strip().splitlines()[0]))


def pytest_terminal_summary(terminalreporter, exitstatus, config):
    if os.environ.get("AURALANE_ALLOW_SKIP") == "1":
        terminalreporter.write_sep(
            "=", "AURALANE_ALLOW_SKIP=1: missing corpus or Tesseract was permitted for this run",
            yellow=True, bold=True)
    skipped = terminalreporter.stats.get("skipped", [])
    if not skipped:
        terminalreporter.write_sep("=", "0 tests skipped", green=True)
        return
    privacy = [r for r in skipped if "privacy" in r.keywords]
    terminalreporter.write_sep(
        "=", f"{len(skipped)} tests SKIPPED, {len(privacy)} of them privacy tests: "
             f"these were NOT verified", red=bool(privacy), yellow=not privacy, bold=True)
    for r in skipped:
        reason = r.longrepr[2] if isinstance(r.longrepr, tuple) else str(r.longrepr)
        reason = reason.removeprefix("Skipped: ")
        tag = "[privacy] " if "privacy" in r.keywords else ""
        terminalreporter.write_line(f"  {tag}{r.nodeid}")
        terminalreporter.write_line(f"      {reason}")
