# Store v2 in-cluster verification - NOT RUN (do after merge/deploy)

Everything in this doc is written for the live kind cluster and was NOT
executed by the store-v2 session (the cluster was off-limits; all verification
ran against a throwaway docker compose stack using the same hardened images and
the real rendered wp-setup script - see docs/DECISIONS.md ADR-075).

Assumes the store layer of this branch is deployed: `make gateway-image` /
`make store-assets-image` + `helm upgrade`, or your usual deploy flow, with the
new store-assets image copied into wp-content by the initContainer.

## 1. Seed timing (the ~3 minute budget)

The job runs on `helm upgrade`; watch it from creation to completion:

```sh
kubectl -n urumi get jobs urumi-wp-setup -w
# or, after completion:
kubectl -n urumi get job urumi-wp-setup -o jsonpath='{.status.completionTime}{" <- done, started: "}{.status.startTime}{"\n"}'
```

Compose reference (arm64-emulated, pessimistic): fresh install 84 s,
re-run 44 s. The cluster measured 3 m 37 s for the 12-product install
(ADR-048) natively; 36 products + ~122 sideloads should stay inside the
3-minute job budget - confirm with the timestamps above.

## 2. Catalog assertions via the Woo REST API

```sh
CK=$(kubectl -n urumi get secret woo-secrets -o jsonpath='{.data.WOO_CONSUMER_KEY}' | base64 -d)
CS=$(kubectl -n urumi get secret woo-secrets -o jsonpath='{.data.WOO_CONSUMER_SECRET}' | base64 -d)
STORE_URL=http://store.127.0.0.1.nip.io   # adjust to your ingress host

# 36 published products
curl -su "$CK:$CS" "$STORE_URL/wp-json/wc/v3/products?per_page=100&status=publish" \
  | python3 -c 'import json,sys; ps=json.load(sys.stdin); print("products:", len(ps)); print("no image:", [p["sku"] for p in ps if not p["images"]]); print("on sale:", len([p for p in ps if p["on_sale"]])); print("out of stock:", [p["sku"] for p in ps if p["stock_status"]=="outofstock"]); print("tags missing:", [p["sku"] for p in ps if not p["tags"]])'

# variations with their own stock (6 variable products, 15 variations)
for ID in $(curl -su "$CK:$CS" "$STORE_URL/wp-json/wc/v3/products?type=variable&per_page=10" | python3 -c 'import json,sys; print(" ".join(str(p["id"]) for p in json.load(sys.stdin)))'); do
  curl -su "$CK:$CS" "$STORE_URL/wp-json/wc/v3/products/$ID/variations?per_page=20" \
    | python3 -c 'import json,sys; vs=json.load(sys.stdin); print([(v["sku"], v["price"], v["stock_quantity"]) for v in vs])'
done
```

## 3. Seed-twice idempotency

Re-run the seed only (force off is the default):

```sh
kubectl -n urumi delete job urumi-wp-setup --ignore-not-found
helm template urumi ./helm -n urumi -f helm/values-local.yaml | kubectl -n urumi apply -f -
kubectl -n urumi wait --for=condition=complete job/urumi-wp-setup --timeout=6m
kubectl -n urumi logs job/urumi-wp-setup -c wp-setup | grep "seed summary"
# expect: created=0 kept=36 updated=0 images=0 variations_created=0 (force=0)
```

Product count must remain 36 before and after:

```sh
curl -su "$CK:$CS" "$STORE_URL/wp-json/wc/v3/products?per_page=1" -o /dev/null -D - | grep -i x-wp-total
```

Legacy URUMI-* products from the old catalog (if this cluster ever ran it) are
removed only by `make demo-reset`, whose keep-manifest now lists the 36
LOAM-* SKUs.

## 4. End-to-end COD checkout + REST visibility

`scripts/verify-store-v2.mjs` works against the cluster as-is:

```sh
export STORE_URL=http://store.127.0.0.1.nip.io
export V2_CK=$CK V2_CS=$CS   # or a dedicated verify key; never commit these
node scripts/verify-store-v2.mjs screenshots --out artifacts/store-cluster
node scripts/verify-store-v2.mjs checkout --out artifacts/store-cluster
node scripts/verify-store-v2.mjs rest --expect 32
```

The checkout mode places a real COD order through the block checkout and then
asserts the order is visible via `/wp-json/wc/v3/orders` with
`payment_method=cod` - the same API surface the woo-mcp tools
(list_products, create_product, list_orders, get_order, update_order_status,
list_product_images, add_product_image) use. The consumer key created by
wp-setup is used unchanged (the seed still creates/rotates it into the
woo-secrets Secret).

## 5. demo-reset contract on the cluster

```sh
make demo-reset            # removes orders only; keeps the 36 LOAM-* products
# watch the pod logs for: "seed summary: created=0 kept=36 ..."
# and "media summary: kept=119 deleted=N" (N = test uploads only)
```

The media reset keeps featured + gallery attachments of manifest SKUs
(119 = 36 mains + 83 gallery) and deletes everything else.

## 6. Offline / zero third-party

```sh
node scripts/verify-store-v2.mjs screenshots --out artifacts/store-cluster
# every page asserts zero third-party requests and no console errors
```

## 7. Brand sanity

```sh
curl -s "$STORE_URL/" | grep -o "<title>[^<]*"   # Loam & Ember ...
kubectl -n urumi exec deploy/urumi-wordpress -c wordpress -- \
  wp option get blogname   # Loam & Ember
```
