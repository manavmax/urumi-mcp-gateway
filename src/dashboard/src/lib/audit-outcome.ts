/* One outcome-to-chip map for every tool-call outcome the dashboard renders
   (Audit, Overview, member Overview, Chat tool echoes). The four pages used to
   carry their own copies, and the copies disagreed: Audit styled
   permission_denied neutral with the deny icon while the other three painted it
   the same as a failed call. This is Audit's map, which the mockup-driven
   page defines; the backend constrains outcomes to the six values checked by
   ck_audit_outcome in the gateway schema, so anything unexpected still reads as
   an error. */
export function outcomeChip(o: string): { cls: string; icon: "check-circle" | "alert" | "x-circle" | "deny" } {
  if (o === "success") return { cls: "chip-ok", icon: "check-circle" };
  if (o === "timeout" || o === "circuit_open") return { cls: "chip-warn", icon: "alert" };
  if (o === "permission_denied") return { cls: "chip-neutral", icon: "deny" };
  return { cls: "chip-danger", icon: "x-circle" };
}
