'use client';

import { createAuthClient } from '@neondatabase/auth/next';
import { useMemo } from 'react';

export const authClient = createAuthClient();

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
  const { data: session, isPending } = authClient.useSession();

  const user = useMemo<AuthUser | null>(() => {
    if (!session?.user) return null;
    return {
      id: session.user.id ?? '',
      github_username: session.user.name ?? '',
      display_name: session.user.name ?? null,
      avatar_url: session.user.image ?? null,
    };
  }, [session]);

  return {
    user,
    token: null,
    loading: isPending,
    login: () => authClient.signIn.social({ provider: 'github', callbackURL: '/' }),
    logout: () => authClient.signOut(),
  };
}
