
## Hosted servers (Phase 6, ADR-062)

**Risk: an arbitrary admin-chosen image runs in the cluster.** The hosted-server
feature executes whatever container image an admin names. Controls: tag/digest
required (:latest refused), optional registry allowlist, non-root (uid 1000),
read-only root filesystem, all capabilities dropped, no service-account token,
mandatory resource requests/limits (capped by Helm values), default-deny
NetworkPolicy with ingress ONLY from gateway pods and egress ONLY DNS. The
namespace is provisioner-managed (the label guard confines all provisioner
operations). Residual risk: a malicious image still runs somewhere in the
cluster with its own code - it can attempt in-cluster recon limited by the
default-deny egress (DNS only), and its output is served to gateway users as
MCP tools. Only admins may host; the review question is whether that admin
trust level is acceptable. A gVisor/Kata sandbox or a VM boundary would be the
next hardening step if this left the demo.
