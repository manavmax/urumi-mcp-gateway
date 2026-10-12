"""Seeded internal upstreams are authoritative: their credential is re-applied from the
environment/Secret, encrypted with the CURRENT Fernet key, on every gateway start
(registry/crud.resync_internal_credentials; docs/DECISIONS.md ADR-026).

The failure mode pinned here is exactly the 2026-10-12 incident: an accidental
`kubectl apply` of `helm template` output regenerated FERNET_KEY, so the stored notes
credential stopped decrypting and every notes__ call failed until something re-encrypted
it. The contract: re-encrypt when decryption fails or the Secret rotated, leave a
matching credential byte-for-byte unchanged (no pointless churn), and never touch a
server an admin added.
"""

from __future__ import annotations

import uuid

import pytest
from cryptography.fernet import Fernet

from db.models import Server
from registry.crud import resync_internal_credentials
from registry.crypto import decrypt, encrypt
from tests.conftest import FakeDB


def make_server_row(*, slug: str, auth_type: str = "none", credential_encrypted: bytes | None = None) -> Server:
    """A real Server row (the resync touches auth_type/credential_encrypted/updated_at)."""
    return Server(
        id=uuid.uuid4(),
        slug=slug,
        url=f"http://urumi-{slug}:8000/mcp",
        auth_type=auth_type,
        header_name=None,
        credential_encrypted=credential_encrypted,
        enabled=True,
        status="Unreachable",
        last_error="failed to decrypt credential (key mismatch)",
        timeout_ms=10000,
    )


@pytest.mark.asyncio
async def test_credential_is_reencrypted_when_decrypt_fails(monkeypatch):
    """The stored value was encrypted under a DIFFERENT Fernet key: re-encrypt."""
    monkeypatch.setenv("NOTES_API_TOKEN", "secret-token")
    foreign = Fernet(Fernet.generate_key()).encrypt(b"token-encrypted-under-the-old-key")
    srv = make_server_row(slug="notes", auth_type="bearer", credential_encrypted=foreign)
    db = FakeDB(servers=[srv])

    resynced = await resync_internal_credentials(db)

    assert resynced == ["notes"]
    assert srv.credential_encrypted != foreign  # a fresh ciphertext was written
    assert decrypt(srv.credential_encrypted) == "secret-token"
    assert srv.auth_type == "bearer"


@pytest.mark.asyncio
async def test_credential_is_unchanged_when_it_already_matches(monkeypatch):
    """Stored value decrypts to the Secret's token under the current key: byte-identical."""
    monkeypatch.setenv("NOTES_API_TOKEN", "secret-token")
    stored = encrypt("secret-token")  # same key the process would use
    srv = make_server_row(slug="notes", auth_type="bearer", credential_encrypted=stored)
    db = FakeDB(servers=[srv])

    resynced = await resync_internal_credentials(db)

    assert resynced == []
    assert srv.credential_encrypted == stored  # no rewrite on every start
    assert decrypt(srv.credential_encrypted) == "secret-token"


@pytest.mark.asyncio
async def test_admin_added_servers_are_untouched(monkeypatch):
    """Only the seeded slugs (woo/time/notes) are managed; an admin's server keeps its credential."""
    monkeypatch.setenv("NOTES_API_TOKEN", "secret-token")
    foreign = Fernet(Fernet.generate_key()).encrypt(b"admin-owned-token")
    custom = make_server_row(slug="custom", auth_type="bearer", credential_encrypted=foreign)
    db = FakeDB(servers=[custom])

    resynced = await resync_internal_credentials(db)

    assert resynced == []
    assert custom.credential_encrypted == foreign  # untouched, even though undecryptable
    assert custom.auth_type == "bearer"


@pytest.mark.asyncio
async def test_rotated_secret_replaces_a_decryptable_credential(monkeypatch):
    """Same key, new Secret value: the stored credential is replaced, not left stale."""
    monkeypatch.setenv("NOTES_API_TOKEN", "new-token")
    stored = encrypt("old-token")
    srv = make_server_row(slug="notes", auth_type="bearer", credential_encrypted=stored)
    db = FakeDB(servers=[srv])

    resynced = await resync_internal_credentials(db)

    assert resynced == ["notes"]
    assert srv.credential_encrypted != stored
    assert decrypt(srv.credential_encrypted) == "new-token"


@pytest.mark.asyncio
async def test_servers_without_auth_are_left_alone(monkeypatch):
    """woo/time take no auth: there is no Secret value to enforce, so nothing is written."""
    monkeypatch.setenv("NOTES_API_TOKEN", "secret-token")
    woo = make_server_row(slug="woo")
    time_srv = make_server_row(slug="time")
    db = FakeDB(servers=[woo, time_srv])

    resynced = await resync_internal_credentials(db)

    assert resynced == []
    assert woo.credential_encrypted is None and time_srv.credential_encrypted is None


@pytest.mark.asyncio
async def test_missing_notes_token_leaves_the_stored_credential_alone(monkeypatch):
    """No token in the environment: there is nothing authoritative to enforce."""
    monkeypatch.delenv("NOTES_API_TOKEN", raising=False)
    stored = encrypt("old-token")
    srv = make_server_row(slug="notes", auth_type="bearer", credential_encrypted=stored)
    db = FakeDB(servers=[srv])

    resynced = await resync_internal_credentials(db)

    assert resynced == []
    assert srv.credential_encrypted == stored
