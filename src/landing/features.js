// Landing page configuration (ADR-082). The ONLY file you edit to change what
// the landing page claims about the project. Rebuild the image after editing.
//
// repoUrl   shown in the announcement bar and the nav (defaults to the repo URL
//           from helm/Chart.yaml home; confirm it points at the public repo).
// videoUrl  the optional demo video. EMPTY = the video block stays hidden. When
//           set, the block renders as a link OUT to the video (never an embed:
//           the page makes zero external requests by design, ADR-080).
// features  the "Beyond the brief" section. Every item ships enabled:false.
//           Only items set to true are rendered; when none are true the whole
//           section is hidden. Flip an item after it actually lands in the
//           demo, never before: the page must only claim what exists there.
window.LANDING = {
  repoUrl: "https://github.com/urumi-ai/mcp-gateway",
  // The real gateway URL shown in the hero MCP config. EMPTY (default) = main.js
  // derives it from the page host by prefixing the apex with "dashboard."
  // (dashboard.<apex>/mcp, the same convention the Helm values use), so the
  // static page never hardcodes a hostname. Set an explicit URL here only if
  // the gateway lives somewhere the convention cannot express.
  gatewayUrl: "",
  // Product count quoted by the store claim ("a 12-product catalog"). Correct
  // it here after the store work lands; set null to drop the count and read
  // "a product catalog".
  storeProductCount: 12,
  videoUrl: "",
  features: [
    {
      id: "multi-store",
      enabled: false,
      title: "Multi-store provisioning",
      body: "Register a second WooCommerce store as its own namespace and manage both from one gateway."
    },
    {
      id: "hosted-servers",
      enabled: false,
      title: "Hosted MCP servers",
      body: "Run shared MCP servers in-cluster alongside the gateway instead of pointing at external ones."
    },
    {
      id: "oauth",
      enabled: false,
      title: "OAuth client login",
      body: "Let members sign in with an external identity provider instead of an invited email and password."
    },
    {
      id: "compact-tools",
      enabled: false,
      title: "Compact tool mode",
      body: "Collapse tool schemas before they reach the LLM so large tool sets fit in one prompt."
    },
    {
      id: "rate-limits",
      enabled: false,
      title: "Configurable rate limits",
      body: "Per-key and per-server quotas set from Helm values instead of the built-in defaults."
    },
    {
      id: "metrics",
      enabled: false,
      title: "Prometheus metrics",
      body: "Expose gateway counters for calls, latency and breaker state to a scraper endpoint."
    }
  ]
};
