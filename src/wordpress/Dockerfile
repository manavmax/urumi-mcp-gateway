# Hardened WordPress image (ADR-043).
#
# FROM the pinned upstream wordpress:6.6-php8.2-apache, with exactly three deltas:
#   1. Apache listens on the unprivileged 8080 instead of 80, so the whole
#      container (entrypoint + master + workers) can run as www-data (uid 33)
#      with no root process and no CAP_NET_BIND_SERVICE.
#   2. /var/www/html and the apache runtime dirs are owned by www-data, so the
#      entrypoint can write wp-config.php from the WORDPRESS_* env without root.
#   3. USER 33 - the image default, enforced again by the chart's
#      podSecurity.workloads.wordpress (runAsUser: 33).
# Core files stay byte-identical to the upstream image; the urumi mu-plugins keep
# arriving via the wp-setup job onto the shared wp-content PVC (that volume mounts
# OVER /var/www/html/wp-content, so baking them here would be hidden anyway).
# The WooCommerce pin lives in wpSetup.wooVersion (values), not here.
FROM wordpress:6.6-php8.2-apache

USER root

# Log hardening (ADR-043): the default "combined" format logs %u (REMOTE_USER),
# which for /wp-json/ Basic auth is the Woo CONSUMER KEY - a credential half,
# leaked into pod logs on every MCP REST call. The redefined combined format
# drops %u (replaced by a literal "-"); conf-enabled loads after apache2.conf's
# LogFormat definitions, so this redefinition wins.
#
# Bake the WordPress core INTO /var/www/html at build time. The upstream image
# ships a sparse docroot and the entrypoint tar-extracts /usr/src/wordpress into
# it on every boot; as a NON-ROOT container on a FRESH wp-content volume that
# extract fails with "tar: ./wp-content: Cannot change mode to rwxrwxrwx:
# Operation not permitted" (the volume mount root is owned root:fsGroup, so the
# non-root uid cannot chmod it) and the pod crashloops. With the core baked into
# the image docroot, the entrypoint's copy step never runs: apache starts
# immediately, fresh AND existing volumes alike (prod-readiness ADR-048).
RUN cp -a /usr/src/wordpress/. /var/www/html/ \
 && sed -ri 's/^Listen 80$/Listen 8080/' /etc/apache2/ports.conf \
 && sed -ri 's/^<VirtualHost \*:80>$/<VirtualHost *:8080>/' /etc/apache2/sites-available/000-default.conf \
 && printf 'LogFormat "%%h %%l - %%t \\"%%r\\" %%>s %%O \\"%%{Referer}i\\" \\"%%{User-Agent}i\\"" combined\n' > /etc/apache2/conf-available/zz-urumi-logformat.conf \
 && a2enconf zz-urumi-logformat \
 && chown -R www-data:www-data /var/www/html \
 && chown -R www-data:www-data /var/run/apache2 /var/log/apache2 /var/cache/apache2 2>/dev/null || true

USER 33

EXPOSE 8080
