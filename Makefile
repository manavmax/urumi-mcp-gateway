.PHONY: kind-up kind-down ingress lint template helm-local helm-prod rotate-secrets clean logs ps port-forward verify-store wp-logs verify-cod woo-mcp-image verify-mcp demo-time-image demo-notes-image demo-images verify-demo

NAMESPACE ?= urumi
RELEASE   ?= urumi

kind-up:
	kind create cluster --name urumi --config kind-config.yaml
	kubectl cluster-info --context kind-urumi

kind-down:
	kind delete cluster --name urumi

ingress:
	kubectl apply -f https://raw.githubusercontent.com/kubernetes/ingress-nginx/main/deploy/static/provider/kind/deploy.yaml
	kubectl wait --namespace ingress-nginx --for=condition=ready pod --selector=app.kubernetes.io/component=controller --timeout=180s

lint:
	helm lint ./helm -f helm/values-local.yaml
	helm lint ./helm -f helm/values-prod.yaml

template:
	helm template $(RELEASE) ./helm -n $(NAMESPACE) -f helm/values-local.yaml

helm-local:
	helm upgrade --install $(RELEASE) ./helm -n $(NAMESPACE) --create-namespace -f helm/values-local.yaml --timeout 8m

# Rotate generated credentials: delete a Secret and let the chart generate a new one on
# the next upgrade. For MariaDB/Postgres you MUST also delete the data PVC, because
# those engines only read the password when the data volume is first initialised
# (docs/DECISIONS.md ADR-015). Nothing here contains a credential value.
rotate-secrets:
	kubectl delete secret mariadb-secret pg-secret wordpress-secret gateway-secrets demo-notes-token -n $(NAMESPACE) --ignore-not-found
	@echo "deleted Secret(s) - next 'helm upgrade' generates fresh values"
	kubectl get pvc -n $(NAMESPACE) --no-headers 2>/dev/null | grep -E "mariadb|postgres" | awk '{print "  also delete (password is already in the volume): " $$1}'

helm-prod:
	helm upgrade --install $(RELEASE) ./helm -n $(NAMESPACE) --create-namespace -f helm/values-prod.yaml --timeout 8m --atomic

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

# Build the Layer 2 image and import it into the kind node (kind load has digest
# issues on this machine, so we pipe the image straight into containerd).
woo-mcp-image:
	docker build -t urumi/woo-mcp:0.1.0 src/woo-mcp
	docker save urumi/woo-mcp:0.1.0 | docker exec -i urumi-control-plane ctr -n k8s.io images import -
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
	docker build -t urumi/demo-mcp-time:0.1.0 src/demo-mcp-time
	docker save urumi/demo-mcp-time:0.1.0 | docker exec -i urumi-control-plane ctr -n k8s.io images import -
	@echo "loaded urumi/demo-mcp-time:0.1.0 into kind node"

demo-notes-image:
	docker build -t urumi/demo-mcp-notes:0.1.0 src/demo-mcp-notes
	docker save urumi/demo-mcp-notes:0.1.0 | docker exec -i urumi-control-plane ctr -n k8s.io images import -
	@echo "loaded urumi/demo-mcp-notes:0.1.0 into kind node"

demo-images: demo-time-image demo-notes-image

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

wp-logs:
	kubectl logs -n $(NAMESPACE) -l app=wp-setup --tail=100 2>&1 | tail -n 100; echo "---"; kubectl logs -n $(NAMESPACE) job/$(RELEASE)-wp-setup --tail=100 2>&1 | tail -n 100 || true

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
