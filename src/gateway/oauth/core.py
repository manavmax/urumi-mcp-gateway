"""OAuth 2.1 authorization server for the MCP endpoint (Phase 7, ADR-063).

MINIMAL CORRECT form of the MCP authorization spec:
  - RFC 9728 Protected Resource Metadata at /.well-known/oauth-protected-resource
  - RFC 8414 Authorization Server Metadata at /.well-known/oauth-authorization-server
    (served by the same origin the resource metadata points at)
  - RFC 7591 dynamic client registration (public clients; exact-match redirect URIs)
  - authorization code flow with PKCE S256 ONLY (plain refused)
  - RFC 8707 resource indicator binding: the authorize request MUST carry a
    resource equal to this gateway's canonical resource URI; tokens carry it and
    /mcp refuses tokens bound to another resource
  - opaque access tokens (5 min) + refresh tokens (7 days, rotating), stored as
    SHA-256 hashes; refresh reuse revokes the token family
  - tokens map to a gateway USER: permissions, rate limits and audit behave
    exactly as with API keys
  - every 401 from /mcp carries WWW-Authenticate pointing at the resource metadata

Everything is behind oauth.enabled (default false; core path unchanged).
The BROWSER part of the flow reuses the dashboard session (the user logs in
normally) and shows a consent page (oauth_consent.html) listing the client name
and the requested scope; approving POSTs back and 302s to the client.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import time
import uuid

import config
from db.models import OauthClient, OauthCode, OauthToken, User
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

CODE_TTL_SECONDS = 600
ACCESS_TTL_SECONDS = 300
REFRESH_TTL_SECONDS = 7 * 24 * 3600


class OauthError(Exception):
    def __init__(self, error: str, description: str = "", status: int = 400):
        self.error = error
        self.description = description
        self.status = status
        super().__init__(f"{error}: {description}")


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def resource_uri() -> str:
    """The canonical resource indicator for THIS gateway's MCP endpoint."""
    s = config.get_settings()
    return s.oauth_resource_uri or f"{s.public_base_url}/mcp"


def as_issuer() -> str:
    s = config.get_settings()
    return s.oauth_issuer or s.public_base_url


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def verify_pkce(challenge: str, method: str, verifier: str) -> bool:
    """S256 ONLY: BASE64URL(SHA256(verifier)) == challenge. 'plain' refused."""
    if method != "S256":
        return False
    return hmac.compare_digest(_b64url(hashlib.sha256(verifier.encode()).digest()), challenge)


def new_client_id() -> str:
    return "mcp-" + secrets.token_urlsafe(16)


def new_code() -> str:
    return secrets.token_urlsafe(32)


def new_access_token() -> str:
    return "uat_" + secrets.token_urlsafe(32)


def new_refresh_token() -> str:
    return "urt_" + secrets.token_urlsafe(32)


async def register_client(db: AsyncSession, body: dict) -> dict:
    """RFC 7591 dynamic client registration. Only what MCP clients need:
    redirect_uris (exact strings), client_name, optional scope. Public clients
    only (token_endpoint_auth_method 'none'); a confidential secret is NOT
    supported (the spec allows the server to pick)."""
    redirects = body.get("redirect_uris") or []
    if not isinstance(redirects, list) or not redirects or not all(
        isinstance(u, str) and u for u in redirects
    ):
        raise OauthError("invalid_client_metadata", "redirect_uris must be a non-empty array of strings")
    if len(redirects) > 10 or any(len(u) > 512 for u in redirects):
        raise OauthError("invalid_client_metadata", "too many or overlong redirect_uris")
    client = OauthClient(
        client_id=new_client_id(),
        redirect_uris=list(redirects),
        client_name=str(body.get("client_name") or "")[:120],
        token_endpoint_auth_method="none",
        grant_types=["authorization_code", "refresh_token"],
        scope=str(body.get("scope") or "")[:200],
    )
    db.add(client)
    await db.flush()
    return {
        "client_id": client.client_id,
        "client_secret": "",
        "client_id_issued_at": int(time.time()),
        "redirect_uris": client.redirect_uris,
        "client_name": client.client_name,
        "token_endpoint_auth_method": "none",
        "grant_types": client.grant_types,
        "response_types": ["code"],
        "scope": client.scope,
    }


async def authorize_consent(
    db: AsyncSession, *, client_id: str, redirect_uri: str, scope: str,
    resource: str, challenge: str, challenge_method: str, state: str,
) -> tuple[OauthClient, dict]:
    """Validate an authorize request BEFORE showing consent. Returns the client
    row + the echo-back parameters for the consent form."""
    if not client_id:
        raise OauthError("invalid_request", "client_id is required")
    client = (await db.execute(select(OauthClient).where(OauthClient.client_id == client_id))).scalars().first()
    if client is None:
        raise OauthError("invalid_request", "unknown client_id", status=400)
    if redirect_uri not in client.redirect_uris:  # EXACT match only
        raise OauthError("invalid_request", "redirect_uri does not exactly match a registered redirect URI")
    if resource != resource_uri():
        raise OauthError(
            "invalid_target",
            f"resource must be {resource_uri()} (RFC 8707)",
        )
    if not challenge or challenge_method != "S256":
        raise OauthError("invalid_request", "PKCE S256 code_challenge is required (plain is not accepted)")
    if len(challenge) < 43 or len(challenge) > 128:
        raise OauthError("invalid_request", "code_challenge length must be 43-128")
    return client, {
        "client_id": client_id,
        "client_name": client.client_name or client_id,
        "redirect_uri": redirect_uri,
        "scope": scope or client.scope or "mcp",
        "resource": resource,
        "challenge": challenge,
        "challenge_method": challenge_method,
        "state": state,
    }


async def approve_authorization(
    db: AsyncSession, user: User, p: dict
) -> str:
    """Create the single-use code (hashed at rest) for an approved consent."""
    code = new_code()
    db.add(OauthCode(
        code_hash=_hash(code),
        client_id=p["client_id"],
        redirect_uri=p["redirect_uri"],
        scope=p["scope"],
        resource=p["resource"],
        challenge=p["challenge"],
        challenge_method="S256",
        user_id=user.id,
        expires_at=_utc_after(CODE_TTL_SECONDS),
    ))
    return code


async def exchange_code(
    db: AsyncSession, *, code: str, client_id: str, redirect_uri: str,
    verifier: str, resource: str | None,
) -> dict:
    """Token endpoint, grant_type=authorization_code. Validates: client, exact
    redirect match, PKCE S256 verifier vs the stored challenge, single use,
    TTL, and the RFC 8707 resource binding. Returns the token response."""
    row = (await db.execute(select(OauthCode).where(OauthCode.code_hash == _hash(code)))).scalars().first()
    if row is None or row.consumed or _expired(row.expires_at):
        if row is not None and not row.consumed:
            row.consumed = True
        raise OauthError("invalid_grant", "authorization code is invalid, expired or already used", status=400)
    if row.client_id != client_id:
        raise OauthError("invalid_grant", "client mismatch", status=400)
    if row.redirect_uri != redirect_uri:  # EXACT match with the authorize request
        raise OauthError("invalid_grant", "redirect_uri mismatch", status=400)
    if not verify_pkce(row.challenge, row.challenge_method, verifier or ""):
        raise OauthError("invalid_grant", "PKCE verification failed", status=400)
    bound = row.resource
    if resource is not None and resource != bound:
        raise OauthError("invalid_target", "resource does not match the authorization", status=400)
    row.consumed = True
    return await _issue_tokens(db, client_id=client_id, user_id=row.user_id, scope=row.scope, resource=bound)


async def refresh_tokens(db: AsyncSession, *, refresh_token: str, client_id: str, resource: str | None) -> dict:
    """grant_type=refresh_token with ROTATION: the old refresh token is marked
    rotated; its reuse revokes the whole family (stolen-token detection)."""
    row = (await db.execute(select(OauthToken).where(OauthToken.token_hash == _hash(refresh_token)))).scalars().first()
    if row is None or row.kind != "refresh":
        raise OauthError("invalid_grant", "unknown refresh token", status=400)
    if row.revoked:
        raise OauthError("invalid_grant", "refresh token was revoked", status=400)
    if row.client_id != client_id:
        raise OauthError("invalid_grant", "client mismatch", status=400)
    if row.rotated:
        # reuse of a rotated token: kill the family
        fam = (await db.execute(select(OauthToken).where(OauthToken.family == row.family))).scalars().all()
        for t in fam:
            t.revoked = True
        raise OauthError("invalid_grant", "refresh token reuse detected; family revoked", status=400)
    if _expired(row.expires_at):
        raise OauthError("invalid_grant", "refresh token expired", status=400)
    if resource is not None and resource != row.resource:
        raise OauthError("invalid_target", "resource does not match the grant", status=400)
    row.rotated = True
    # rotation keeps the SAME family: reuse of ANY rotated member revokes the
    # whole chain (original + every successor)
    return await _issue_tokens(
        db, client_id=row.client_id, user_id=row.user_id, scope=row.scope,
        resource=row.resource, family=row.family,
    )


async def _issue_tokens(db: AsyncSession, *, client_id: str, user_id, scope: str, resource: str,
                        family: uuid.UUID | None = None) -> dict:
    access = new_access_token()
    refresh = new_refresh_token()
    family = family or uuid.uuid4()
    db.add(OauthToken(
        token_hash=_hash(access), kind="access", client_id=client_id, user_id=user_id,
        scope=scope, resource=resource, family=family, expires_at=_utc_after(ACCESS_TTL_SECONDS),
    ))
    db.add(OauthToken(
        token_hash=_hash(refresh), kind="refresh", client_id=client_id, user_id=user_id,
        scope=scope, resource=resource, family=family, expires_at=_utc_after(REFRESH_TTL_SECONDS),
    ))
    return {
        "access_token": access,
        "token_type": "Bearer",
        "expires_in": ACCESS_TTL_SECONDS,
        "refresh_token": refresh,
        "scope": scope,
    }


async def authenticate_bearer(db: AsyncSession, token: str) -> tuple[User, OauthToken] | None:
    """Map an access token to its user (or None). Refuses: unknown, revoked,
    rotated (access tokens are never rotated), expired, and tokens bound to a
    DIFFERENT resource (RFC 8707 audience binding)."""
    row = (await db.execute(select(OauthToken).where(OauthToken.token_hash == _hash(token)))).scalars().first()
    if row is None or row.kind != "access" or row.revoked or row.rotated or _expired(row.expires_at):
        return None
    if row.resource != resource_uri():
        return None
    user = (await db.execute(select(User).where(User.id == row.user_id))).scalars().first()
    if user is None or not user.is_active:
        return None
    return user, row


def www_authenticate_header() -> str:
    """The 401 header pointing unauthenticated MCP clients at the metadata."""
    return (
        f'Bearer resource_metadata="{resource_uri().replace("/mcp", "")}/.well-known/oauth-protected-resource"'
    )


def _utc_after(seconds: int):
    from datetime import UTC, datetime

    return datetime.now(UTC).fromtimestamp(time.time() + seconds, tz=UTC)


def _expired(dt) -> bool:
    if dt is None:
        return True
    from datetime import UTC, datetime

    dt = dt if dt.tzinfo else dt.replace(tzinfo=UTC)
    return dt <= datetime.now(UTC)


def metadata_document() -> dict:
    """RFC 8414 authorization server metadata (minimal, correct)."""
    base = as_issuer()
    return {
        "issuer": base,
        "authorization_endpoint": f"{base}/oauth/authorize",
        "token_endpoint": f"{base}/oauth/token",
        "registration_endpoint": f"{base}/oauth/register",
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code", "refresh_token"],
        "code_challenge_methods_supported": ["S256"],
        "token_endpoint_auth_methods_supported": ["none"],
        "scopes_supported": ["mcp"],
        "resource_indicators_supported": True,
    }


def protected_resource_document() -> dict:
    """RFC 9728 protected resource metadata."""
    base = as_issuer()
    return {
        "resource": resource_uri(),
        "authorization_servers": [base],
        "scopes_supported": ["mcp"],
        "bearer_methods_supported": ["header"],
        "resource_documentation": f"{base}/",
    }
