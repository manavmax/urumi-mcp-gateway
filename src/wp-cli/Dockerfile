# Hardened wp-cli runner for the wp-setup hook job (ADR-043).
#
# FROM the same upstream wordpress:cli-php8.2 the job used before, with one delta:
# /var/www/html is chowned to www-data so the whole job can run as uid 33. The job
# writes wp-config.php there on every run (the cli image ships no wp-config.php, so
# `wp config create` runs against the shared DB each time); mu-plugins, seeds and
# plugin installs go to the shared wp-content PVC, which the job pod's fsGroup 33
# makes group-writable. No root, ALL capabilities dropped (chart podSecurity).
FROM wordpress:cli-php8.2

USER root

RUN chown -R www-data:www-data /var/www/html

USER 33
