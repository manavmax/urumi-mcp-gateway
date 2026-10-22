"""Security headers shared by the gateway (ADR-046).

main.py applies these to every response (setdefault, so a route can override a
header for a specific response - the OAuth consent page does exactly that to
allow its own inline <style> block via a style-src hash, RC fix: the consent
page used to render unstyled because the gateway CSP blocked its own CSS).
"""

from __future__ import annotations

# Hardening (ADR-046): security headers on every gateway response. The API serves
# JSON only, so the CSP is a defence-in-depth cap on what a response COULD render
# if a content-type ever went wrong: self-only scripts/styles/connects, no
# framing, no inline anything. The dashboard's nginx sets the same policy for the
# SPA (src/dashboard/nginx.conf).
SECURITY_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'self'; script-src 'self'; style-src 'self'; "
        "img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; "
        "base-uri 'self'; form-action 'self'"
    ),
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "X-Frame-Options": "DENY",
    # Deliberately empty value (the spec allows an empty policy = all features
    # denied by default on browsers that honour it).
    "Permissions-Policy": "",
}
