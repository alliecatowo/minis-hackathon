"use client";

import { type ReactNode } from "react";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useAuth } from "@/lib/auth";
import { type LucideIcon } from "lucide-react";

interface AuthGateProps {
  children: ReactNode;
  icon: LucideIcon;
  message: string;
}

export function AuthGate({ children, icon: Icon, message }: AuthGateProps) {
  const { user, loading: authLoading, login } = useAuth();

  if (authLoading) {
    return (
      <div className="flex min-h-[60vh] items-center justify-center">
        <Skeleton className="h-8 w-48" />
      </div>
    );
  }

  if (!user) {
    return (
      <div className="flex min-h-[60vh] flex-col items-center justify-center gap-4">
        <div className="flex h-16 w-16 items-center justify-center rounded-full bg-secondary">
          <Icon className="h-7 w-7 text-muted-foreground" />
        </div>
        <div className="text-center">
          <p className="font-medium text-foreground">Sign in required</p>
          <p className="mt-1 text-sm text-muted-foreground">{message}</p>
        </div>
        <Button onClick={login} size="sm" className="mt-2">
          Sign In
        </Button>
      </div>
    );
  }

  return <>{children}</>;
}
