// Landing environment config (ADR-088). This file is the image default for
// plain `docker run` (no chart). In every deployment the landing-config
// ConfigMap — rendered from landing.repoUrl and the chart's ingress hosts —
// is mounted OVER this exact path, so the chart values are the one place to
// change these. No other file in src/landing carries the repo URL.
(window.LANDING = window.LANDING || {}).repoUrl = "https://github.com/manavmax/urumi-mcp-gateway";
