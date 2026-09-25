"""The privacy page states two expiry times; they must match the code."""
import inspect
from pathlib import Path

from core.providers.local import DevAuth, FileBlob

PAGE = (Path(__file__).resolve().parents[1] / "client" / "src" / "Legal.jsx").read_text()


def test_privacy_page_expiries_match_the_code():
    assert inspect.signature(DevAuth.issue).parameters["ttl"].default == 3600
    assert "expires after one hour" in PAGE
    assert inspect.signature(FileBlob.presigned_url).parameters["ttl"].default == 300
    assert "expire after five" in PAGE and "minutes" in PAGE
