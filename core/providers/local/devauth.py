"""DevAuth: HS256 JWTs signed with a local key. DEVELOPMENT ONLY.

Never deploy this. It stands in for Cognito on localhost so the API can check a
bearer token and a group without an AWS account. Anyone holding the key can
mint any identity.

The key comes from AURALANE_DEV_JWT_SECRET, or is generated per instance, in
which case only that instance can verify what it issued.

Two seeded users, both synthetic:
    radiologist@dev.auralane.local   group radiologist
    admin@dev.auralane.local         group admin
"""
from __future__ import annotations

import os
import secrets
import time

import jwt      # PyJWT: jwt.encode(payload, key, algorithm=), jwt.decode(token, key, algorithms=, audience=)

from core.ports import AuthPort
from core.types import Principal

ISSUER = "auralane-devauth"
AUDIENCE = "auralane-local"

SEEDED = {
    "radiologist": Principal("dev-radiologist-1", "radiologist@dev.auralane.local",
                             ("radiologist",)),
    "admin": Principal("dev-admin-1", "admin@dev.auralane.local", ("admin",)),
}


class DevAuth(AuthPort):
    def __init__(self, secret: str | None = None):
        self._key = secret or os.environ.get("AURALANE_DEV_JWT_SECRET") or secrets.token_hex(32)

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
