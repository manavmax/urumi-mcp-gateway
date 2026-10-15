import React, { createContext, useContext, useEffect, useState, useCallback } from "react";
import { api, setCsrf } from "./api";
import { clearHistory } from "./history";

type User = { id: string; email: string; role: string };
type AuthState = {
  user: User | null;
  loading: boolean;
  login: (email: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  refresh: () => Promise<void>;
};

const Ctx = createContext<AuthState>(null as unknown as AuthState);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    try {
      const me = await api.me();
      setUser(me.user);
      setCsrf(me.csrf_token);
    } catch {
      setUser(null);
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
    setCsrf(res.csrf_token);
  }, []);

  const logout = useCallback(async () => {
    /* STAGE 1 decision: chat history is browser-only and cleared on sign out. */
    clearHistory(user?.email ?? "");
    try {
      await api.logout();
    } finally {
      setUser(null);
      setCsrf("");
    }
  }, [user?.email]);

  return <Ctx.Provider value={{ user, loading, login, logout, refresh }}>{children}</Ctx.Provider>;
}

export function useAuth() {
  return useContext(Ctx);
}
