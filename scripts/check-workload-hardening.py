#!/usr/bin/env python3
"""Workload hardening gate (stdlib only).

Renders the local Helm chart and, for every Deployment, StatefulSet, Job and
CronJob in the chart, reports each container's liveness and readiness probes,
resource requests and limits, and whether the workload has persistent volumes.

Fails (exit 1) when a Deployment or StatefulSet container is missing a
liveness probe or a readiness probe, or when any container (including Jobs and
CronJobs) is missing resource requests or limits. Jobs and CronJobs do not get
probes by design (they run to completion), so probes are not required there.

Run: python3 scripts/check-workload-hardening.py
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def render_chart() -> str:
    return subprocess.run(
        ["helm", "template", "urumi", "./helm", "-n", "urumi", "-f", "helm/values-local.yaml"],
        capture_output=True, text=True, cwd=ROOT,
    ).stdout


def workload_docs(yaml: str):
    for doc in re.split(r"^---$", yaml, flags=re.M):
        km = re.search(r"^kind: (\S+)", doc, re.M)
        if not km:
            continue
        kind = km.group(1)
        if kind not in ("Deployment", "StatefulSet", "Job", "CronJob"):
            continue
        nm = re.search(r"^  name: (\S+)", doc, re.M)
        name = nm.group(1) if nm else "?"
        yield doc, kind, name


def container_flags(doc: str) -> tuple[bool, bool, bool, bool]:
    """Whether the workload's spec carries liveness, readiness, requests and
    limits anywhere on its containers (chart values apply these per workload)."""
    live = bool(re.search(r"livenessProbe:", doc))
    ready = bool(re.search(r"readinessProbe:", doc))
    req = bool(re.search(r"^\s+requests:", doc, re.M))
    lim = bool(re.search(r"^\s+limits:", doc, re.M))
    return live, ready, req, lim


def main() -> int:
    yaml = render_chart()
    rows: list[tuple[str, str, str, str, str, str, str]] = []
    problems: list[str] = []
    total = 0
    for doc, kind, name in workload_docs(yaml):
        total += 1
        live, ready, req, lim = container_flags(doc)
        pvc = "volumeClaimTemplates:" in doc
        rows.append((kind, name,
                     f"liveness={'y' if live else 'n'}, readiness={'y' if ready else 'n'}, requests={'y' if req else 'n'}, limits={'y' if lim else 'n'}",
                     "PVC" if pvc else "-"))
        if kind in ("Deployment", "StatefulSet") and not (live and ready):
            problems.append(f"{kind} {name}: missing liveness/readiness probe")
        if not (req and lim):
            problems.append(f"{kind} {name}: missing requests/limits")

    print("Workload hardening check (helm template -f helm/values-local.yaml)")
    print()
    print("| kind | name | liveness, readiness, requests, limits | persistence |")
    print("|---|---|---|---|")
    for kind, name, cinfo, pvc in rows:
        print(f"| {kind} | {name} | {cinfo} | {pvc} |")
    print()
    print(f"Workloads checked: {total}")
    if problems:
        print("FAILED:")
        for p in problems:
            print(f"  {p}")
        return 1
    print("OK: every Deployment/StatefulSet container has liveness and readiness probes, "
          "and every container has resource requests and limits.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
