"""FileBlob: a directory under data/blob/ standing in for S3."""
from __future__ import annotations

from pathlib import Path

from core.ports import BlobPort

DEFAULT_ROOT = Path(__file__).resolve().parents[3] / "data" / "blob"


class FileBlob(BlobPort):
    def __init__(self, root: Path | str = DEFAULT_ROOT):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        p = (self.root / key).resolve()
        if self.root not in p.parents:
            raise ValueError(f"blob key escapes the store: {key!r}")
        return p

    def put(self, key: str, data: bytes) -> str:
        p = self._path(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
        return key

    def get(self, key: str) -> bytes:
        return self._path(key).read_bytes()

    def delete(self, key: str) -> None:
        self._path(key).unlink(missing_ok=True)

    def presigned_url(self, key: str, ttl: int = 300) -> str:
        """A file:// URL. Local files do not expire; ttl is ignored."""
        p = self._path(key)
        if not p.exists():
            raise FileNotFoundError(key)
        return p.as_uri()
