"""RBAC + CSRF 403 contract (docs/04 §4.2, §7).

Dashboard mutations require an admin session AND a CSRF header that matches the one bound
into the signed session cookie. These tests pin the 403 paths without a database.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from auth.rbac import require_admin, require_member, verify_csrf
from auth.session import create_session_cookie, verify_session_cookie
from tests.conftest import make_user


def test_require_admin_rejects_member_with_403():
    member = make_user(role="member")
    with pytest.raises(HTTPException) as ei:
        require_admin(member)
    assert ei.value.status_code == 403 and ei.value.detail == "admin required"


def test_require_admin_allows_admin():
    admin = make_user(role="admin")
    assert require_admin(admin) is admin


def test_require_member_allows_both_roles_rejects_others():
    assert require_member(make_user(role="member")).role == "member"
    assert require_member(make_user(role="admin")).role == "admin"
    with pytest.raises(HTTPException) as ei:
        require_member(make_user(role="ghost"))
    assert ei.value.status_code == 403


def _fake_request(*, session_csrf=None, header_token=None):
    headers = {}
    if header_token is not None:
        headers["x-csrf-token"] = header_token
    return SimpleNamespace(
        state=SimpleNamespace(session_csrf=session_csrf),
        headers=headers,
        cookies={},
    )


def test_csrf_accepts_only_a_matching_header():
    verify_csrf(_fake_request(session_csrf="tok", header_token="tok"))  # must not raise


def test_csrf_rejects_missing_or_mismatched_header_with_403():
    for req in [
        _fake_request(session_csrf="tok", header_token=None),  # no header
        _fake_request(session_csrf="tok", header_token="wrong"),  # wrong header
    ]:
        with pytest.raises(HTTPException) as ei:
            verify_csrf(req)
        assert ei.value.status_code == 403 and ei.value.detail == "csrf validation failed"


def test_session_cookie_roundtrip_binds_uid_and_csrf():
    uid = uuid.uuid4()
    token, csrf = create_session_cookie(uid)
    data = verify_session_cookie(token)
    assert data is not None
    assert data["uid"] == str(uid) and data["csrf"] == csrf
    # tampered / empty cookies must fail closed
    assert verify_session_cookie(token + "x") is None
    assert verify_session_cookie("") is None
