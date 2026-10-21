"""OAuth HTTP surface (Phase 7, ADR-063). All behind oauth.enabled.

  GET  /.well-known/oauth-protected-resource   RFC 9728 (public)
  GET  /.well-known/oauth-authorization-server RFC 8414 (public)
  POST /oauth/register                         RFC 7591 dynamic client registration
  GET  /oauth/authorize                        validates the request, renders CONSENT
                                               (requires a dashboard session: the
                                               browser part reuses the normal login)
  POST /oauth/authorize                        approves consent -> 302 code?state=
  POST /oauth/token                            code exchange (PKCE) + refresh
  POST /oauth/revoke                           revokes a token (its family for refresh)

The MCP endpoint accepts these access tokens as `Authorization: Bearer uat_...`
and maps them to users (permissions / rate limits / audit unchanged).
"""

from __future__ import annotations

import config
from auth.rbac import get_current_user_via_session, verify_csrf
from db.models import OauthToken, User
from db.session import get_db
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from oauth import core

router = APIRouter()


def _require_oauth() -> None:
    if not config.get_settings().oauth_enabled:
        from fastapi import HTTPException

        raise HTTPException(status_code=403, detail="oauth is disabled on this deployment")


def _error_redirect(redirect_uri: str, error: str, description: str, state: str) -> RedirectResponse:
    from urllib.parse import urlencode

    params = {"error": error, "error_description": description}
    if state:
        params["state"] = state
    sep = "&" if "?" in redirect_uri else "?"
    return RedirectResponse(f"{redirect_uri}{sep}{urlencode(params)}", status_code=302)


@router.get("/.well-known/oauth-protected-resource")
async def protected_resource_metadata():
    _require_oauth()
    return JSONResponse(core.protected_resource_document())


@router.get("/.well-known/oauth-authorization-server")
async def authorization_server_metadata():
    _require_oauth()
    return JSONResponse(core.metadata_document())


@router.post("/oauth/register")
async def register_client(request: Request, db: AsyncSession = Depends(get_db)):
    _require_oauth()
    body = await request.json()
    try:
        doc = await core.register_client(db, body)
    except core.OauthError as exc:
        return JSONResponse({"error": exc.error, "error_description": exc.description}, status_code=exc.status)
    await db.commit()
    return JSONResponse(doc, status_code=201)


@router.get("/oauth/authorize")
async def authorize_form(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user_via_session),
):
    """Renders the consent page (dashboard session required - the BROWSER part
    of the flow reuses the normal login). Invalid requests 302 back to the
    client with error codes where we have a redirect_uri to send them to."""
    _require_oauth()
    p = request.query_params
    try:
        _client, echo = await core.authorize_consent(
            db,
            client_id=p.get("client_id", ""),
            redirect_uri=p.get("redirect_uri", ""),
            scope=p.get("scope", ""),
            resource=p.get("resource", ""),
            challenge=p.get("code_challenge", ""),
            challenge_method=p.get("code_challenge_method", ""),
            state=p.get("state", ""),
        )
    except core.OauthError as exc:
        ru = p.get("redirect_uri")
        if ru and p.get("client_id"):
            return _error_redirect(ru, exc.error, exc.description, p.get("state", ""))
        return JSONResponse({"error": exc.error, "error_description": exc.description}, status_code=exc.status)
    html = _consent_html(
        client_name=echo["client_name"],
        scope=echo["scope"],
        resource=echo["resource"],
        hidden={
            "client_id": echo["client_id"],
            "redirect_uri": echo["redirect_uri"],
            "scope": echo["scope"],
            "resource": echo["resource"],
            "code_challenge": echo["challenge"],
            "code_challenge_method": echo["challenge_method"],
            "state": echo["state"],
        },
    )
    return HTMLResponse(html)


@router.post("/oauth/authorize")
async def authorize_submit(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user_via_session),
):
    _require_oauth()
    verify_csrf(request)
    form = await request.form()
    p = {k: str(form.get(k) or "") for k in (
        "client_id", "redirect_uri", "scope", "resource",
        "code_challenge", "code_challenge_method", "state",
    )}
    if user is None or not user.is_active:
        return JSONResponse({"error": "access_denied", "error_description": "not signed in"}, status_code=401)
    try:
        _client, echo = await core.authorize_consent(
            db,
            client_id=p["client_id"],
            redirect_uri=p["redirect_uri"],
            scope=p["scope"],
            resource=p["resource"],
            challenge=p["code_challenge"],
            challenge_method=p["code_challenge_method"] or "S256",
            state=p["state"],
        )
    except core.OauthError as exc:
        return _error_redirect(p["redirect_uri"], exc.error, exc.description, p["state"])
    if str(form.get("decision") or "") != "approve":
        return _error_redirect(echo["redirect_uri"], "access_denied", "the user denied the request", echo["state"])
    code = await core.approve_authorization(db, user, echo)
    await db.commit()
    from urllib.parse import urlencode

    params = {"code": code}
    if echo["state"]:
        params["state"] = echo["state"]
    sep = "&" if "?" in echo["redirect_uri"] else "?"
    return RedirectResponse(f"{echo['redirect_uri']}{sep}{urlencode(params)}", status_code=302)


@router.post("/oauth/token")
async def token_endpoint(request: Request, db: AsyncSession = Depends(get_db)):
    _require_oauth()
    form = await request.form()
    grant_type = str(form.get("grant_type") or "")
    client_id = str(form.get("client_id") or "")
    try:
        if grant_type == "authorization_code":
            doc = await core.exchange_code(
                db,
                code=str(form.get("code") or ""),
                client_id=client_id,
                redirect_uri=str(form.get("redirect_uri") or ""),
                verifier=str(form.get("code_verifier") or ""),
                resource=form.get("resource") and str(form.get("resource")),
            )
        elif grant_type == "refresh_token":
            doc = await core.refresh_tokens(
                db,
                refresh_token=str(form.get("refresh_token") or ""),
                client_id=client_id,
                resource=form.get("resource") and str(form.get("resource")),
            )
        else:
            return JSONResponse(
                {"error": "unsupported_grant_type", "error_description": "use authorization_code or refresh_token"},
                status_code=400,
            )
    except core.OauthError as exc:
        # a rejected grant may still hold DB state (the refresh-reuse path
        # revokes the whole family BEFORE raising): commit so the revocation
        # survives the error response
        await db.commit()
        return JSONResponse({"error": exc.error, "error_description": exc.description}, status_code=exc.status)
    await db.commit()
    return JSONResponse(doc, headers={"Cache-Control": "no-store"})


@router.post("/oauth/revoke")
async def revoke_endpoint(request: Request, db: AsyncSession = Depends(get_db)):
    """RFC 7009-style revocation: token_type_hint may say refresh_token. A
    refresh token revokes its whole family; an access token only itself."""
    _require_oauth()
    form = await request.form()
    token = str(form.get("token") or "")
    hint = str(form.get("token_type_hint") or "")
    if not token:
        return JSONResponse({"error": "invalid_request", "error_description": "token is required"}, status_code=400)
    import hashlib

    from sqlalchemy import update

    th = hashlib.sha256(token.encode()).hexdigest()
    row = (await db.execute(select(OauthToken).where(OauthToken.token_hash == th))).scalars().first()
    if row is not None:
        if row.kind == "refresh" or hint == "refresh_token":
            await db.execute(
                update(OauthToken).where(OauthToken.family == row.family).values(revoked=True)
            )
        else:
            row.revoked = True
        await db.commit()
    # RFC 7009: 200 even when the token is unknown (no oracle)
    return JSONResponse({})


def _consent_html(*, client_name: str, scope: str, resource: str, hidden: dict) -> str:
    inputs = "".join(
        f'<input type="hidden" name="{k}" value="{_esc(v)}" />' for k, v in hidden.items()
    )
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Authorize { _esc(client_name) } — Urumi gateway</title>
<meta name="viewport" content="width=device-width, initial-scale=1"></head>
<body style="font-family: system-ui, sans-serif; max-width: 34rem; margin: 12vh auto; padding: 0 1rem;">
<h1>Authorize access</h1>
<p><strong>{ _esc(client_name) }</strong> is asking to use the Urumi MCP gateway <strong>as your user</strong>.</p>
<ul>
  <li>Access scope: <code>{ _esc(scope or "mcp") }</code></li>
  <li>Resource: <code>{ _esc(resource) }</code></li>
  <li>It will be able to call the tools you can call (stores you own, allowed upstreams), and every call is audited under your account.</li>
</ul>
<form method="post" action="/oauth/authorize">
  {inputs}
  <button type="submit" name="decision" value="approve">Approve</button>
  <button type="submit" name="decision" value="deny">Deny</button>
</form>
<p class="small muted">Denying returns an access_denied error to the client. You can revoke access later from the dashboard.</p>
</body></html>"""


def _esc(s: str) -> str:
    """Minimal HTML escaping for the consent template (attribute-safe)."""
    return (
        (s or "")
        .replace(chr(38), chr(38) + "amp;")
        .replace(chr(60), chr(38) + "lt;")
        .replace(chr(62), chr(38) + "gt;")
        .replace(chr(34), chr(38) + "quot;")
    )
