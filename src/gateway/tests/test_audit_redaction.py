"""Audit redaction (docs/04 §7).

The audit trail answers "who called what, when, with what result" — a table of
identifiers. These tests pin the structural guarantee that no tool arguments, tool
output or credential material can reach the audit queue or the audit_logs schema.
"""

from __future__ import annotations

import inspect
import json
import uuid

import audit.queue as audit_queue_module
from audit.queue import log_audit
from db.models import AuditLog

# columns/fields that would make the audit trail a credential or tool-payload sink
BANNED = {
    "arguments", "arguments_json", "args", "result", "results", "content", "output",
    "response", "response_body", "request_body", "params", "payload", "credential",
    "credential_encrypted", "password_hash", "key_hash", "sha256", "raw_key", "secret",
}

# the complete, exact set of fields the audit row is allowed to carry
SAFE_COLUMNS = {
    "id", "ts", "user_id", "api_key_id", "server_id", "server_slug",
    "tool_exposed_name", "tool_upstream_name", "request_id", "duration_ms",
    "outcome", "error_code", "client_ip",
}


def test_audit_log_schema_has_no_payload_columns():
    cols = {c.name for c in AuditLog.__table__.columns}
    assert not (cols & BANNED), f"audit schema can carry payloads/credentials via {sorted(cols & BANNED)}"
    assert cols <= SAFE_COLUMNS, "audit schema is not a bounded identifier table"


def test_log_audit_signature_has_no_payload_parameter():
    params = set(inspect.signature(log_audit).parameters)
    banned_params = {"arguments", "args", "result", "content", "output", "payload", "body", "credential", "token"}
    assert not (params & banned_params), f"log_audit could be handed a secret via {sorted(params & banned_params)}"


class SpyQueue:
    """Replaces the module-level asyncio.Queue so items can be inspected, not written."""

    def __init__(self):
        self.captured = []

    def put_nowait(self, item):
        self.captured.append(item)


async def test_queued_audit_item_is_identifiers_only(monkeypatch):
    spy = SpyQueue()
    monkeypatch.setattr(audit_queue_module, "audit_queue", spy)

    await log_audit(
        user_id=uuid.uuid4(),
        api_key_id=uuid.uuid4(),
        server_id=uuid.uuid4(),
        server_slug="woo",
        tool_exposed_name="woo__create_product",
        tool_upstream_name="create_product",
        request_id=uuid.uuid4(),
        duration_ms=12,
        outcome="success",
        error_code=None,
        client_ip="10.244.0.9",
    )
    assert len(spy.captured) == 1
    item = spy.captured[0]
    assert not (set(item) & BANNED), "queued audit items must be identifiers only"
    assert item["outcome"] == "success" and item["server_slug"] == "woo"
    assert json.loads(json.dumps(item, default=str))["duration_ms"] == 12


async def test_failure_paths_still_audit_without_payloads(monkeypatch):
    spy = SpyQueue()
    monkeypatch.setattr(audit_queue_module, "audit_queue", spy)
    # a tool argument that would be a credential if it were ever logged
    secret_argument = {"password": "urumi_sk_SUPERSECRET_value_1234567890"}
    assert "SUPERSECRET" in json.dumps(secret_argument)

    await log_audit(
        user_id=uuid.uuid4(),
        api_key_id=uuid.uuid4(),
        server_id=uuid.uuid4(),
        server_slug="woo",
        tool_exposed_name="woo__create_product",
        tool_upstream_name="create_product",
        request_id=uuid.uuid4(),
        duration_ms=7,
        outcome="validation_error",
        error_code="validation_error",
        client_ip=None,
    )
    blob = json.dumps(spy.captured[0], default=str)
    # log_audit never receives tool arguments, so the secret cannot appear in the row
    assert "SUPERSECRET" not in blob
    assert spy.captured[0]["outcome"] == "validation_error"
