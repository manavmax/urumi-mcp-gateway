import { useState, useEffect, useCallback, createContext, useContext, createElement, type ReactNode } from "react";

// F1 item 1: two modes only. Light and Dark. Default Light when nothing is
// stored; a stored "system" or any unknown value is treated as Light.
export type Theme = "light" | "dark";

const ThemeCtx = createContext<{ theme: Theme; setTheme: (t: Theme) => void } | null>(null);

function readSaved(): Theme {
  try {
    const v = localStorage.getItem("theme");
    if (v === "light" || v === "dark") return v;
  } catch { /* ignore */ }
  return "light";
}

function applyResolved(t: Theme) {
  document.documentElement.setAttribute("data-theme", t);
  updateFavicon();
}

/* Favicon + logo mark follow the theme via currentColor: rebuild the SVG
   data-URL favicon from the live token values so the tab icon matches the
   page (dark tile in light mode, light tile in dark mode). No hex here:
   colours are read from the computed tokens at runtime. */
function updateFavicon() {
  try {
    const cs = getComputedStyle(document.documentElement);
    const tile = (cs.getPropertyValue("--ink") || "").trim();
    const line = (cs.getPropertyValue("--primary-pill-text") || "").trim();
    if (!tile || !line) return;
    const svg =
      `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">` +
      `<rect x="3" y="3" width="18" height="18" rx="5.5" fill="${tile}"/>` +
      `<path d="M9.2 16.8v-3.4a2.8 2.8 0 0 1 5.6 0v3.4" fill="none" stroke="${line}" stroke-width="1.9" stroke-linecap="round"/>` +
      `<path d="M7 12h10" fill="none" stroke="${line}" stroke-width="1.9" stroke-linecap="round"/>` +
      `</svg>`;
    const url = `data:image/svg+xml,${encodeURIComponent(svg)}`;
    let link = document.querySelector<HTMLLinkElement>('link[rel="icon"]');
    if (!link) {
      link = document.createElement("link");
      link.rel = "icon";
      link.type = "image/svg+xml";
      document.head.appendChild(link);
    }
    link.href = url;
  } catch { /* ignore */ }
}

export function useTheme() {
  const [theme, setThemeState] = useState<Theme>(() => {
    if (typeof window === "undefined") return "light";
    const saved = readSaved();
    document.documentElement.setAttribute("data-theme", saved);
    return saved;
  });

  useEffect(() => {
    applyResolved(theme);
    try { localStorage.setItem("theme", theme); } catch { /* ignore */ }
  }, [theme]);

  const setTheme = useCallback((t: Theme) => setThemeState(t), []);
  return { theme, setTheme };
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [theme, setThemeState] = useState<Theme>(() => {
    if (typeof window === "undefined") return "light";
    return readSaved();
  });

  useEffect(() => {
    applyResolved(theme);
    try { localStorage.setItem("theme", theme); } catch { /* ignore */ }
  }, [theme]);

  const setTheme = useCallback((t: Theme) => setThemeState(t), []);
  return createElement(ThemeCtx.Provider, { value: { theme, setTheme } }, children);
}

export function useSharedTheme() {
  const ctx = useContext(ThemeCtx);
  if (ctx) return ctx;
  return useTheme();
}
