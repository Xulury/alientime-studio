import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { get, post, setCsrf } from "./api";
import type { AuthState } from "./types";

interface AuthCtx {
  state: AuthState | null;
  refresh: () => Promise<void>;
  login: (username: string, password: string) => Promise<void>;
  setup: (username: string, password: string, displayName: string) => Promise<void>;
  logout: () => Promise<void>;
}

const Ctx = createContext<AuthCtx>(null as unknown as AuthCtx);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<AuthState | null>(null);
  const qc = useQueryClient();

  const refresh = useCallback(async () => {
    try {
      const s = await get<AuthState>("/api/auth/state");
      setCsrf(s.csrf_token);
      setState(s);
    } catch {
      setState({ authenticated: false, setup_required: false, user: null, csrf_token: null });
    }
  }, []);

  useEffect(() => {
    refresh();
    const onExpired = () => refresh();
    window.addEventListener("studio:auth-expired", onExpired);
    return () => window.removeEventListener("studio:auth-expired", onExpired);
  }, [refresh]);

  const login = async (username: string, password: string) => {
    const s = await post<AuthState>("/api/auth/login", { username, password });
    setCsrf(s.csrf_token);
    qc.clear();
    setState({ ...s, setup_required: false });
  };
  const setup = async (username: string, password: string, display_name: string) => {
    const s = await post<AuthState>("/api/auth/setup", { username, password, display_name });
    setCsrf(s.csrf_token);
    setState({ ...s, setup_required: false });
  };
  const logout = async () => {
    await post("/api/auth/logout");
    setCsrf(null);
    qc.clear();
    setState({ authenticated: false, setup_required: false, user: null, csrf_token: null });
  };
  return <Ctx.Provider value={{ state, refresh, login, setup, logout }}>{children}</Ctx.Provider>;
}

export const useAuth = () => useContext(Ctx);
