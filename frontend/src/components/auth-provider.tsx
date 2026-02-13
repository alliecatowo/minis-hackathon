'use client';

import { authClient } from '@/lib/auth';
import { NeonAuthUIProvider } from '@neondatabase/auth/react';
import type { ReactNode } from 'react';

export function AuthProvider({ children }: { children: ReactNode }) {
  return (
    <NeonAuthUIProvider authClient={authClient} social={{ providers: ['github'] }}>
      {children}
    </NeonAuthUIProvider>
  );
}
