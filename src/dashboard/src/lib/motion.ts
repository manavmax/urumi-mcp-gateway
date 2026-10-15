/* Mockup motion script, ported from design/mockups/*.html: cards fade + rise
   staggered 40ms in DOM order, and the first 12 table rows fade in the same
   way. Pure CSS animations (styles.css keyframes); this hook only assigns the
   stagger delays exactly like the mockup script does. */
import { useEffect } from "react";

export function useMockupMotion(dep: unknown) {
  useEffect(() => {
    const cards = document.querySelectorAll(
      ".content > .card, .content > .page-head, .content > .note-banner, .content > section, .content > div",
    );
    cards.forEach((el, i) => {
      (el as HTMLElement).style.animationDelay = `${i * 40}ms`;
    });
    const rows = document.querySelectorAll("tbody tr");
    rows.forEach((el, i) => {
      if (i < 12) {
        el.classList.add("row-anim");
        (el as HTMLElement).style.animationDelay = `${i * 40}ms`;
      }
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dep]);
}
