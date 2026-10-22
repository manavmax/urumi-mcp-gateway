# Landing page image (ADR-080): same pattern as the dashboard image, minus the
# build stage (the site is already plain static HTML/CSS/JS, no build step).
# nginx runs as uid 101 via the chart podSecurity and listens on 8080; no root,
# no CAP_NET_BIND_SERVICE needed.
FROM nginx:1.27-alpine
COPY index.html styles.css main.js theme-init.js features.js favicon.svg /usr/share/nginx/html/
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 8080
