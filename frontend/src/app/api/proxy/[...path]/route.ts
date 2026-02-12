import { type NextRequest, NextResponse } from "next/server";
import { SignJWT } from "jose";
import { auth } from "@/lib/auth-server";

// Allow large file uploads (100MB) and longer execution time through the proxy
export const maxDuration = 60;
export const dynamic = "force-dynamic";

const BACKEND_URL = process.env.BACKEND_URL || "http://localhost:8000";
const SERVICE_JWT_SECRET = process.env.SERVICE_JWT_SECRET || "dev-service-secret-change-in-production";

async function createServiceJwt(backendUserId: string): Promise<string> {
  const secret = new TextEncoder().encode(SERVICE_JWT_SECRET);
  return new SignJWT({ sub: backendUserId })
    .setProtectedHeader({ alg: "HS256" })
    .setIssuedAt()
    .setExpirationTime("5m")
    .setIssuer("minis-bff")
    .sign(secret);
}

async function proxyRequest(req: NextRequest, params: { path: string[] }): Promise<Response> {
  const path = params.path.join("/");

  const { data: session } = await auth.getSession();
  const backendUserId = session?.user?.id;
  console.log(`[proxy] ${req.method} /api/${path} hasAuth=${!!backendUserId}`);

  // Debug endpoint
  if (path === "_debug/auth") {
    return NextResponse.json({
      hasSession: !!session,
      backendUserId: backendUserId ?? null,
      hasBackendUrl: !!process.env.BACKEND_URL,
      backendUrl: process.env.BACKEND_URL?.substring(0, 20),
      cookies: req.cookies.getAll().map(c => c.name),
    });
  }

  const url = new URL(`/api/${path}`, BACKEND_URL);

  // Forward query parameters
  req.nextUrl.searchParams.forEach((value, key) => {
    url.searchParams.set(key, value);
  });

  // Build headers, forwarding content-type and other relevant headers
  const headers = new Headers();
  const contentType = req.headers.get("content-type");
  if (contentType) {
    headers.set("content-type", contentType);
  }

  // Add service JWT from Neon Auth session (BFF pattern)
  if (backendUserId) {
    const serviceJwt = await createServiceJwt(backendUserId);
    headers.set("authorization", `Bearer ${serviceJwt}`);
  }

  // Get request body for non-GET requests
  let body: BodyInit | null = null;
  if (req.method !== "GET" && req.method !== "HEAD") {
    if (contentType?.includes("multipart/form-data")) {
      body = await req.blob();
      headers.delete("content-type");
      headers.set("content-type", contentType);
    } else {
      body = await req.text();
    }
  }

  try {
    const backendRes = await fetch(url.toString(), {
      method: req.method,
      headers,
      body,
    });

    // For SSE responses, stream them through
    const resContentType = backendRes.headers.get("content-type") || "";
    if (resContentType.includes("text/event-stream")) {
      return new Response(backendRes.body, {
        status: backendRes.status,
        headers: {
          "content-type": "text/event-stream",
          "cache-control": "no-cache",
          connection: "keep-alive",
        },
      });
    }

    const responseHeaders = new Headers();
    backendRes.headers.forEach((value, key) => {
      if (!["transfer-encoding", "content-encoding", "content-length", "connection", "keep-alive"].includes(key.toLowerCase())) {
        responseHeaders.set(key, value);
      }
    });

    // 204 No Content has no body — don't try to read one
    if (backendRes.status === 204) {
      return new NextResponse(null, { status: 204, headers: responseHeaders });
    }

    const resBody = await backendRes.arrayBuffer();
    return new NextResponse(resBody, {
      status: backendRes.status,
      headers: responseHeaders,
    });
  } catch (err) {
    console.error("Proxy error:", err);
    return NextResponse.json(
      { detail: "Backend unavailable" },
      { status: 502 },
    );
  }
}

export async function GET(req: NextRequest, context: { params: Promise<{ path: string[] }> }) {
  const params = await context.params;
  return proxyRequest(req, params);
}

export async function POST(req: NextRequest, context: { params: Promise<{ path: string[] }> }) {
  const params = await context.params;
  return proxyRequest(req, params);
}

export async function PUT(req: NextRequest, context: { params: Promise<{ path: string[] }> }) {
  const params = await context.params;
  return proxyRequest(req, params);
}

export async function DELETE(req: NextRequest, context: { params: Promise<{ path: string[] }> }) {
  const params = await context.params;
  return proxyRequest(req, params);
}

export async function PATCH(req: NextRequest, context: { params: Promise<{ path: string[] }> }) {
  const params = await context.params;
  return proxyRequest(req, params);
}
