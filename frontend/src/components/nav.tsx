"use client";

import { useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { Button } from "@/components/ui/button";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Plus, Github, Menu, X, Settings, BarChart3, LogOut } from "lucide-react";
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

  const initials = user
    ? user.github_username.slice(0, 2).toUpperCase()
    : "";

  return (
    <header className="sticky top-0 z-50 border-b border-border/50 bg-background/80 backdrop-blur-sm">
      <div className="relative mx-auto flex h-14 max-w-6xl items-center justify-between px-4">
        <div className="flex items-center gap-6">
          <Link href="/" className="font-mono text-lg font-bold tracking-tight">
            minis
          </Link>
          <nav className="hidden items-center gap-4 sm:flex">
            <Link href="/features" className={linkClass("/features")}>
              Features
            </Link>
            <Link href="/roadmap" className={linkClass("/roadmap")}>
              Roadmap
            </Link>
            <Link href="/pricing" className={linkClass("/pricing")}>
              Pricing
            </Link>
            <Link href="/gallery" className={linkClass("/gallery")}>
              Gallery
            </Link>
            {user && (
              <Link href="/teams" className={linkClass("/teams")}>
                Teams
              </Link>
            )}
            {user && (
              <Link href="/orgs" className={linkClass("/orgs")}>
                Orgs
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
            <div className="hidden sm:block">
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <button type="button" className="rounded-full ring-offset-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2">
                    <Avatar className="h-8 w-8 cursor-pointer">
                      <AvatarImage src={user.avatar_url || undefined} alt={user.github_username} />
                      <AvatarFallback className="text-[10px]">{initials}</AvatarFallback>
                    </Avatar>
                  </button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end" className="w-48">
                  <DropdownMenuLabel className="font-normal">
                    <div className="flex flex-col gap-0.5">
                      <p className="text-sm font-medium">{user.display_name || user.github_username}</p>
                      <p className="text-xs text-muted-foreground">@{user.github_username}</p>
                    </div>
                  </DropdownMenuLabel>
                  <DropdownMenuSeparator />
                  <DropdownMenuItem asChild>
                    <Link href="/settings" className="cursor-pointer gap-2">
                      <Settings className="h-3.5 w-3.5" />
                      Settings
                    </Link>
                  </DropdownMenuItem>
                  <DropdownMenuItem asChild>
                    <Link href="/settings?tab=usage" className="cursor-pointer gap-2">
                      <BarChart3 className="h-3.5 w-3.5" />
                      Usage
                    </Link>
                  </DropdownMenuItem>
                  <DropdownMenuSeparator />
                  <DropdownMenuItem onClick={logout} className="cursor-pointer gap-2 text-muted-foreground focus:text-destructive">
                    <LogOut className="h-3.5 w-3.5" />
                    Log out
                  </DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>
            </div>
          ) : (
            <Button size="sm" variant="outline" onClick={login} className="hidden gap-1.5 sm:flex">
              <Github className="h-3.5 w-3.5" />
              <span className="hidden sm:inline">Sign in</span>
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
            <Link href="/features" className={linkClass("/features")} onClick={() => setMenuOpen(false)}>
              Features
            </Link>
            <Link href="/roadmap" className={linkClass("/roadmap")} onClick={() => setMenuOpen(false)}>
              Roadmap
            </Link>
            <Link href="/pricing" className={linkClass("/pricing")} onClick={() => setMenuOpen(false)}>
              Pricing
            </Link>
            <Link href="/gallery" className={linkClass("/gallery")} onClick={() => setMenuOpen(false)}>
              Gallery
            </Link>
            {user && (
              <Link href="/teams" className={linkClass("/teams")} onClick={() => setMenuOpen(false)}>
                Teams
              </Link>
            )}
            {user && (
              <Link href="/orgs" className={linkClass("/orgs")} onClick={() => setMenuOpen(false)}>
                Orgs
              </Link>
            )}
            {user && (
              <Link href="/settings" className={linkClass("/settings")} onClick={() => setMenuOpen(false)}>
                Settings
              </Link>
            )}
            {loading ? null : user ? (
              <button
                type="button"
                onClick={() => { logout(); setMenuOpen(false); }}
                className="text-left text-sm text-muted-foreground hover:text-foreground"
              >
                Log out
              </button>
            ) : (
              <button
                type="button"
                onClick={() => { login(); setMenuOpen(false); }}
                className="text-left text-sm text-muted-foreground hover:text-foreground"
              >
                Sign in with GitHub
              </button>
            )}
          </div>
        </div>
      )}
    </header>
  );
}
