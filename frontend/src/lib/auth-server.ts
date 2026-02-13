import { createNeonAuth } from '@neondatabase/auth/next/server';

const baseUrl = process.env.AUTH_URL || process.env.NEON_AUTH_BASE_URL || 'http://localhost:3000';

export const auth = createNeonAuth({
  baseUrl,
  cookies: { 
    secret: process.env.NEON_AUTH_COOKIE_SECRET || 'dev-secret-change-in-production-min-32-chars!' 
  },
});
