import type { NextAuthConfig } from "next-auth";
import type { JWT } from "next-auth/jwt";
import GitHub from "next-auth/providers/github";

const BACKEND_URL = process.env.BACKEND_URL || "http://localhost:8000";

declare module "next-auth" {
  interface Session {
    backendUserId?: string;
    backendToken?: string;
    user: {
      id?: string;
      name?: string | null;
      email?: string | null;
      image?: string | null;
      githubUsername?: string;
    };
  }
}

declare module "next-auth/jwt" {
  interface JWT {
    backendUserId?: string;
    backendToken?: string;
    githubUsername?: string;
  }
}

export default {
  providers: [GitHub],
  session: { strategy: "jwt" },
  callbacks: {
    async signIn({ user, account, profile }) {
      if (account?.provider !== "github" || !profile) return true;

      const ghProfile = profile as unknown as {
        id: number;
        login: string;
        name?: string | null;
        avatar_url?: string;
      };

      try {
        const res = await fetch(`${BACKEND_URL}/api/auth/sync`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            github_id: ghProfile.id,
            github_username: ghProfile.login,
            display_name: ghProfile.name ?? null,
            avatar_url: ghProfile.avatar_url ?? user.image ?? null,
          }),
        });

        if (!res.ok) {
          console.error("Backend sync failed:", res.status, await res.text());
          return false;
        }

        const data: { user_id: string; token: string } = await res.json();
        // Store on the user object so the jwt callback can pick it up
        (user as Record<string, unknown>).backendUserId = data.user_id;
        (user as Record<string, unknown>).backendToken = data.token;
        (user as Record<string, unknown>).githubUsername = ghProfile.login;
        return true;
      } catch (err) {
        console.error("Backend sync error:", err);
        return false;
      }
    },

    async jwt({ token, user }) {
      if (user) {
        const u = user as Record<string, unknown>;
        token.backendUserId = u.backendUserId as string | undefined;
        token.backendToken = u.backendToken as string | undefined;
        token.githubUsername = u.githubUsername as string | undefined;
      }
      return token;
    },

    async session({ session, token }) {
      session.backendUserId = token.backendUserId;
      session.backendToken = token.backendToken;
      if (token.githubUsername) {
        session.user.githubUsername = token.githubUsername;
      }
      return session;
    },
  },
} satisfies NextAuthConfig;
