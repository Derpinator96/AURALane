"""DevAuth: HS256 JWTs signed with a local key. DEVELOPMENT ONLY.

Never deploy this. It stands in for Cognito on localhost so the API can check a
bearer token and a group without an AWS account. Anyone holding the key can
mint any identity.

The key comes from the secret argument, else AURALANE_DEV_JWT_SECRET, else
key_file (created with a random key on first use), so a token printed by
`python -m core.run token` verifies in a separate `serve` process. With none of
the three, the key is random per instance.

Two seeded users, both synthetic:
    radiologist@dev.auralane.local   group radiologist
    admin@dev.auralane.local         group admin

login() accepts either seeded user (by key or email) with the development
password: AURALANE_DEV_PASSWORD if set, else "auralane-dev". It is written
here in a public repository on purpose: it guards nothing but a laptop.
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
DEV_PASSWORD = "auralane-dev"
AUDIENCE = "auralane-local"

SEEDED = {
    "radiologist": Principal("dev-radiologist-1", "radiologist@dev.auralane.local",
                             ("radiologist",)),
    "admin": Principal("dev-admin-1", "admin@dev.auralane.local", ("admin",)),
}


class DevAuth(AuthPort):
    def __init__(self, secret: str | None = None, key_file: str | os.PathLike | None = None):
        self._key = secret or os.environ.get("AURALANE_DEV_JWT_SECRET")
        if not self._key and key_file:
            path = Path(key_file)
            if not path.exists():
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(secrets.token_hex(32))
                path.chmod(0o600)
            self._key = path.read_text().strip()
        self._key = self._key or secrets.token_hex(32)

    def login(self, username: str, password: str) -> str:
        user = next((k for k, p in SEEDED.items() if username in (k, p.email)), None)
        expected = os.environ.get("AURALANE_DEV_PASSWORD", DEV_PASSWORD)
        if user is None or not secrets.compare_digest(password.encode(), expected.encode()):
            raise PermissionError("unknown user or wrong password")
        return self.issue(user)

    def issue(self, user: str, ttl: int = 3600) -> str:
        p = SEEDED[user]
        now = int(time.time())
        return jwt.encode({"sub": p.subject, "email": p.email, "groups": list(p.groups),
                           "iss": ISSUER, "aud": AUDIENCE, "iat": now, "exp": now + ttl},
                          self._key, algorithm="HS256")

    def verify(self, token: str) -> Principal:
        c = jwt.decode(token, self._key, algorithms=["HS256"], audience=AUDIENCE,
                       issuer=ISSUER, options={"require": ["exp", "sub"]})
        return Principal(c["sub"], c.get("email", ""), tuple(c.get("groups", [])))
