// Copy helper (F1 item 5): navigator.clipboard only exists in a secure
// context, and http://*.nip.io is NOT one, so a plain clipboard.writeText
// silently throws there. One util for every copy button:
// 1. navigator.clipboard.writeText when it exists and works (https, localhost);
// 2. else a hidden readonly textarea + document.execCommand("copy");
// 3. else select the text and tell the user to press Ctrl/Cmd + C.
// Returns a status so the button can show "Copied" or the manual hint.
export type CopyStatus = "copied" | "manual";

export async function copyText(text: string): Promise<CopyStatus> {
  if (typeof navigator !== "undefined" && window.isSecureContext && navigator.clipboard?.writeText) {
    try {
      await navigator.clipboard.writeText(text);
      return "copied";
    } catch { /* fall through to the execCommand path */ }
  }
  try {
    const ta = document.createElement("textarea");
    ta.value = text;
    ta.setAttribute("readonly", "");
    ta.style.position = "fixed";
    ta.style.left = "-9999px";
    ta.style.opacity = "0";
    document.body.appendChild(ta);
    const selection = document.getSelection();
    const prevRange = selection && selection.rangeCount > 0 ? selection.getRangeAt(0) : null;
    ta.select();
    const ok = document.execCommand("copy");
    ta.remove();
    if (prevRange && selection) { selection.removeAllRanges(); selection.addRange(prevRange); }
    if (ok) return "copied";
  } catch { /* fall through to the manual hint */ }
  return "manual";
}
