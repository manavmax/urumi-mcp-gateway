#!/usr/bin/env bash
# Build and push all 9 custom Urumi images to GHCR (multi-arch via buildx).
#
# One stranger-runnable line:
#   GHCR_OWNER=<owner> GHCR_TOKEN=<token> scripts/push-images.sh
#   GHCR_OWNER=<owner> scripts/push-images.sh            # token prompted, hidden
#   PLATFORMS=linux/amd64,linux/arm64 GHCR_OWNER=<owner> scripts/push-images.sh
#
# Required variables (also listed by `make help`):
#   GHCR_OWNER  ghcr.io account or org that owns the packages (env or $1)
#   GHCR_TOKEN  a GitHub token with write:packages (env GHCR_TOKEN, or hidden prompt;
#               fed to `docker login ghcr.io --password-stdin`, never echoed, never
#               written to a file or the shell history)
# Optional:
#   PLATFORMS   buildx platforms, default linux/amd64 (append linux/arm64 explicitly;
#               arm64 builds run under QEMU and take considerably longer)
#   GHCR_USER   login name for ghcr.io (defaults to GHCR_OWNER)
#
# Tag = <chart appVersion>-<short git SHA>, e.g. 1.0.1-a1b2c3d, computed from the
# checkout being built. Pin that tag in helm/values-prod.yaml after pushing.
#
# Security: no credential is ever hardcoded, echoed, redirected to a file or passed
# on a command line; the token travels only via stdin to `docker login`.
set -eu

OWNER="${GHCR_OWNER:?set GHCR_OWNER (ghcr.io owner, e.g. GHCR_OWNER=manavsharma make images-push)}"
GHCR_USER="${GHCR_USER:-$OWNER}"
PLATFORMS="${PLATFORMS:-linux/amd64}"

APP_VERSION=$(sed -n 's/^appVersion: *"\([^"]*\)".*/\1/p' helm/Chart.yaml)
GIT_SHA=$(git rev-parse --short HEAD)
TAG="${APP_VERSION}-${GIT_SHA}"

# Image name -> build context (all 9 custom images the chart deploys).
IMAGES="gateway:src/gateway dashboard:src/dashboard landing:src/landing woo-mcp:src/woo-mcp \
demo-mcp-time:src/demo-mcp-time demo-mcp-notes:src/demo-mcp-notes \
wordpress:src/wordpress wp-cli:src/wp-cli store-assets:store"

# Token: environment first (keeps it out of the TTY), else a hidden prompt.
# Neither path echoes the token, writes it to disk, or puts it in argv/history.
if [ -z "${GHCR_TOKEN:-}" ]; then
  printf 'GHCR token (input hidden): ' >&2
  IFS= read -rs GHCR_TOKEN
  printf '\n' >&2
fi
[ -n "$GHCR_TOKEN" ] || { echo "ERROR: empty GHCR token" >&2; exit 1; }
printf '%s' "$GHCR_TOKEN" | docker login ghcr.io --username "$GHCR_USER" --password-stdin >/dev/null
echo "logged in to ghcr.io as ${GHCR_USER} (token not echoed, not stored)"

echo "building + pushing tag ${TAG} for PLATFORMS=${PLATFORMS}"
for entry in $IMAGES; do
  name=${entry%%:*}; dir=${entry#*:}
  echo "== ${name} <- ${dir} =="
  docker buildx build \
    --platform "$PLATFORMS" \
    --file "${dir}/Dockerfile" \
    --tag "ghcr.io/${GHCR_OWNER}/${name}:${TAG}" \
    --push \
    "${dir}"
  echo "pushed ghcr.io/${GHCR_OWNER}/${name}:${TAG}"
done

echo "next: pin these tags in helm/values-prod.yaml (image.tag: ${TAG}) - never :latest"
