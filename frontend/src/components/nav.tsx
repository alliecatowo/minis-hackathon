"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Button } from "@/components/ui/button";
import { Plus } from "lucide-react";
import { cn } from "@/lib/utils";

export function Nav() {
  const pathname = usePathname();

  return (
    <header className="sticky top-0 z-50 h-14 border-b border-border/50 bg-background/80 backdrop-blur-sm">
      <div className="mx-auto flex h-full max-w-6xl items-center justify-between px-4">
        <div className="flex items-center gap-6">
          <Link
            href="/"
            className="font-mono text-lg font-bold tracking-tight"
          >
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
          </nav>
        </div>
        <Link href="/">
          <Button size="sm" variant="outline" className="gap-1.5">
            <Plus className="h-3.5 w-3.5" />
            <span className="hidden sm:inline">New Mini</span>
          </Button>
        </Link>
      </div>
    </header>
  );
}
