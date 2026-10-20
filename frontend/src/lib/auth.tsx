import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { errorMessage, get, post, setCsrf } from "./api";
import type { AuthState } from "./types";

interface AuthCtx {
  state: AuthState | null;
  error: string | null;
  refresh: () => Promise<void>;
  login: (username: string, password: string) => Promise<void>;
  setup: (username: string, password: string, displayName: string) => Promise<void>;
  register: (username: string, password: string, displayName: string) => Promise<void>;
  guest: () => Promise<void>;
  logout: () => Promise<void>;
}

const Ctx = createContext<AuthCtx>(null as unknown as AuthCtx);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<AuthState | null>(null);
  const [error, setError] = useState<string | null>(null);
  const version = useRef(0);
  const qc = useQueryClient();

  const refresh = useCallback(async () => {
    const requestVersion = ++version.current;
    setError(null);
    try {
      const s = await get<AuthState>("/api/auth/state");
      if (requestVersion !== version.current) return;
      setCsrf(s.csrf_token);
      setState(s);
    } catch (e) {
      if (requestVersion === version.current) setError(errorMessage(e));
    }
  }, []);

  useEffect(() => {
    refresh();
    const onExpired = () => {
      setCsrf(null);
      setState(null);
      void refresh();
    };
    window.addEventListener("studio:auth-expired", onExpired);
    return () => window.removeEventListener("studio:auth-expired", onExpired);
  }, [refresh]);

  const acceptSession = (s: AuthState) => {
    // A slow initial state request must not overwrite a newly signed-in session.
    version.current++;
    setCsrf(s.csrf_token);
    setError(null);
    qc.clear();
    setState({ ...s, setup_required: false });
  };

  const login = async (username: string, password: string) => {
    const s = await post<AuthState>("/api/auth/login", { username, password });
    acceptSession(s);
  };
  const setup = async (username: string, password: string, display_name: string) => {
    const s = await post<AuthState>("/api/auth/setup", { username, password, display_name });
    acceptSession(s);
  };
  const register = async (username: string, password: string, display_name: string) => {
    const s = await post<AuthState>("/api/auth/register", { username, password, display_name });
    acceptSession(s);
  };
  const guest = async () => {
    const s = await post<AuthState>("/api/auth/guest");
    acceptSession(s);
  };
  const logout = async () => {
    await post("/api/auth/logout");
    version.current++;
    setCsrf(null);
    setError(null);
    qc.clear();
    setState({ authenticated: false, setup_required: false, user: null, csrf_token: null });
  };
  return <Ctx.Provider value={{ state, error, refresh, login, setup, register, guest, logout }}>{children}</Ctx.Provider>;
}

export const useAuth = () => useContext(Ctx);
