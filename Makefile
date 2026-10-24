.PHONY: kind-up kind-down ingress lint chart-parity template helm-local helm-prod helm-prod-first rotate-secrets clean logs ps port-forward verify-store wp-logs verify-cod woo-mcp-image verify-mcp demo-time-image demo-notes-image demo-images store-assets-image verify-demo admin-password gateway-admin-password gateway-image dashboard-image landing-image wordpress-image wp-cli-image verify-gateway verify-dashboard verify-llm deploy test demo-reset images-push images-pull images-push smoke-images help upgrade rollback

NAMESPACE ?= urumi
RELEASE   ?= urumi
CONTEXT   ?= kind-urumi

# Docker context for the LOCAL kind build/load targets below: on this machine the
# kind node container (urumi-control-plane) lives under colima, not the default
# context, so builds/loads for kind must talk to colima while registry pushes
# (images-push -> scripts/push-images.sh) go through the default context.
# Override with DOCKER_CONTEXT=<name> when kind runs elsewhere.
DOCKER_CONTEXT ?= colima
DOCKER = docker --context $(DOCKER_CONTEXT)

# helm 4 renamed --atomic to --rollback-on-failure (the old spelling still works
# there but prints a deprecation warning; helm 3 only has --atomic). Pick the
# spelling the INSTALLED helm understands so both versions keep working.
HELM_MAJOR ?= $(shell helm version --short 2>/dev/null | sed -E 's/^v([0-9]+).*/\1/')
HELM_ROLLBACK ?= $(if $(filter 4,$(HELM_MAJOR)),--rollback-on-failure,--atomic)

# Admin credentials: the USER comes from values, the PASSWORD only ever comes from the
# Secret (ADR-019). ADMIN_SECRET_NAME lets `existingAdminSecret` be honoured by make.
ADMIN_SECRET_NAME ?= $(shell helm get values $(RELEASE) -n $(NAMESPACE) -o json 2>/dev/null | grep -o '"existingAdminSecret":"[^"]*"' | cut -d'"' -f4)
WP_ADMIN_USER ?= $(shell [ -n "$$(helm get values $(RELEASE) -n $(NAMESPACE) -o json 2>/dev/null | grep -o '"adminUser":"[^"]*"' | cut -d'"' -f4)" ] && helm get values $(RELEASE) -n $(NAMESPACE) -o json 2>/dev/null | grep -o '"adminUser":"[^"]*"' | cut -d'"' -f4 || grep -o 'adminUser: .*' helm/values.yaml | head -n1 | cut -d' ' -f2)

kind-up:
	kind create cluster --name urumi --config kind-config.yaml
	kubectl cluster-info --context kind-urumi

kind-down:
	kind delete cluster --name urumi

ingress:
	kubectl apply -f https://raw.githubusercontent.com/kubernetes/ingress-nginx/main/deploy/static/provider/kind/deploy.yaml
	kubectl wait --namespace ingress-nginx --for=condition=ready pod --selector=app.kubernetes.io/component=controller --timeout=180s

# Chart lint (both value files) + Python lint (ruleset: ruff.toml). ruff ships in
# requirements-dev.txt and is installed by the .venv that `make test` bootstraps,
# so the pin in that file is the pin lint runs with.
lint:
	helm lint ./helm -f helm/values-local.yaml
	helm lint ./helm -f helm/values-prod.yaml
	$(MAKE) chart-parity
	@if [ -x .venv/bin/ruff ]; then .venv/bin/ruff check .; \
	  else echo "ERROR: .venv/bin/ruff missing - run 'make test' once to bootstrap .venv from requirements-dev.txt" >&2; exit 1; fi

# Drift guard (ADR-083): the main chart and the per-store chart each carry a
# copy of the wp-setup seed + storefront config and the store-assets copy step.
# This check fails when the copies diverge (allow-list for genuinely
# store-specific lines lives IN the script). How to update it:
# scripts/check-store-chart-parity.py docstring.
chart-parity:
	python3 scripts/check-store-chart-parity.py

template:
	helm template $(RELEASE) ./helm -n $(NAMESPACE) -f helm/values-local.yaml

# The wp-setup hook is a full WordPress + WooCommerce bootstrap (core download, plugin
# install, pages, COD settings, product seed, REST keypair). On the 2-CPU kind node that
# takes several minutes, so the hook budget must be generous: a too-small --timeout makes
# helm give up on a hook that is still working and report "context deadline exceeded".
helm-local:
	helm upgrade --install $(RELEASE) ./helm -n $(NAMESPACE) --create-namespace -f helm/values-local.yaml --timeout 15m $(HELM_ROLLBACK) --wait

# FIRST install on a FRESH cluster (prod or local): NO --wait and NO rollback flag.
# Helm runs post-install hooks only after --wait is satisfied, and the wp-setup
# hook is what CREATES the woo-secrets Secret that woo-mcp needs to be Ready, so a
# fresh install with --wait can never converge. Every later upgrade CAN use
# --rollback-on-failure --wait because the Secret already exists
# (docs/DEPLOY_VPS.md, first-install gotcha).
helm-prod-first:
	helm upgrade --install $(RELEASE) ./helm -n $(NAMESPACE) --create-namespace -f helm/values-prod.yaml $(ARGS) --timeout 15m

# Rotate generated credentials: delete a Secret and let the chart generate a new one on
# the next upgrade. For MariaDB/Postgres you MUST also delete the data PVC, because
# those engines only read the password when the data volume is first initialised
# (docs/DECISIONS.md ADR-015). Nothing here contains a credential value.
rotate-secrets:
	kubectl delete secret mariadb-secret pg-secret wordpress-secret gateway-secrets demo-notes-token -n $(NAMESPACE) --ignore-not-found
	@echo "deleted Secret(s) - next 'helm upgrade' generates fresh values"
	kubectl get pvc -n $(NAMESPACE) --no-headers 2>/dev/null | grep -E "mariadb|postgres" | awk '{print "  also delete (password is already in the volume): " $$1}'

helm-prod:
	helm upgrade --install $(RELEASE) ./helm -n $(NAMESPACE) --create-namespace -f helm/values-prod.yaml --timeout 15m $(HELM_ROLLBACK) --wait

logs:
	kubectl logs -l app=wordpress -n $(NAMESPACE) --tail=100 -f

ps:
	kubectl get pods,svc,ingress,pvc,networkpolicy -n $(NAMESPACE)

port-forward:
	kubectl port-forward svc/$(RELEASE)-wordpress 8080:80 -n $(NAMESPACE)

verify-store:
	@echo "== helm lint ==" && helm lint ./helm -f helm/values-local.yaml && helm lint ./helm -f helm/values-prod.yaml
	@echo "== kubectl ps ==" && kubectl get pods,svc,ingress,pvc,jobs,networkpolicy -n $(NAMESPACE)
	@echo "== wp-setup logs (last 80) ==" && kubectl logs -n $(NAMESPACE) -l app=wp-setup --tail=80 2>&1 | tail -n 80 || kubectl logs -n $(NAMESPACE) job/$(RELEASE)-wp-setup --tail=80 2>&1 | tail -n 80 || echo "no wp-setup logs yet"
	@echo "== store curl via Host header ==" && curl -s -H "Host: store.127.0.0.1.nip.io" http://localhost/ 2>&1 | head -n 30 || echo "store curl failed (ingress-nginx not ready?)"
	@echo "== woo-secrets ==" && kubectl get secret woo-secrets -n $(NAMESPACE) -o yaml 2>&1 | head -n 20 || echo "woo-secrets not yet created (wp-setup not finished)"
	@echo "== wordpress-admin Secret (existence only; use 'make admin-password' to read it) =="
	@kubectl get secret wordpress-admin -n $(NAMESPACE) -o jsonpath='{.metadata.name} created {.metadata.creationTimestamp}{"\n"}' 2>/dev/null || echo "wordpress-admin not created yet"

# Build the Layer 2 image and import it into the kind node (kind load has digest
# issues on this machine, so we pipe the image straight into containerd).
woo-mcp-image:
	$(DOCKER) build -t urumi/woo-mcp:0.1.0 src/woo-mcp
	$(DOCKER) save urumi/woo-mcp:0.1.0 | docker exec -i urumi-control-plane ctr -n k8s.io images import -
	@echo "loaded urumi/woo-mcp:0.1.0 into kind node"

# Layer 2 verification: probes, MCP handshake + 6 tools, isolation, no public ingress.
verify-mcp:
	@POD=$$(kubectl get pods -n $(NAMESPACE) -l app=woo-mcp -o jsonpath='{.items[0].metadata.name}'); \
	echo "== pods =="; kubectl get pods,svc,networkpolicy -n $(NAMESPACE) | grep -E "NAME|woo-mcp|allow-gateway"; \
	echo "== ingress hosts (woo-mcp must NOT appear) =="; kubectl get ingress -n $(NAMESPACE) -o jsonpath='{.items[0].spec.rules[*].host}'; echo ""; \
	echo "== MCP handshake + tools (in pod, via loopback) =="; \
	kubectl exec -n $(NAMESPACE) $$POD -c woo-mcp -- python3 -c "$$(cat scripts/verify-mcp.py)"; \
	echo "== isolation: a non-gateway pod must NOT reach woo-mcp =="; \
	WP=$$(kubectl get pods -n $(NAMESPACE) -l app=wordpress -o jsonpath='{.items[0].metadata.name}'); \
	kubectl exec -n $(NAMESPACE) $$WP -c wordpress -- sh -c 'curl -s -m 8 -o /dev/null -w "wordpress -> woo-mcp/mcp: %{http_code} (000 = blocked by NetworkPolicy)\n" -X POST http://urumi-woo-mcp:8000/mcp -H "Content-Type: application/json" -d "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"ping\"}" 2>/dev/null || echo "wordpress -> woo-mcp/mcp: blocked (no route)"'

# Extra demo upstreams (Day 5-7 seeds): build + import into the kind node.
demo-time-image:
	$(DOCKER) build -t urumi/demo-mcp-time:0.1.0 src/demo-mcp-time
	$(DOCKER) save urumi/demo-mcp-time:0.1.0 | docker exec -i urumi-control-plane ctr -n k8s.io images import -
	@echo "loaded urumi/demo-mcp-time:0.1.0 into kind node"

demo-notes-image:
	$(DOCKER) build -t urumi/demo-mcp-notes:0.1.0 src/demo-mcp-notes
	$(DOCKER) save urumi/demo-mcp-notes:0.1.0 | docker exec -i urumi-control-plane ctr -n k8s.io images import -
	@echo "loaded urumi/demo-mcp-notes:0.1.0 into kind node"

demo-images: demo-time-image demo-notes-image

# Hardened WordPress (ADR-043): FROM the pinned wordpress:6.6-php8.2-apache,
# listening on 8080, running as www-data (uid 33), no root. Build + import into
# the kind node; `make helm-local` (or a rollout restart) lands it.
wordpress-image:
	$(DOCKER) build -t urumi/wordpress:6.6-php8.2-apache-hardened src/wordpress
	$(DOCKER) save urumi/wordpress:6.6-php8.2-apache-hardened | docker exec -i urumi-control-plane ctr -n k8s.io images import -
	@echo "loaded urumi/wordpress:6.6-php8.2-apache-hardened into kind node"

# Hardened wp-cli runner for the wp-setup hook job (ADR-043): upstream
# wordpress:cli-php8.2 with /var/www/html owned by www-data, job runs as uid 33.
wp-cli-image:
	$(DOCKER) build -t urumi/wp-cli:cli-php8.2-hardened src/wp-cli
	$(DOCKER) save urumi/wp-cli:cli-php8.2-hardened | docker exec -i urumi-control-plane ctr -n k8s.io images import -
	@echo "loaded urumi/wp-cli:cli-php8.2-hardened into kind node"

# Static storefront assets (theme + catalog + images). Local Kind: build and
# import into the node; the WordPress pod's `store-assets` initContainer copies
# them onto the wp-content volume on pod start, so restart wordpress after a
# rebuild (`kubectl rollout restart deployment/urumi-wordpress -n urumi`).
store-assets-image:
	$(DOCKER) build -t urumi/store-assets:0.1.0 store
	$(DOCKER) save urumi/store-assets:0.1.0 | $(DOCKER) exec -i urumi-control-plane ctr -n k8s.io images import -
	@echo "loaded urumi/store-assets:0.1.0 into kind node"

# Verify both demo servers with a real MCP SDK ClientSession: list tools, call each,
# and show the 401 the notes server returns without a token.
verify-demo:
	@TIME_POD=$$(kubectl get pods -n $(NAMESPACE) -l app=demo-time -o jsonpath='{.items[0].metadata.name}'); \
	NOTES_POD=$$(kubectl get pods -n $(NAMESPACE) -l app=demo-notes -o jsonpath='{.items[0].metadata.name}'); \
	TOKEN=$$(kubectl get secret demo-notes-token -n $(NAMESPACE) -o jsonpath='{.data.NOTES_API_TOKEN}' | base64 -d); \
	echo "demo-time pod: $$TIME_POD"; echo "demo-notes pod: $$NOTES_POD"; \
	kubectl exec -n $(NAMESPACE) $$TIME_POD -c demo-time -- python3 -c "$$(cat scripts/verify-demo-time.py)"; \
	echo ""; \
	kubectl exec -n $(NAMESPACE) $$NOTES_POD -c demo-notes -- python3 -c "$$(cat scripts/verify-demo-notes.py)"; \
	echo ""; echo "== 401 without token (what the gateway will have to solve) =="; \
	kubectl exec -n $(NAMESPACE) $$NOTES_POD -c demo-notes -- python3 -c "$$(cat scripts/verify-demo-notes-401.py)"; \
	echo ""; echo "token used for authenticated checks: $${TOKEN%%????}... (full value stays in the Secret)"

# Layer 3 — gateway + dashboard images (local Kind: build + import into node)
# NOTE: importing an image under the SAME tag does NOT restart running pods — an
# existing pod keeps its old imageID until it is recreated. `make deploy` is the
# target that rebuilds AND restarts; use it (not these two alone) when the fix is
# in code, otherwise the running pod is silently stale (docs/DECISIONS.md ADR-028).
gateway-image:
	$(DOCKER) build -t urumi/gateway:0.1.0 src/gateway
	$(DOCKER) save urumi/gateway:0.1.0 | $(DOCKER) exec -i urumi-control-plane ctr -n k8s.io images import -
	@echo "loaded urumi/gateway:0.1.0 into kind node"
	@echo "REMINDER: pods are NOT restarted by an import - run 'make deploy' to restart"

dashboard-image:
	$(DOCKER) build -t urumi/dashboard:0.1.0 src/dashboard
	$(DOCKER) save urumi/dashboard:0.1.0 | $(DOCKER) exec -i urumi-control-plane ctr -n k8s.io images import -
	@echo "loaded urumi/dashboard:0.1.0 into kind node"
	@echo "REMINDER: pods are NOT restarted by an import - run 'make deploy' to restart"

# Phase 5 (ADR-060): the provisioner image bakes the store chart. Docker cannot
# COPY outside the context, so helm/store is staged into src/provisioner/chart
# for the build (transient; gitignored) and removed afterwards.
provisioner-image:
	rm -rf src/provisioner/chart
	cp -R helm/store src/provisioner/chart
	$(DOCKER) build -t urumi/provisioner:0.1.0 src/provisioner
	$(DOCKER) save urumi/provisioner:0.1.0 | docker exec -i urumi-control-plane ctr -n k8s.io images import -
	rm -rf src/provisioner/chart
	@echo "loaded urumi/provisioner:0.1.0 into kind node"

# Landing page image (ADR-080): static site from src/landing on nginx 8080.
# Same build + import pattern as dashboard-image. A chart change (values) still
# needs `make helm-local`; this is the content-change deploy path.
landing-image:
	$(DOCKER) build -t urumi/landing:0.2.0 src/landing
	$(DOCKER) save urumi/landing:0.2.0 | docker exec -i urumi-control-plane ctr -n k8s.io images import -
	@echo "loaded urumi/landing:0.2.0 into kind node"
	@echo "REMINDER: pods are NOT restarted by an import - restart with: kubectl rollout restart deployment/urumi-landing -n $(NAMESPACE)"

# Rebuild Layer 3 images, import them into the kind node, then RESTART the pods so
# the new build actually lands. Without the rollout restart, `ctr images import`
# replaces the image bytes under the same tag but existing pods keep running the
# previous image (their imageID is unchanged) - the stale-dashboard/pod bug.
# A chart change still needs `make helm-local`; this is the code-change deploy path.
deploy: gateway-image dashboard-image provisioner-image
	@echo "== restarting gateway + dashboard + provisioner so the new builds land =="
	kubectl rollout restart deployment/urumi-gateway deployment/urumi-dashboard deployment/urumi-provisioner -n $(NAMESPACE)
	kubectl rollout status deployment/urumi-gateway -n $(NAMESPACE) --timeout=150s
	kubectl rollout status deployment/urumi-dashboard -n $(NAMESPACE) --timeout=150s
	kubectl rollout status deployment/urumi-provisioner -n $(NAMESPACE) --timeout=150s
	@echo "== deploy done; pods on new image =="
	kubectl get pods -n $(NAMESPACE) -l 'app in (gateway, dashboard, provisioner)' -o jsonpath='{range .items[*]}{.metadata.name} image={.spec.containers[0].image} imageID={.status.containerStatuses[0].imageID}{"\n"}{end}'

# Verify gateway: handshake, tools/list fan-out (3 servers), tools/call routing, SSRF deny, audit, RBAC
verify-gateway:
	@POD=$$(kubectl get pods -n $(NAMESPACE) -l app=gateway -o jsonpath='{.items[0].metadata.name}'); \
	echo "== gateway pod: $$POD =="; kubectl get pods -n $(NAMESPACE) -l app=gateway; echo ""; \
	echo "== healthz/readyz =="; kubectl exec -n $(NAMESPACE) $$POD -c gateway -- sh -c 'curl -s http://127.0.0.1:8000/healthz; echo ""; curl -s http://127.0.0.1:8000/readyz; echo ""'; echo ""; \
	echo "== MCP handshake via gateway (requires API key) =="; \
	kubectl exec -n $(NAMESPACE) $$POD -c gateway -- python3 -c "$$(cat scripts/verify-gateway.py)" 2>&1 || echo "grep the FAILURES line above - gateway verification FAILED"

# Verify the live LLM path (Days 8-9 exit) inside the gateway pod: a chat
# completion that carries all 11 tool schemas, the multi-step tool loop (model
# calls a tool -> the gateway echoes the result -> the loop iterates), SSE
# streaming with [DONE], and the wrong-key error. Needs a real key in the
# `gateway-llm` Secret; the free-tier Gemini endpoint rate-limits per minute, so
# the script retries those turns instead of reporting them as failures.
verify-llm:
	@POD=$$(kubectl get pods -n $(NAMESPACE) -l app=gateway -o jsonpath='{.items[0].metadata.name}'); \
	echo "== gateway pod: $$POD =="; kubectl get pods -n $(NAMESPACE) -l app=gateway; echo ""; \
	echo "== chat streaming + multi-step tool loop via gateway (requires a real LLM key) =="; \
	kubectl exec -n $(NAMESPACE) $$POD -c gateway -- python3 -c "$$(cat scripts/verify-llm.py)" 2>&1 || echo "grep the FAILURES line above - LLM verification FAILED"

# Phase 5 (ADR-060): cross-store NetworkPolicy isolation proof (local kind only).
# Usage: make isolation A=gate-alpha B=gate-bravo
isolation:
	bash scripts/lib/phase5_isolation.sh $(A) $(B)

# Phase 7 (ADR-063): the full OAuth flow against the deployed gateway (host-side;
# 15 checks: metadata, DCR, consent+PKCE, token, /mcp calls, refresh, revocation).
oauth-gate:
	bash scripts/phase7-oauth-gate.sh

# Phase 7 (ADR-063): drive the gateway with the MCP Python SDK's OWN OAuth client.
sdk-oauth:
	@ADMIN_PASSWORD="$$(make -s gateway-admin-password | sed -n 's/^admin pass: *//p' | head -1)"; \
	test -n "$$ADMIN_PASSWORD" || { echo "could not read admin password" >&2; exit 2; }; \
	GATEWAY_ADMIN_PASSWORD="$$ADMIN_PASSWORD" .venv/bin/python scripts/phase7_sdk_oauth_client.py

# Unit tests for every src/ service that HAS a suite (docs/04): gateway (incl.
# the provisioner unit tests, which live under gateway/tests), woo-mcp and
# demo-mcp-time; tool namespacing/routing, timeout defaults + isolation, circuit
# breaker, RBAC/CSRF 403, audit redaction, admin-endpoint RBAC through the real
# router, and the MCP tool servers' blank-optional-argument contract. No cluster
# and no network needed. First run bootstraps ./.venv from requirements-dev.txt
# (never shipped in the image, gitignored). -q comes from each pytest.ini; the
# recipe must NOT add another -q or the final "N passed" summary disappears.
test:
	@if [ ! -x .venv/bin/pytest ]; then \
		echo "bootstrapping .venv for the test suite (first run only)..."; \
		python3 -m venv .venv; \
		.venv/bin/pip install -q -r requirements-dev.txt; \
	fi
	@echo "== src/gateway tests =="
	cd src/gateway && ../../.venv/bin/python -m pytest tests
	@echo "== src/woo-mcp tests =="
	cd src/woo-mcp && ../../.venv/bin/python -m pytest tests
	@echo "== src/demo-mcp-time tests =="
	cd src/demo-mcp-time && ../../.venv/bin/python -m pytest tests
	@echo "note: src/provisioner unit tests run inside the gateway suite (gateway/tests/test_provisioner_units.py)"
	@echo "note: src/demo-mcp-notes has no test suite (none invented here)"
	$(MAKE) chart-parity

# LOCAL USE ONLY - prints the gateway administrator password held in the chart-generated
# `gateway-admin` Secret (never printed by any automated target, never written to a
# committed file - docs/DECISIONS.md ADR-021). The gateway reads the same Secret as
# GATEWAY_ADMIN_PASSWORD and syncs it to the admin row on every start, so this value is
# always the one that works. GUARD: reads the LOCAL kind cluster only - the current
# kubectl context is printed first and anything other than kind-urumi is refused
# (a bare kubectl may be pointed at a VPS via KUBECONFIG, and this value must never
# be read from a remote cluster into a local shell).
gateway-admin-password:
	@CTX=$$(kubectl config current-context 2>/dev/null || true); \
	echo "kubectl context: $${CTX:-<unset>}"; \
	if [ "$$CTX" != "$(CONTEXT)" ]; then \
	  echo "ERROR: gateway-admin-password reads the LOCAL cluster only (context '$(CONTEXT)')." >&2; \
	  echo "       current kubectl context is '$${CTX:-<none>}': refusing to read the password from it." >&2; \
	  echo "       switch first with: kubectl config use-context $(CONTEXT)" >&2; \
	  exit 1; fi; \
	RAW=$$(kubectl get secret gateway-admin -n $(NAMESPACE) -o jsonpath='{.data.password}' 2>&1); RC=$$?; \
	if [ $$RC -ne 0 ]; then \
	  echo "ERROR: kubectl failed to read Secret gateway-admin (namespace $(NAMESPACE)) - this is a kubectl/connect problem, not an empty Secret. kubectl said:" >&2; \
	  echo "$$RAW" >&2; \
	  echo "hint: check the SSH tunnel is up and prefix with KUBECONFIG=<vps kubeconfig> - a bare kubectl targets the local kind cluster (docs/DEPLOY_VPS.md section 5)" >&2; \
	  exit 1; fi; \
	PASS=$$(printf '%s' "$$RAW" | base64 -d 2>/dev/null); \
	if [ -z "$$PASS" ]; then echo "ERROR: no password found in Secret gateway-admin (namespace $(NAMESPACE)): the Secret was READ but key .data.password is empty" >&2; exit 1; fi; \
	echo "admin email: $${GATEWAY_ADMIN_EMAIL:-admin@urumi.local}"; \
	echo "admin pass:  $$PASS"; \
	echo "(from Secret gateway-admin - local development only; never commit this value)"

verify-dashboard:
	@POD=$$(kubectl get pods -n $(NAMESPACE) -l app=dashboard -o jsonpath='{.items[0].metadata.name}'); \
	echo "== dashboard pod: $$POD =="; kubectl get pods -n $(NAMESPACE) -l app=dashboard; echo ""; \
	echo "== ingress hosts =="; kubectl get ingress -n $(NAMESPACE) -o jsonpath='{.items[0].spec.rules[*].host}'; echo ""; \
	kubectl exec -n $(NAMESPACE) $$POD -c dashboard -- sh -c 'curl -s -o /dev/null -w "dashboard / -> %{http_code}\n" http://127.0.0.1:80/ 2>/dev/null || wget -qO- http://127.0.0.1:80/ 2>&1 | head -n 5'

# LOCAL USE ONLY - prints the WordPress admin credentials held in the chart-generated
# `wordpress-admin` Secret. Never printed by any automated target, and never written to a
# committed file (docs/DECISIONS.md ADR-019). If `wpSetup.existingAdminSecret` is set, read
# that Secret instead.
admin-password:
	@SECRET=$${ADMIN_SECRET_NAME:-wordpress-admin}; \
	PASS=$$(kubectl get secret $${SECRET} -n $(NAMESPACE) -o jsonpath='{.data.password}' 2>/dev/null | base64 -d); \
	if [ -z "$$PASS" ]; then echo "ERROR: no password found in Secret $${SECRET} (namespace $(NAMESPACE))" >&2; exit 1; fi; \
	echo "admin user: $(WP_ADMIN_USER)"; \
	echo "admin pass: $$PASS"; \
	echo "(from Secret $${SECRET} - local development only; never commit this value)"

wp-logs:
	kubectl logs -n $(NAMESPACE) -l app=wp-setup --tail=100 2>&1 | tail -n 100; echo "---"; kubectl logs -n $(NAMESPACE) job/$(RELEASE)-wp-setup --tail=100 2>&1 | tail -n 100 || true

# Demo reset (docs/DECISIONS.md ADR-032): put the cluster back into a demo-ready
# state before recording. The DEFAULT is a DRY RUN that prints what WOULD be
# deleted (with counts) and changes nothing; `CONFIRM=yes` performs it.
#   make demo-reset                                  # dry run
#   make demo-reset CONFIRM=yes                      # perform the reset
#   make demo-reset CONFIRM=yes ARGS=--with-demo-users   # + demo A/B users
# Guards (refuses anything that is not the local kind cluster in namespace urumi),
# never touches Secrets/PVCs/the Helm release, and never prints a credential except
# the demo-user keys that --with-demo-users shows exactly once.
demo-reset:
	@CONTEXT=$(CONTEXT) NAMESPACE=$(NAMESPACE) CONFIRM=$(CONFIRM) scripts/demo-reset.sh $(ARGS)

# Verify Cash on delivery is offered at checkout.
# WooCommerce 9.x installs the BLOCK checkout by default: the payment method list is
# rendered client-side from the Store API (wc/store/v1/cart -> payment_methods), so that
# is what a browser ends up showing. The classic-checkout AJAX path (update_order_review)
# is kept as a fallback for installs that use the classic checkout shortcode.
# Verify Cash on delivery is offered at checkout.
# WooCommerce 9.x installs the BLOCK checkout by default: the payment method list is
# rendered client-side from the Store API (wc/store/v1/cart -> payment_methods), which is
# what a browser ends up showing. The classic-checkout AJAX path (update_order_review) is
# kept as a fallback for installs that still use the classic checkout shortcode.
# The MariaDB password is never written into this file, a process list or an env var we
# manage: the mariadb pod already receives it from the Secret as $MARIADB_PASSWORD, and
# the mariadb client honours $MYSQL_PWD instead of taking it via -p on the command line.
COD_PRODUCT_ID ?= $(shell kubectl exec -n $(NAMESPACE) urumi-mariadb-0 -c mariadb -- sh -c 'MYSQL_PWD="$$MARIADB_PASSWORD" mariadb -u wordpress wordpress -N -e "SELECT ID FROM wp_posts WHERE post_type=\"product\" AND post_status=\"publish\" ORDER BY ID LIMIT 1"' 2>/dev/null | tr -d '\r\n ')

verify-cod:
	@POD=$$(kubectl get pods -n $(NAMESPACE) -l app=wordpress -o jsonpath='{.items[0].metadata.name}'); \
	kubectl exec -n $(NAMESPACE) $$POD -c wordpress -- sh -c '\
	  rm -f /tmp/vc_cj; \
	  echo "using product id $(COD_PRODUCT_ID)"; \
	  curl -s -m 25 -c /tmp/vc_cj -b /tmp/vc_cj -o /dev/null "http://127.0.0.1:80/?add-to-cart=$(COD_PRODUCT_ID)"; \
	  echo "== Store API (block checkout, WooCommerce 9.x default) =="; \
	  curl -s -m 30 -c /tmp/vc_cj -b /tmp/vc_cj -o /tmp/vc_cart.json "http://127.0.0.1:80/wp-json/wc/store/v1/cart"; \
	  if grep -q "\"payment_methods\":\[[^]]*\"cod\"" /tmp/vc_cart.json; then echo "  cod -> OFFERED at checkout (block checkout)"; else echo "  cod -> NOT offered (block checkout)"; fi; \
	  grep -o "\"payment_methods\":\[[^]]*\]" /tmp/vc_cart.json | head -n 1; \
	  grep -o "\"items_count\":[0-9]*" /tmp/vc_cart.json | head -n 1; \
	  echo "== classic checkout AJAX (fallback) =="; \
	  curl -s -m 30 -c /tmp/vc_cj -b /tmp/vc_cj -o /tmp/vc_co.html "http://127.0.0.1:80/checkout/"; \
	  NONCE=$$(grep -o "\"update_order_review_nonce\":\"[a-f0-9]*\"" /tmp/vc_co.html | head -n1 | sed "s/.*:\"//; s/\"//"); \
	  if [ -n "$$NONCE" ]; then \
	    curl -s -m 60 -c /tmp/vc_cj -b /tmp/vc_cj -X POST "http://127.0.0.1:80/?wc-ajax=update_order_review" \
	      --data "security=$$NONCE&payment_method=cod&country=US&postcode=10001&state=NY&city=New+York&address=1+Main+St&has_full_address=true&post_data=billing_first_name%3DDemo%26billing_last_name%3DUser%26billing_email%3Ddemo%40example.com" -o /tmp/vc_rev.html; \
	    if grep -q "payment_method_cod" /tmp/vc_rev.html; then echo "  cod -> OFFERED at checkout (classic checkout)"; else echo "  cod -> NOT offered (classic checkout)"; fi; \
	  else echo "  classic checkout params not present (block checkout in use) - Store API result above is authoritative"; fi'
	@echo "== COD option value (from MariaDB) =="
	@kubectl exec -n $(NAMESPACE) urumi-mariadb-0 -c mariadb -- sh -c 'MYSQL_PWD="$$MARIADB_PASSWORD" mariadb -u wordpress wordpress -e "SELECT option_value FROM wp_options WHERE option_name=\"woocommerce_cod_settings\"" 2>/dev/null' | sed 's/^/  /'

# ------------------------------------------------------------------
# PROD READINESS (PROMPT V)
# ------------------------------------------------------------------
# Make a one-line stranger can run (required variables listed by `make help`):
#   GHCR_OWNER=<owner> GHCR_TOKEN=<token> make images-push
# Builds all 9 custom images with docker buildx for PLATFORMS (default
# linux/amd64; add linux/arm64 explicitly) and pushes ghcr.io/<owner>/<name>:<tag>.
# The 9th is the provisioner: the script stages helm/store into src/provisioner/chart
# (Docker cannot COPY outside the context; same staging as `provisioner-image`) and
# ALWAYS removes it via an EXIT trap, even when the run fails.
# Tag = <chart appVersion>-<short git SHA>, pinned into helm/values-prod.yaml after.
# The token is fed to `docker login --password-stdin` (env or hidden prompt), never
# echoed, never written to disk or shell history. See scripts/push-images.sh.
images-push:
	GHCR_OWNER=$${GHCR_OWNER:?set GHCR_OWNER (see make help)} scripts/push-images.sh

# Host-platform build + per-image container smoke test (no push). Proves every
# build context and Dockerfile works and that no secret-like files land in images.
smoke-images:
	scripts/smoke-images.sh

# Prod install/upgrade one-liner with an EXPLICIT helm timeout (ADR-048). The
# wp-setup hook bakes core + WooCommerce, so 15m covers a cold install; upgrades
# of an existing site finish far faster. The rollback flag (helm 4 spelling:
# --rollback-on-failure, older: --atomic) rolls back automatically when the
# upgrade fails, so a bad change cannot leave a half-deployed release.
# Rehearsed upgrade/rollback helpers (docs/UPGRADE_ROLLBACK.md). Overrides are
# inline so `make upgrade ARGS="--set gateway.image.tag=x"` works like helm.
upgrade:
	helm upgrade $(RELEASE) ./helm -n $(NAMESPACE) -f helm/values-local.yaml $(ARGS) --timeout 15m $(HELM_ROLLBACK) --wait

rollback:
	helm rollback $(RELEASE) $(REV) -n $(NAMESPACE) --timeout 15m --wait

# Quick reference for the prod-readiness variables.
help:
	@echo "Urumi Make targets"
	@echo "  make images-push   GHCR_OWNER=<owner> [GHCR_TOKEN=<token>] [PLATFORMS=linux/amd64,linux/arm64]"
	@echo "    builds all 9 custom images with buildx and pushes ghcr.io/<owner>/<name>:<tag>"
	@echo "    tag = <chart appVersion>-<short git SHA>; token via GHCR_TOKEN or hidden prompt"
	@echo "    (GHCR_TOKEN is never echoed, written to a file, or put in shell history)"
	@echo "  make smoke-images  build host-platform + run a container smoke test per image"
	@echo "  make helm-local / helm-prod   upgrade with explicit --timeout 15m --wait and"
	@echo "    $(HELM_ROLLBACK) (helm 4 spelling; --atomic on helm 3 - auto-detected)"
	@echo "  make helm-prod-first   FIRST install on a fresh cluster: no --wait (hook ordering,"
	@echo "    docs/DEPLOY_VPS.md); upgrades afterwards use make helm-prod"
	@echo "  make upgrade ARGS='--set x=y' / make rollback REV=<n>   rehearsed upgrade/rollback"
	@echo "  make verify-store verify-mcp verify-gateway verify-llm verify-hardening   live gates"
