import React, { createContext, useContext, useEffect, useState, useCallback } from "react";
import { api, setCsrf } from "./api";
import { clearHistory } from "./history";

type User = { id: string; email: string; role: string };
export type Features = { stores: boolean; hosted: boolean };
/* Old-gateway tolerance: if /api/me carries no features object, assume both on
   (the API's own 403s stay the source of truth for what actually works). */
const DEFAULT_FEATURES: Features = { stores: true, hosted: true };
type AuthState = {
  user: User | null;
  features: Features;
  loading: boolean;
  login: (email: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  refresh: () => Promise<void>;
};

const Ctx = createContext<AuthState>(null as unknown as AuthState);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [features, setFeatures] = useState<Features>(DEFAULT_FEATURES);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    try {
      const me = await api.me();
      setUser(me.user);
      setFeatures(me.features ?? DEFAULT_FEATURES);
      setCsrf(me.csrf_token);
    } catch {
      setUser(null);
      setFeatures(DEFAULT_FEATURES);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const login = useCallback(async (email: string, password: string) => {
    const res = await api.login(email, password);
    setUser(res.user);
    setFeatures(res.features ?? DEFAULT_FEATURES);
    setCsrf(res.csrf_token);
  }, []);

  const logout = useCallback(async () => {
    /* STAGE 1 decision: chat history is browser-only and cleared on sign out. */
    clearHistory(user?.email ?? "");
    try {
      await api.logout();
    } finally {
      setUser(null);
      setFeatures(DEFAULT_FEATURES);
      setCsrf("");
    }
  }, [user?.email]);

  return <Ctx.Provider value={{ user, features, loading, login, logout, refresh }}>{children}</Ctx.Provider>;
}

export function useAuth() {
  return useContext(Ctx);
}
