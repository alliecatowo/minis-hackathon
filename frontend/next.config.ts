import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // BFF proxy at app/api/proxy/[...path]/route.ts handles backend forwarding.
  // Do NOT add rewrites for /api/proxy/* — on Vercel, edge rewrites run before
  // serverless functions and would bypass the BFF (which adds the service JWT).
};

export default nextConfig;
