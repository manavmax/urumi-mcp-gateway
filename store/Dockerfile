# Urumi store-assets image.
# Static only: the catalog (store/products.json), the product images and the
# urumi-store block theme. The WordPress deployment's `store-assets`
# initContainer copies these onto the wp-content volume (the official WordPress
# image never refreshes an existing wp-content volume, so this copy step is
# mandatory - docs/DECISIONS.md ADR). Nothing here runs at runtime.
FROM alpine:3.20
RUN mkdir -p /assets/themes
COPY products.json /assets/products.json
COPY photos-manifest.json /assets/photos-manifest.json
COPY images /assets/images
COPY theme/urumi-store /assets/themes/urumi-store
