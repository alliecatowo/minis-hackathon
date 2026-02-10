"use client";

import { useState, useEffect, useCallback, type ReactNode } from "react";
import {
  AuthContext,
  type AuthUser,
  getStoredToken,
  setStoredToken,
  clearStoredToken,
  loginRedirect,
  fetchCurrentUser,
} from "@/lib/auth";

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [token, setToken] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const stored = getStoredToken();
    if (stored) {
      setToken(stored);
      fetchCurrentUser(stored)
        .then(setUser)
        .catch(() => {
          clearStoredToken();
          setToken(null);
        })
        .finally(() => setLoading(false));
    } else {
      setLoading(false);
    }
  }, []);

  const login = useCallback(() => loginRedirect(), []);
  const logout = useCallback(() => {
    clearStoredToken();
    setUser(null);
    setToken(null);
  }, []);

  return (
    <AuthContext value={{ user, token, loading, login, logout }}>
      {children}
    </AuthContext>
  );
}
