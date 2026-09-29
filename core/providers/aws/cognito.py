"""CognitoAuth: AuthPort on an Amazon Cognito user pool.

Groups radiologist and admin, created by the stack. login uses the
USER_PASSWORD_AUTH flow and returns the ID token; verify checks that token's
RS256 signature against the pool's JWKS, its issuer, audience (the app
client), expiry and token_use, then maps the claims onto the same Principal
shape DevAuth returns:

    subject = sub
    email   = email, or cognito:username when the token carries no email claim
    groups  = cognito:groups, as a tuple

core/api.py is unchanged; its group checks and the 403s in both directions
read Principal.groups exactly as before.

The JWKS is fetched once from the pool's well-known URL and cached by
PyJWKClient. Tests pass jwks= directly, so no network call is made.
"""
from __future__ import annotations

import jwt      # PyJWT: PyJWKClient(uri), PyJWK(dict), jwt.decode(token, key, algorithms=, audience=, issuer=)

from core.ports import AuthPort
from core.providers.aws import session as shared
from core.providers.aws.config import REGION
from core.types import Principal


class CognitoAuth(AuthPort):
    def __init__(self, user_pool_id: str, client_id: str, region: str = REGION,
                 jwks: dict | None = None, client=None):
        self.pool, self.client_id, self.region = user_pool_id, client_id, region
        self.issuer = f"https://cognito-idp.{region}.amazonaws.com/{user_pool_id}"
        self.idp = client or shared.client("cognito-idp", region)
        self._keys = ({k["kid"]: jwt.PyJWK(k) for k in jwks["keys"]} if jwks else None)
        self._jwk_client = None

    def login(self, username: str, password: str) -> str:
        try:
            r = self.idp.initiate_auth(ClientId=self.client_id, AuthFlow="USER_PASSWORD_AUTH",
                                       AuthParameters={"USERNAME": username, "PASSWORD": password})
        except (self.idp.exceptions.NotAuthorizedException,
                self.idp.exceptions.UserNotFoundException) as e:
            raise PermissionError("unknown user or wrong password") from e
        if "AuthenticationResult" not in r:
            # e.g. NEW_PASSWORD_REQUIRED for a user created without a permanent password.
            raise PermissionError(f"sign-in needs the {r.get('ChallengeName')} challenge completed "
                                  f"first; set a permanent password for this user")
        return r["AuthenticationResult"]["IdToken"]

    def _key(self, token: str):
        if self._keys is not None:
            kid = jwt.get_unverified_header(token).get("kid")
            if kid not in self._keys:
                raise jwt.InvalidTokenError(f"unknown signing key {kid!r}")
            return self._keys[kid].key
        if self._jwk_client is None:
            self._jwk_client = jwt.PyJWKClient(f"{self.issuer}/.well-known/jwks.json")
        return self._jwk_client.get_signing_key_from_jwt(token).key

    def verify(self, token: str) -> Principal:
        c = jwt.decode(token, self._key(token), algorithms=["RS256"], audience=self.client_id,
                       issuer=self.issuer, options={"require": ["exp", "sub", "iss", "aud"]})
        if c.get("token_use") != "id":
            raise jwt.InvalidTokenError(f"expected an ID token, got token_use={c.get('token_use')!r}")
        return Principal(c["sub"], c.get("email") or c.get("cognito:username", ""),
                         tuple(c.get("cognito:groups", [])))

    # -- access requests (core/api.py /api/access-requests) --------------------
    # A requester signs up with their own password through Cognito's SignUp:
    # the password goes to Cognito and nowhere else. The account is unconfirmed
    # and in no group, so it can neither sign in nor reach any route until a
    # super admin approves it. Rejecting deletes it.
    def request_access(self, username: str, email: str, password: str) -> None:
        try:
            self.idp.sign_up(ClientId=self.client_id, Username=username, Password=password,
                             UserAttributes=[{"Name": "email", "Value": email}])
        except (self.idp.exceptions.UsernameExistsException,
                self.idp.exceptions.InvalidPasswordException,
                self.idp.exceptions.InvalidParameterException) as e:
            raise ValueError(e.response["Error"]["Message"]) from e

    def approve(self, username: str, group: str) -> None:
        self.idp.admin_confirm_sign_up(UserPoolId=self.pool, Username=username)
        self.idp.admin_add_user_to_group(UserPoolId=self.pool, Username=username, GroupName=group)

    def readers(self) -> list[tuple[str, str]]:
        """(username, reader id) for every user in the radiologist group. The
        reader id is the email attribute, else the username: the same choice
        verify() makes for Principal.email."""
        out = []
        for page in self.idp.get_paginator("list_users_in_group").paginate(
                UserPoolId=self.pool, GroupName="radiologist"):
            for u in page["Users"]:
                attrs = {a["Name"]: a["Value"] for a in u.get("Attributes", [])}
                out.append((u["Username"], attrs.get("email") or u["Username"]))
        return out

    def reject(self, username: str) -> None:
        self.idp.admin_delete_user(UserPoolId=self.pool, Username=username)
