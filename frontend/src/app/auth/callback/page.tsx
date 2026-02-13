"use client";

import { Suspense, useEffect, useRef } from "react";
import { useSearchParams } from "next/navigation";

function AuthCallbackContent() {
  const searchParams = useSearchParams();
  const initiated = useRef(false);

  useEffect(() => {
    if (initiated.current) return;
    initiated.current = true;

    const token = searchParams.get("token");
    
    if (!token) {
      window.location.href = "/?error=no_token";
      return;
    }

    fetch("/api/auth/session", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ token }),
    })
      .then((res) => {
        if (res.ok) {
          window.location.href = "/";
        } else {
          window.location.href = "/?error=session_failed";
        }
      })
      .catch(() => {
        window.location.href = "/?error=session_failed";
      });
  }, [searchParams]);

  return (
    <div className="flex min-h-screen items-center justify-center">
      <p className="text-lg">Completing sign in...</p>
    </div>
  );
}

export default function AuthCallbackPage() {
  return (
    <Suspense fallback={
      <div className="flex min-h-screen items-center justify-center">
        <p className="text-lg">Loading...</p>
      </div>
    }>
      <AuthCallbackContent />
    </Suspense>
  );
}
