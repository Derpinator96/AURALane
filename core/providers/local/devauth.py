"""DevAuth: HS256 JWTs signed with a local key. DEVELOPMENT ONLY.

Never deploy this in front of real data. It stands in for Cognito on localhost
so the API can check a bearer token and a group without an AWS account. Anyone
holding the key can mint any identity. The one hosted use is the fixture
preview (synthetic rows, no datastore), and there core/run.py refuses to serve
beyond loopback unless the password and signing key are set explicitly.

The key comes from the secret argument, else AURALANE_DEV_JWT_SECRET, else
key_file (created with a random key on first use), so a token printed by
`python -m core.run token` verifies in a separate `serve` process. With none of
the three, the key is random per instance.

Seeded users, all synthetic:
    radiologist@dev.auralane.local     group radiologist (the original development user)
    radiologist-1..4@dev.auralane.local group radiologist (readers for distribution;
                                       names and reading pools in models/readers.json)
    admin@dev.auralane.local           group admin

login() accepts any seeded user (by key or email) with the development
password, resolved the same way as the key: the password argument, else
AURALANE_DEV_PASSWORD, else password_file (created with a random value on first
use), else random per instance. No password is written in this repository.
"""
from __future__ import annotations

import os
import secrets
import time
from pathlib import Path

import jwt      # PyJWT: jwt.encode(payload, key, algorithm=), jwt.decode(token, key, algorithms=, audience=)

from core.ports import AuthPort
from core.types import Principal

ISSUER = "auralane-devauth"
AUDIENCE = "auralane-local"

SEEDED = {
    "radiologist": Principal("dev-radiologist-1", "radiologist@dev.auralane.local",
                             ("radiologist",)),
    **{f"radiologist-{n}": Principal(f"dev-radiologist-r{n}",
                                     f"radiologist-{n}@dev.auralane.local", ("radiologist",))
       for n in range(1, 5)},
    "admin": Principal("dev-admin-1", "admin@dev.auralane.local", ("admin",)),
}


def _resolve(value, env, file):
    """value, else the environment variable, else the file (created with a
    random value, mode 0600, on first use), else random for this instance."""
    value = value or os.environ.get(env)
    if not value and file:
        path = Path(file)
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(secrets.token_hex(32))
            path.chmod(0o600)
        value = path.read_text().strip()
    return value or secrets.token_hex(32)


class DevAuth(AuthPort):
    def __init__(self, secret: str | None = None, key_file: str | os.PathLike | None = None,
                 password: str | None = None,
                 password_file: str | os.PathLike | None = None):
        self._key = _resolve(secret, "AURALANE_DEV_JWT_SECRET", key_file)
        self._password = _resolve(password, "AURALANE_DEV_PASSWORD", password_file)

    def login(self, username: str, password: str) -> str:
        user = next((k for k, p in SEEDED.items() if username in (k, p.email)), None)
        if user is None or not secrets.compare_digest(password.encode(), self._password.encode()):
            raise PermissionError("unknown user or wrong password")
        return self.issue(user)

    def issue(self, user: str, ttl: int = 3600) -> str:
        p = SEEDED[user]
        now = int(time.time())
        return jwt.encode({"sub": p.subject, "email": p.email, "groups": list(p.groups),
                           "iss": ISSUER, "aud": AUDIENCE, "iat": now, "exp": now + ttl},
                          self._key, algorithm="HS256")

    def readers(self) -> list[tuple[str, str]]:
        """(username, reader id) for every seeded radiologist. The reader id is
        what verify() puts in Principal.email, so assignments match sign-ins."""
        return [(k, p.email) for k, p in SEEDED.items() if "radiologist" in p.groups]

    def verify(self, token: str) -> Principal:
        c = jwt.decode(token, self._key, algorithms=["HS256"], audience=AUDIENCE,
                       issuer=ISSUER, options={"require": ["exp", "sub"]})
        return Principal(c["sub"], c.get("email", ""), tuple(c.get("groups", [])))
