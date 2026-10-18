"""Safety tests for scripts/demo-reset.sh (docs/DECISIONS.md ADR-032).

The demo reset is destructive, so two properties must hold without a cluster:

1. its DEFAULT mode is a dry run - it only reads (kubectl get / config / exec) and
   prints what would change; no deploy/rollout/delete command is ever issued;
2. the guard REFUSES to run against anything that is not the local kind cluster in
   the `urumi` namespace (context name, loopback API server, namespace).

Both are proven with a stubbed `kubectl` on PATH: the real script runs end to end,
the pods and the in-pod workers are canned, and every kubectl invocation is logged.
"""

from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "scripts" / "demo-reset.sh"

# A minimal kubectl: logs the subcommand level of every call (never the script text
# that `kubectl exec` carries), answers just enough for a healthy local kind cluster,
# and returns canned worker output so the orchestrator runs to completion offline.
STUB_KUBECTL = r"""#!/usr/bin/env bash
echo "kubectl ${1} ${2} ${3} ${4}" >> "$STUB_LOG"
case "${1} ${2}" in
  "config current-context") echo "${STUB_CONTEXT:-kind-urumi}" ;;
  "config view") echo "https://127.0.0.1:41273" ;;
esac
case "$*" in
  *"-l app=gateway"*) echo "urumi-gateway-stub-1" ;;
  *"-l app=woo-mcp"*) echo "urumi-woo-mcp-stub-1" ;;
  *"-l app=wordpress"*) echo "urumi-wordpress-stub-1" ;;
  exec*)
    # the exec'd container decides which worker this is (-c woo-mcp vs -c gateway)
    worker=gateway
    case "$*" in *"-c woo-mcp"*) worker=woo ;; esac
    echo "exec-worker: $worker" >> "$STUB_LOG"
    case "$*" in
      *" --dry-run"*) echo "exec-flags: --dry-run" >> "$STUB_LOG" ;;
      *" --reset"*)   echo "exec-flags: --reset" >> "$STUB_LOG" ;;
      *" --verify"*)  echo "exec-flags: --verify" >> "$STUB_LOG" ;;
    esac
    if [ "$worker" = "woo" ]; then
      cat <<'OUT'
== WooCommerce (stubbed) ==
  KEEP    product #10 'Urumi Classic Tee' sku=URUMI-TEE-001
  DELETE  product #55 'Gemini Verify 1786ba' sku=(none)
DRY RUN: no WooCommerce object was changed.
SUMMARY_JSON {"dry_run":true,"products_total":2,"products_kept":[{"id":10,"name":"Urumi Classic Tee","sku":"URUMI-TEE-001"}],"products_planned":1,"products_deleted":0,"products_already_gone":0,"orders_total":8,"orders_planned":8,"orders_deleted":0,"orders_already_gone":0,"failures":0}
OUT
    else
      cat <<'OUT'
== Gateway (stubbed) ==
audit_logs: 189 rows -> would be TRUNCATEd
DRY RUN: nothing was changed.
SUMMARY_JSON {"mode":"dry-run","audit_rows_planned":189,"users_planned":["member@urumi.local"],"member_keys_planned":3,"admin_keys_kept":2,"admins_kept":["admin@urumi.local"],"servers":[{"slug":"notes","status":"Connected","enabled":true}],"extra_servers":[],"notes_count":3}
OUT
    fi
    ;;
esac
exit 0
"""


def write_stub(tmp_path: Path) -> Path:
    """Install the stubbed kubectl first on PATH; return the directory holding it."""
    binary = tmp_path / "bin"
    binary.mkdir(parents=True, exist_ok=True)
    stub = binary / "kubectl"
    stub.write_text(STUB_KUBECTL)
    stub.chmod(stub.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return binary


def run_script(tmp_path: Path, *, context: str = "kind-urumi", namespace: str = "urumi", confirm: str | None = None) -> subprocess.CompletedProcess:
    binary = write_stub(tmp_path)
    log = tmp_path / "kubectl.log"
    log.write_text("")
    env = dict(os.environ)
    env["PATH"] = f"{binary}{os.pathsep}{env.get('PATH', '')}"
    env["STUB_LOG"] = str(log)
    env["STUB_CONTEXT"] = context
    env["NAMESPACE"] = namespace
    env.pop("CONFIRM", None)
    if confirm is not None:
        env["CONFIRM"] = confirm
    return subprocess.run(
        [str(SCRIPT)],
        check=False,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )


def log_lines(tmp_path: Path) -> list[str]:
    return [line for line in (tmp_path / "kubectl.log").read_text().splitlines() if line.strip()]


def kubectl_calls(tmp_path: Path) -> list[str]:
    return [line for line in log_lines(tmp_path) if line.startswith("kubectl ")]


def test_demo_reset_defaults_to_dry_run(tmp_path: Path) -> None:
    """No CONFIRM=yes: the reset plans, reads and prints - it deletes nothing."""
    assert SCRIPT.exists(), "scripts/demo-reset.sh is missing"
    assert os.access(SCRIPT, os.X_OK), "scripts/demo-reset.sh must stay executable"

    proc = run_script(tmp_path)
    out = proc.stdout + proc.stderr
    assert proc.returncode == 0, out
    assert "DRY RUN" in out, out
    assert "nothing was deleted" in out, out

    calls = kubectl_calls(tmp_path)
    # only read-only kubectl verbs: get / config / exec (the two in-pod workers)
    assert calls, out
    for call in calls:
        assert call.startswith(("kubectl get ", "kubectl exec ", "kubectl config ")), call
    # the deploy/rollout/delete/Secret/PVC/helm surface must never be touched
    for forbidden in ("rollout", "delete", "apply", "patch", "scale", "helm", "replace", "edit"):
        assert not any(f" {forbidden} " in f" {call} " for call in calls), forbidden

    joined = "\n".join(log_lines(tmp_path))
    assert "exec-worker: woo" in joined, joined
    assert "exec-worker: gateway" in joined, joined
    assert joined.count("exec-flags: --dry-run") == 2, joined
    # the plan must actually be shown, including what would be kept
    assert "KEEP" in out and "DELETE" in out, out
    assert "Urumi Classic Tee" in out, out
    assert "demo-reset summary" in out, out
    assert "kept product" in out, out


def test_demo_reset_guard_refuses_non_local_context(tmp_path: Path) -> None:
    """A context that is not a local kind cluster is refused before anything runs."""
    proc = run_script(tmp_path, context="gke_urumi-prod")
    out = proc.stdout + proc.stderr
    assert proc.returncode == 2, out
    assert "REFUSING to run" in out, out
    assert "kind" in out, out
    # nothing but the context lookup may have been attempted
    for call in kubectl_calls(tmp_path):
        assert call.startswith("kubectl config "), call
    assert not any("exec" in call for call in kubectl_calls(tmp_path))

    # a kind context in the WRONG namespace is refused too (namespace is part of the guard)
    proc = run_script(tmp_path, context="kind-urumi", namespace="default")
    out = proc.stdout + proc.stderr
    assert proc.returncode == 2, out
    assert "REFUSING to run" in out and "urumi" in out, out
    for call in kubectl_calls(tmp_path):
        assert call.startswith("kubectl config "), call

    # --check-only reports the guard verdict without resolving pods or exec'ing workers
    binary = write_stub(tmp_path)
    (tmp_path / "kubectl.log").write_text("")
    env = dict(os.environ)
    env["PATH"] = f"{binary}{os.pathsep}{env.get('PATH', '')}"
    env["STUB_LOG"] = str(tmp_path / "kubectl.log")
    env["STUB_CONTEXT"] = "kind-urumi"
    env["NAMESPACE"] = "urumi"
    env.pop("CONFIRM", None)
    proc = subprocess.run(
        [str(SCRIPT), "--check-only"],
        check=False,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    out = proc.stdout + proc.stderr
    assert proc.returncode == 0, out
    assert "guard OK" in out, out
    assert not any("exec" in call for call in kubectl_calls(tmp_path))
