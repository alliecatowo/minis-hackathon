"use client";

import { useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { Button } from "@/components/ui/button";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { Plus, Github, LogOut, Menu, X } from "lucide-react";
import { cn } from "@/lib/utils";
import { useAuth } from "@/lib/auth";

export function Nav() {
  const pathname = usePathname();
  const { user, loading, login, logout } = useAuth();
  const [menuOpen, setMenuOpen] = useState(false);

  const linkClass = (href: string) =>
    cn(
      "text-sm transition-colors",
      pathname === href || pathname.startsWith(href + "/")
        ? "text-foreground font-medium"
        : "text-muted-foreground hover:text-foreground"
    );

  return (
    <header className="sticky top-0 z-50 border-b border-border/50 bg-background/80 backdrop-blur-sm">
      <div className="relative mx-auto flex h-14 max-w-6xl items-center justify-between px-4">
        <div className="flex items-center gap-6">
          <Link href="/" className="font-mono text-lg font-bold tracking-tight">
            minis
          </Link>
          <nav className="hidden items-center gap-4 sm:flex">
            <Link href="/gallery" className={linkClass("/gallery")}>
              Gallery
            </Link>
            {user && (
              <Link href="/teams" className={linkClass("/teams")}>
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
            <div className="hidden items-center gap-2 sm:flex">
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
            <Button size="sm" variant="outline" onClick={login} className="hidden gap-1.5 sm:flex">
              <Github className="h-3.5 w-3.5" />
              <span className="hidden sm:inline">Login</span>
            </Button>
          )}
          <button
            type="button"
            onClick={() => setMenuOpen(!menuOpen)}
            className="sm:hidden rounded-md p-2 text-muted-foreground hover:text-foreground"
          >
            {menuOpen ? <X className="h-5 w-5" /> : <Menu className="h-5 w-5" />}
          </button>
        </div>
      </div>
      {menuOpen && (
        <div className="border-t border-border bg-background p-4 sm:hidden">
          <div className="flex flex-col gap-3">
            <Link href="/gallery" className={linkClass("/gallery")} onClick={() => setMenuOpen(false)}>
              Gallery
            </Link>
            {user && (
              <Link href="/teams" className={linkClass("/teams")} onClick={() => setMenuOpen(false)}>
                Teams
              </Link>
            )}
            {loading ? null : user ? (
              <button
                type="button"
                onClick={() => { logout(); setMenuOpen(false); }}
                className="text-left text-sm text-muted-foreground hover:text-foreground"
              >
                Logout
              </button>
            ) : (
              <button
                type="button"
                onClick={() => { login(); setMenuOpen(false); }}
                className="text-left text-sm text-muted-foreground hover:text-foreground"
              >
                Login with GitHub
              </button>
            )}
          </div>
        </div>
      )}
    </header>
  );
}
