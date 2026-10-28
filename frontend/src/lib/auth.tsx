import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { api, hasToken, setToken, setUnauthorizedHandler } from "./api";
import type { Me } from "./types";

interface AuthState {
  me: Me | null;
  ready: boolean;
  login(username: string, password: string): Promise<void>;
  register(email: string, username: string, password: string): Promise<void>;
  logout(): void;
}

const Ctx = createContext<AuthState>(null!);
export const useAuth = () => useContext(Ctx);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [me, setMe] = useState<Me | null>(null);
  const [ready, setReady] = useState(false);

  const loadMe = useCallback(async () => {
    setMe(hasToken() ? await api<Me>("/users/me").catch(() => null) : null);
    setReady(true);
  }, []);

  useEffect(() => {
    setUnauthorizedHandler(() => setMe(null));
    loadMe();
  }, [loadMe]);

  const value = useMemo<AuthState>(() => {
    const login = async (username: string, password: string) => {
      const t = await api<{ access_token: string }>("/auth/login", {
        method: "POST",
        form: { username, password },
      });
      setToken(t.access_token);
      await loadMe();
    };
    return {
      me,
      ready,
      login,
      register: async (email, username, password) => {
        await api("/auth/register", { method: "POST", json: { email, username, password } });
        await login(username, password);
      },
      logout: () => {
        setToken(null);
        setMe(null);
      },
    };
  }, [me, ready, loadMe]);

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}
