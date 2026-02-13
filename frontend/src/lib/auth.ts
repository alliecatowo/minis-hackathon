'use client';

import { createAuthClient } from '@neondatabase/auth/next';
import { useMemo, useCallback } from 'react';

const PRODUCTION_URL = 'https://frontend-red-one-13.vercel.app';

function isPreview(): boolean {
  if (typeof window === 'undefined') return false;
  const host = window.location.host;
  return host.includes('--') && host.includes('.vercel.app') && !host.startsWith('frontend-red-one-13');
}

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

  const login = useCallback(() => {
    if (isPreview()) {
      const returnUrl = encodeURIComponent(window.location.origin + window.location.pathname);
      window.location.href = `${PRODUCTION_URL}/api/auth/signin/social?provider=github&callbackURL=${PRODUCTION_URL}/auth/bridge?return_to=${returnUrl}`;
    } else {
      authClient.signIn.social({ provider: 'github', callbackURL: '/' });
    }
  }, []);

  const logout = useCallback(() => {
    if (isPreview()) {
      window.location.href = `${PRODUCTION_URL}/api/auth/signout?callbackURL=${encodeURIComponent(window.location.origin)}`;
    } else {
      authClient.signOut();
    }
  }, []);

  return {
    user,
    token: null,
    loading: isPending,
    login,
    logout,
  };
}
