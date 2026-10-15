/* Client-side page search: one shared query string, reset on navigation.
   Pages filter their already-loaded rows against this query (decided in
   STAGE 1 planning: search never hits the server). */
import React, { createContext, useContext, useEffect, useMemo, useState } from "react";
import { useLocation } from "react-router-dom";

type SearchState = { query: string; setQuery: (q: string) => void };

const Ctx = createContext<SearchState>({ query: "", setQuery: () => {} });

export function SearchProvider({ children }: { children: React.ReactNode }) {
  const [query, setQuery] = useState("");
  const location = useLocation();
  useEffect(() => {
    setQuery("");
  }, [location.pathname]);
  const value = useMemo(() => ({ query, setQuery }), [query]);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useSearch() {
  return useContext(Ctx);
}

/* Case-insensitive substring match across the given fields of a row. */
export function matchesQuery<T>(row: T, query: string, fields: (row: T) => Array<string | number | null | undefined>): boolean {
  const q = query.trim().toLowerCase();
  if (!q) return true;
  return fields(row).some((v) => v != null && String(v).toLowerCase().includes(q));
}

export function displayName(email: string | undefined): string {
  if (!email) return "";
  const local = email.split("@")[0] || email;
  return local
    .split(/[._-]+/)
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

/* Deterministic initials from real data: first letter of the email local part
   plus the first letter of the domain. admin@urumi.local -> AU. */
export function initials(email: string | undefined): string {
  if (!email) return "?";
  const [local, domain] = email.split("@");
  return ((local?.[0] || "") + (domain?.[0] || "")).toUpperCase();
}
