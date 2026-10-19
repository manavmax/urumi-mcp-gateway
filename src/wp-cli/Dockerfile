# Hardened wp-cli runner for the wp-setup hook job (ADR-043), now with WordPress
# core and WooCommerce BAKED IN at build time (prod-readiness: the job must not
# download anything at runtime).
#
# Build-time fetches, both checksum-verified against hashes pinned in this repo:
#   - WordPress core tarball, verified against the sha1 published for the official
#     release (pinned below and re-checked here; a changed tarball fails the build)
#   - WooCommerce zip, verified against the sha256 committed in
#     woocommerce-9.4.2.zip.sha256 (copied in below so the pin travels with the image)
#
# At runtime wp-setup copies the core into the empty wp-content volume and installs
# the plugin from the baked zip: zero internet reach (NetworkPolicy now denies all
# egress except the cluster services the job needs).
FROM wordpress:cli-php8.2

ARG WORDPRESS_VERSION=6.6
# sha1 of https://wordpress.org/wordpress-6.6.tar.gz (fetched from
# https://wordpress.org/wordpress-6.6.tar.gz.sha1 on 2026-10-19 and pinned here)
ARG WORDPRESS_SHA1=6bdc580973c6c5e44c0c6164c348217152874817
ARG WOOCOMMERCE_VERSION=9.4.2

USER root

# WordPress core: download, VERIFY against the pinned sha1, unpack into a stable
# location the setup job copies from. If upstream ever mutates the tarball the
# sha1sum -c fails and the image build fails.
RUN set -eu; \
    curl -fsSL -o /tmp/wp.tar.gz "https://wordpress.org/wordpress-${WORDPRESS_VERSION}.tar.gz"; \
    echo "${WORDPRESS_SHA1}  /tmp/wp.tar.gz" | sha1sum -c -; \
    mkdir -p /var/www/wordpress-core; \
    tar -xzf /tmp/wp.tar.gz -C /var/www/wordpress-core --strip-components=1; \
    rm -f /tmp/wp.tar.gz

# WooCommerce: pinned version + sha256 recorded in the repo (the zip is not
# committed; the HASH is). Verification failure aborts the build.
COPY woocommerce-${WOOCOMMERCE_VERSION}.zip.sha256 /tmp/woo.sha256
RUN set -eu; \
    curl -fsSL -o /tmp/woocommerce.zip "https://downloads.wordpress.org/plugin/woocommerce.${WOOCOMMERCE_VERSION}.zip"; \
    echo "$(cut -d' ' -f1 /tmp/woo.sha256)  /tmp/woocommerce.zip" | sha256sum -c -; \
    cp /tmp/woocommerce.zip /var/www/woocommerce.zip; \
    rm -f /tmp/woocommerce.zip /tmp/woo.sha256

RUN chown -R www-data:www-data /var/www/html \
 && chown -R www-data:www-data /var/www/wordpress-core /var/www/woocommerce.zip

USER 33
