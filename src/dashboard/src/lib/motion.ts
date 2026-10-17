/* Mockup motion script, ported from design/mockups/*.html: cards fade + rise
   staggered 40ms in DOM order (first 8 cards), and the first 12 table rows
   fade in the same way. Pure CSS animations (styles.css keyframes); this hook
   only assigns the stagger delays exactly like the mockup script does. */
import { useEffect, useRef, useState } from "react";

export function useMockupMotion(dep: unknown) {
  useEffect(() => {
    const cards = document.querySelectorAll(
      ".content > .card, .content > .page-head, .content > .note-banner, .content > section, .content > div",
    );
    cards.forEach((el, i) => {
      (el as HTMLElement).style.animationDelay = i < 8 ? `${i * 40}ms` : "0ms";
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

/* Count-up hook: animates a number from 0 to `target` over `duration` ms via
   requestAnimationFrame (the only JS animation allowed beyond CSS keyframes).
   `decimals` keeps fractional values (e.g. success rate 99.5) exact at the end.
   Skips straight to the final value under prefers-reduced-motion. */
export function useCountUp(target: number, duration = 700, decimals = 0): number {
  const [value, setValue] = useState(0);
  const rafRef = useRef<number>(0);
  const startRef = useRef<number>(0);

  useEffect(() => {
    if (target === 0) { setValue(0); return; }
    const prefersReduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (prefersReduced) { setValue(target); return; }

    setValue(0);
    startRef.current = performance.now();
    const factor = Math.pow(10, decimals);
    rafRef.current = requestAnimationFrame(function step(now) {
      const elapsed = now - startRef.current;
      const progress = Math.min(elapsed / duration, 1);
      const eased = 1 - Math.pow(1 - progress, 3);
      setValue(Math.round(eased * target * Math.pow(10, decimals)) / Math.pow(10, decimals));
      if (progress < 1) {
        rafRef.current = requestAnimationFrame(step);
      }
    });
    return () => { if (rafRef.current) cancelAnimationFrame(rafRef.current); };
  }, [target, duration]);

  return value;
}
