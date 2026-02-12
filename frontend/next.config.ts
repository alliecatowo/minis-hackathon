import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Proxy /api/* requests to the backend.
  // - Local dev: defaults to http://localhost:8000
  // - Vercel prod: set BACKEND_URL env var to the Fly.io backend URL
  //   (e.g. https://minis-api.fly.dev)
  async rewrites() {
    const backendUrl = process.env.BACKEND_URL || "http://localhost:8000";
    return [
      {
        // Proxy only /api/proxy/* to backend, NOT /api/auth/*
        source: "/api/proxy/:path*",
        destination: `${backendUrl}/api/:path*`,
      },
    ];
  },
};

export default nextConfig;
