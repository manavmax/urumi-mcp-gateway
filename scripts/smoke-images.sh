#!/usr/bin/env bash
# Host-platform build + per-image container smoke test for all 8 custom images.
# Proves the build contexts and Dockerfiles work WITHOUT pushing anything.
# Used by `make smoke-images`; push-images.sh does the multi-arch GHCR push.
set -eu

APP_VERSION=$(sed -n 's/^appVersion: *"\([^"]*\)".*/\1/p' helm/Chart.yaml)
GIT_SHA=$(git rev-parse --short HEAD)
TAG="${APP_VERSION}-${GIT_SHA}"

IMAGES="gateway:src/gateway dashboard:src/dashboard woo-mcp:src/woo-mcp \
demo-mcp-time:src/demo-mcp-time demo-mcp-notes:src/demo-mcp-notes \
wordpress:src/wordpress wp-cli:src/wp-cli store-assets:store"

PORT=18080   # one host port reused per image (only one container up at a time)
FAIL=0

stop_smoke() { docker rm -f "urumi-smoke-$1" >/dev/null 2>&1 || true; }

echo "smoke-testing tag ${TAG} (host platform)"
for entry in $IMAGES; do
  name=${entry%%:*}; dir=${entry#*:}
  echo "== ${name} <- ${dir} =="
  if ! docker build -q -t "urumi/${name}:${TAG}" "${dir}" >/dev/null; then
    echo "  BUILD FAILED: ${name}"; FAIL=1; continue
  fi

  # Per-image smoke check.
  case "$name" in
    gateway)
      docker run -d --rm --name "urumi-smoke-${name}" -p "127.0.0.1:${PORT}:8000" "urumi/${name}:${TAG}" >/dev/null
      sleep 3
      if curl -sf "http://127.0.0.1:${PORT}/healthz" | grep -q status; then echo "  gateway /healthz OK"; else echo "  gateway /healthz FAILED"; FAIL=1; fi ;;
    dashboard)
      docker run -d --rm --name "urumi-smoke-${name}" -p "127.0.0.1:${PORT}:8080" "urumi/${name}:${TAG}" >/dev/null; sleep 2
      [ "$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:${PORT}/")" = 200 ] && echo "  dashboard / -> 200" || { echo "  dashboard FAILED"; FAIL=1; } ;;
    woo-mcp|demo-mcp-time)
      docker run -d --rm --name "urumi-smoke-${name}" -p "127.0.0.1:${PORT}:8000" "urumi/${name}:${TAG}" >/dev/null; sleep 2
      [ "$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:${PORT}/")" = 200 ] && echo "  ${name} / -> 200" || { echo "  ${name} FAILED"; FAIL=1; } ;;
    demo-mcp-notes)
      docker run -d --rm --name "urumi-smoke-${name}" -e NOTES_API_TOKEN=smoke -p "127.0.0.1:${PORT}:8000" "urumi/${name}:${TAG}" >/dev/null; sleep 2
      if [ "$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:${PORT}/")" = 200 ]; then echo "  demo-notes / -> 200"; else echo "  demo-notes FAILED"; FAIL=1; fi ;;
    wordpress)
      # apache2-foreground directly: the official entrypoint blocks on a DB wait
      docker run -d --rm --name "urumi-smoke-${name}" -p "127.0.0.1:${PORT}:8080" "urumi/${name}:${TAG}" apache2-foreground >/dev/null; sleep 2
      [ "$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:${PORT}/readme.html")" = 200 ] && echo "  wordpress /readme.html -> 200 (apache 8080)" || { echo "  wordpress FAILED"; FAIL=1; } ;;
    wp-cli)
      docker run --rm "urumi/${name}:${TAG}" sh -c 'wp --allow-root --version && test -f /var/www/wordpress-core/wp-load.php && test -f /var/www/woocommerce.zip' && echo "  wp-cli ok (baked core + woo zip present)" || { echo "  wp-cli FAILED"; FAIL=1; } ;;
    store-assets)
      docker run --rm "urumi/${name}:${TAG}" sh -c 'test -f /assets/products.json && test -d /assets/images && test -d /assets/themes/urumi-store && echo ok' && echo "  store-assets contents ok" || { echo "  store-assets FAILED"; FAIL=1; } ;;
  esac

  # Secret-like file scan inside the image (expect none). System CA bundles are
  # legitimate (the OS trust store and Python's certifi cacert.pem), so the scan
  # targets the app-relevant dirs where a mistakenly-baked secret would land and
  # drops the standard CA bundle name.
  HITS=$(docker run --rm --entrypoint sh "urumi/${name}:${TAG}" -c \
    "find /app /var/www /assets /home /root /tmp /usr/local/bin /usr/local/lib/python3.12/site-packages -name '.env' -o -name '.env.*' -o -name '*.pem' -o -name '*.key' -o -name 'kubeconfig' -o -name 'id_rsa*' -o -name '*.p12' 2>/dev/null | grep -v 'cacert.pem' | head -5" 2>/dev/null || true)
  if [ -n "$HITS" ]; then echo "  SECRET-LIKE FILES FOUND: $HITS"; FAIL=1; else echo "  no secret-like files in image"; fi

  stop_smoke "${name}"
done

if [ "$FAIL" = 0 ]; then echo "ALL IMAGE SMOKE TESTS PASSED (tag ${TAG})"; else echo "SMOKE TESTS FAILED"; exit 1; fi
