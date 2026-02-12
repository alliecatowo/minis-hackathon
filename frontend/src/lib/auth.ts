"use client";

import { useSession, signIn, signOut } from "next-auth/react";
import { useMemo } from "react";

export interface AuthUser {
  id: string;
  github_username: string;
  display_name: string | null;
  avatar_url: string | null;
}

export interface AuthContextType {
  user: AuthUser | null;
  token: string | null;
  loading: boolean;
  login: () => void;
  logout: () => void;
}

export function useAuth(): AuthContextType {
  const { data: session, status } = useSession();

  const user = useMemo<AuthUser | null>(() => {
    if (!session?.user) return null;
    return {
      id: session.backendUserId ?? "",
      github_username: session.user.githubUsername ?? session.user.name ?? "",
      display_name: session.user.name ?? null,
      avatar_url: session.user.image ?? null,
    };
  }, [session]);

  return {
    user,
    token: null, // Tokens are now server-side only (BFF pattern)
    loading: status === "loading",
    login: () => signIn("github"),
    logout: () => signOut({ callbackUrl: "/" }),
  };
}
