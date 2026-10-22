# Landing page: decisions made and items waiting for Manav

Context: the `landing` branch work was done without access to the cluster (another session uses
it), and without answers to a few questions only you can settle. Everything below was decided
unilaterally and logged in docs/DECISIONS.md as ADR-080..084; nothing here blocks merging, but
each item needs your eyes before or shortly after the deploy.

## Decisions I made (details in docs/DECISIONS.md)

- ADR-080: static no-build site in `src/landing/`, served by the dashboard nginx pattern
  (uid 101, 8080, strict CSP, zero external requests, video as a link out, never an embed).
- ADR-081: dark-first with a light toggle; tokens mirror the dashboard family; stored choice beats
  `prefers-color-scheme` beats dark. Design tokens documented in docs/LANDING_DESIGN.md.
- ADR-082: `src/landing/features.js` is the only config file; every beyond-the-brief item ships
  `enabled: false`, zero enabled items hides the whole section.
- ADR-083: five new `helm/templates/landing-*.yaml` files; apex Ingress with a dedicated
  certificate Secret (`urumi-landing-tls`); NetworkPolicy opens ingress ONLY from the ingress
  controller, no egress at all; dedicated ServiceAccount with no token; flag OFF by default.
- ADR-084: verification ran with docker + Playwright + helm lint/template only, no cluster.

## Waiting on you

1. **Apex DNS before enabling (prod).** The apex A record must point at the server BEFORE
   `landing.enabled=true` and `landing.host=<bare domain>` go into the prod upgrade
   (`--set landing.host=example.com --set landing.enabled=true`, or your uncommitted overlay;
   I did not touch the committed values-prod.yaml, per the brief it keeps placeholders).
2. **Confirm the repo URL.** The page links to `https://github.com/urumi-ai/mcp-gateway`
   (the `home:` field in helm/Chart.yaml). If the public repo lives elsewhere, change `repoUrl` in
   `src/landing/features.js` and rebuild the image.
3. **Flip features.js items only after the branches merge.** multi-store, hosted servers, OAuth,
   compact tool mode, rate limits, metrics are all `enabled: false`. Flip one, then
   `make landing-image` and restart `deployment/urumi-landing` (on the cluster; I never ran these).
4. **Demo video.** The section stays hidden until `landing.videoUrl` is set in features.js. It
   renders as a link OUT (no embed), so the page keeps making zero external requests. If you want
   an embedded player instead, that is a deliberate CSP/external-request policy change.
5. **Look at the screenshots.** artifacts/landing/landing-{desktop,mobile}-{dark,light}.png
   (1440 and 390, both themes, full page; gitignored). This session could not view images, so the
   visual review was scripted proxies: no horizontal overflow at 390/1440, 32/32 AA contrast pairs
   per theme, zero console errors, reduced-motion collapse verified. Your eyes are the last gate.
6. **www subdomain.** The component serves only the bare apex (`landing.host`). If you want
   www.<domain> to reach the page too, it needs one more Ingress rule; I left it out because the
   brief named the apex only.
7. **Image tag for the build session.** I built locally as `urumi/landing:0.1.0`. For GHCR, use
   `make images-push` (it will build all nine images as `ghcr.io/<owner>/landing:<appVersion>-<sha>`)
   and pin that tag in values-prod.
8. **Live check on kind (when free).** `make landing-image && make helm-local`, then open
   http://127.0.0.1.nip.io . Everything above was verified against the docker image on port 8090
   and with helm template; the in-cluster path (ingress -> NetworkPolicy -> pod) is chart-reviewed
   but never live-run from this session.

## Evidence summary

- `docker build -t urumi/landing:0.1.0 src/landing` and `docker run --user 101 ... ` (uid 101,
  tmpfs for the three emptyDir paths): 200 on /, all five assets 200, 404 for unknown paths, CSP
  self-only + nosniff + no-referrer + DENY framing on every response.
- `node scripts/landing-verify.mjs`: all four cases OK (zero external requests, contrast 32/32
  both themes, zero console errors, beyond/video hidden by default, gateway URL derived).
- `helm lint` with values-local and values-prod.example: 0 failures. `helm template` with the flag
  off renders zero landing lines; with values-local it renders SA + Service + Deployment + Ingress
  + the controller-only NetworkPolicy.
- Page weight: 52KB raw / 15.5KB gzip total. Secret scan and em-dash scan of src/landing: clean.
