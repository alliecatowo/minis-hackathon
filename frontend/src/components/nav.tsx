"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Button } from "@/components/ui/button";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { Plus, Github, LogOut } from "lucide-react";
import { cn } from "@/lib/utils";
import { useAuth } from "@/lib/auth";

export function Nav() {
  const pathname = usePathname();
  const { user, loading, login, logout } = useAuth();

  return (
    <header className="sticky top-0 z-50 h-14 border-b border-border/50 bg-background/80 backdrop-blur-sm">
      <div className="mx-auto flex h-full max-w-6xl items-center justify-between px-4">
        <div className="flex items-center gap-6">
          <Link href="/" className="font-mono text-lg font-bold tracking-tight">
            minis
          </Link>
          <nav className="hidden items-center gap-4 sm:flex">
            <Link
              href="/gallery"
              className={cn(
                "text-sm transition-colors hover:text-foreground",
                pathname === "/gallery"
                  ? "text-foreground font-medium"
                  : "text-muted-foreground"
              )}
            >
              Gallery
            </Link>
            {user && (
              <Link
                href="/teams"
                className={cn(
                  "text-sm transition-colors hover:text-foreground",
                  pathname.startsWith("/teams")
                    ? "text-foreground font-medium"
                    : "text-muted-foreground"
                )}
              >
                Teams
              </Link>
            )}
          </nav>
        </div>
        <div className="flex items-center gap-3">
          <Link href="/">
            <Button size="sm" variant="outline" className="gap-1.5">
              <Plus className="h-3.5 w-3.5" />
              <span className="hidden sm:inline">New Mini</span>
            </Button>
          </Link>
          {loading ? null : user ? (
            <div className="flex items-center gap-2">
              <Link href={`/m/${user.github_username}`}>
                <Avatar className="h-7 w-7 cursor-pointer">
                  <AvatarImage src={user.avatar_url || undefined} alt={user.github_username} />
                  <AvatarFallback className="text-[10px]">
                    {user.github_username.slice(0, 2).toUpperCase()}
                  </AvatarFallback>
                </Avatar>
              </Link>
              <Button size="sm" variant="ghost" onClick={logout} className="h-7 w-7 p-0">
                <LogOut className="h-3.5 w-3.5" />
              </Button>
            </div>
          ) : (
            <Button size="sm" variant="outline" onClick={login} className="gap-1.5">
              <Github className="h-3.5 w-3.5" />
              <span className="hidden sm:inline">Login</span>
            </Button>
          )}
        </div>
      </div>
    </header>
  );
}
