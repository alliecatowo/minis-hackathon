"use client";

import { useEffect, useState, Suspense } from "react";
import { useSearchParams, useRouter } from "next/navigation";
import { exchangeCode, setStoredToken } from "@/lib/auth";

function CallbackInner() {
  const searchParams = useSearchParams();
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const code = searchParams.get("code");
    if (!code) {
      setError("No authorization code received");
      return;
    }

    exchangeCode(code)
      .then(({ token }) => {
        setStoredToken(token);
        router.replace("/");
      })
      .catch(() => setError("Authentication failed. Please try again."));
  }, [searchParams, router]);

  if (error) {
    return (
      <div className="flex min-h-[60vh] flex-col items-center justify-center gap-4">
        <p className="text-sm text-destructive">{error}</p>
        <a href="/" className="text-sm text-muted-foreground underline hover:text-foreground">
          Back to home
        </a>
      </div>
    );
  }

  return (
    <div className="flex min-h-[60vh] items-center justify-center">
      <p className="text-sm text-muted-foreground">Authenticating with GitHub...</p>
    </div>
  );
}

export default function AuthCallbackPage() {
  return (
    <Suspense fallback={<div className="flex min-h-[60vh] items-center justify-center"><p className="text-sm text-muted-foreground">Loading...</p></div>}>
      <CallbackInner />
    </Suspense>
  );
}
