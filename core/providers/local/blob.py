"""FileBlob: a directory under data/blob/ standing in for S3.

presigned_url behaves like an S3 presigned GET: with url_base set it returns
an HTTP URL carrying an expiry and an HMAC signature, which the API's
/api/blob route checks before serving the file (core/api.py). Without url_base
it returns a file:// URL, which only code on this machine can open. The AWS
provider returns a real S3 presigned URL instead; the client calls the same
method either way and does not know which it got.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from pathlib import Path
from urllib.parse import quote

from core.ports import BlobPort

DEFAULT_ROOT = Path(__file__).resolve().parents[3] / "data" / "blob"


class FileBlob(BlobPort):
    def __init__(self, root: Path | str = DEFAULT_ROOT, url_base: str | None = None,
                 secret: bytes | None = None):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.url_base = url_base.rstrip("/") if url_base else None
        self._secret = secret or secrets.token_bytes(32)

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

    def _sign(self, key: str, expires: int) -> str:
        return hmac.new(self._secret, f"{key}\n{expires}".encode(), hashlib.sha256).hexdigest()

    def presigned_url(self, key: str, ttl: int = 300) -> str:
        p = self._path(key)
        if not p.exists():
            raise FileNotFoundError(key)
        if self.url_base is None:
            return p.as_uri()
        expires = int(time.time()) + ttl
        return (f"{self.url_base}/{quote(key)}?expires={expires}"
                f"&sig={self._sign(key, expires)}")

    def open_signed(self, key: str, expires: int, sig: str) -> Path:
        """The file behind a presigned URL, or PermissionError if the signature
        is wrong or has expired."""
        if not hmac.compare_digest(sig, self._sign(key, expires)):
            raise PermissionError("bad signature")
        if expires < time.time():
            raise PermissionError("expired")
        p = self._path(key)
        if not p.is_file():
            raise FileNotFoundError(key)
        return p
