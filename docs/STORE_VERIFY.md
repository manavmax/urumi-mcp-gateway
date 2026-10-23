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

---

# UPDATE 2026-10-22 (photo-first theme pass, branch store-v2)

## What ran in the compose harness THIS session (real runs)

Harness: `docker compose -f artifacts/store-compose/compose.yml -p store-v2-verify`
(fresh `down -v` first), exact hardened images, wp-setup executed as the REAL
rendered script (`render-setup.py` re-run after every helm edit).

| Check | Result |
| --- | --- |
| Fresh wp-setup (36 products, 15 variations, no image files) | 54 s (emulated arm64; pessimistic) |
| Second wp-setup run (idempotency) | `created=0 kept=36 updated=0 images=0 variations_created=0`, 45 s |
| REST catalog (count, sale, stock, weight/dims, tags, variations) | all PASS at 36 products |
| REST "every product has an image" | FAIL, expected: no photographs shipped yet (ADR-078) |
| REST "gallery images (2+)" | FAIL, expected: same reason |
| e2e COD checkout via block checkout -> REST order visible | PASS (order #72, status processing, payment_method=cod) |
| Screenshots 1440 + 390 (10 page types) + gates | 91/93 PASS (screens in artifacts/store-v2-shots, gitignored) |
| Zero third-party requests | PASS on every page and viewport |
| No horizontal overflow (390/768-class/1440) | PASS after `overflow-x: clip` fix (Woo drawer) |
| Console errors | PASS except 2 known cosmetic Woo ResizeObserver warnings (cart 1440, checkout 390) |
| WCAG contrast (rest/hover/focus, all pages) | PASS (after ADR-080 fixes; scripts/verify-store-contrast.mjs) |
| Home page weight | 470 KB total (454 subresources + 16 doc) - under the 800 KB gate (no photos yet; re-measure after curation) |
| Shop page weight | 542 KB total |
| demo-reset contract (dry-run via REST) | 36 KEEP, 0 planned product deletions, orders always removed |
| Consumer key from wp-setup | harness artifact: each compose wp-setup run rotates it (no K8s Secret in compose); the harness re-inserts its verify key. In-cluster semantics unchanged. |
| /image-credits/ page | 200, licence copy rendered; footer "Photography from Unsplash." links to it |
| Banned-words + em-dash scan of shipped copy | clean (one invented origin claim removed from a product description) |

Reproduce:

```sh
node scripts/verify-store-v2.mjs screenshots --out artifacts/store-v2-shots
node scripts/verify-store-v2.mjs checkout
node scripts/verify-store-v2.mjs rest --expect 36
STORE_URL=http://localhost:18088 node scripts/verify-store-contrast.mjs
```

## What did NOT run (photo-dependent, blocked by ADR-078)

- Photo curation, product rebuild FROM photos, IMAGE_CREDITS rows, contact
  sheet with real photos.
- Screenshot review by eye: this session's model cannot view images; the
  19 screenshots in artifacts/store-v2-shots await a human/photo-capable pass.
- Post-photo re-measurement of page weight (tiles will add ~300-600 KB
  fetched; the 800 KB home budget needs re-checking then - see
  docs/REVIEW_NEEDED_STORE.md).
