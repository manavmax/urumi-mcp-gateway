#!/usr/bin/env bash
# Create or update the LLM key Secret used by the gateway chat assistant.
#
# The key is read from a HIDDEN prompt (never from a repo file) and piped into
# kubectl via stdin so it never appears in argv, shell history, or any file.
#
# Usage:
#   scripts/create-llm-secret.sh [namespace] [secret-name]
# (defaults: namespace urumi, secret gateway-llm; set gateway.llm.existingSecret
#  in values to point at a different secret name)
set -eu

NS=${1:-urumi}
SECRET=${2:-gateway-llm}

printf 'LLM API key for Secret %s/%s (input hidden): ' "$NS" "$SECRET" >&2
IFS= read -rs KEY
printf '\n' >&2
[ -n "$KEY" ] || { echo "ERROR: empty key - aborting (no secret written)" >&2; exit 1; }

# Key travels only over stdin: never argv, never a file, never shell history.
printf '%s' "$KEY" | kubectl create secret generic "$SECRET" -n "$NS" \
  --from-file=OPENAI_API_KEY=/dev/stdin --dry-run=client -o yaml | kubectl apply -f -
KEY=unset
echo "Secret ${NS}/${SECRET} updated (key not echoed). Restarting gateway so it picks up the change..."
kubectl rollout restart deployment/urumi-gateway -n "$NS" >/dev/null
kubectl rollout status deployment/urumi-gateway -n "$NS" --timeout=180s
echo "gateway restarted with the new key."
echo "To verify the chat path: make verify-llm (runs scripts/verify-llm.py in the pod)."
