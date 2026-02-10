"use client";

import { useState, useEffect, useCallback } from "react";
import { useRouter } from "next/navigation";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { MiniCard } from "@/components/mini-card";
import { listMinis, type Mini } from "@/lib/api";
import { ArrowRight, Github } from "lucide-react";

export default function Home() {
  const router = useRouter();
  const [username, setUsername] = useState("");
  const [avatarUrl, setAvatarUrl] = useState<string | null>(null);
  const [avatarLoading, setAvatarLoading] = useState(false);
  const [minis, setMinis] = useState<Mini[]>([]);
  const [minisLoading, setMinisLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);

  // Debounced avatar preview
  useEffect(() => {
    if (!username.trim()) {
      setAvatarUrl(null);
      return;
    }

    setAvatarLoading(true);
    const timeout = setTimeout(() => {
      const img = new Image();
      img.onload = () => {
        setAvatarUrl(`https://github.com/${username}.png`);
        setAvatarLoading(false);
      };
      img.onerror = () => {
        setAvatarUrl(null);
        setAvatarLoading(false);
      };
      img.src = `https://github.com/${username}.png`;
    }, 400);

    return () => clearTimeout(timeout);
  }, [username]);

  // Fetch existing minis
  useEffect(() => {
    listMinis()
      .then(setMinis)
      .catch(() => setMinis([]))
      .finally(() => setMinisLoading(false));
  }, []);

  const handleSubmit = useCallback(
    (e: React.FormEvent) => {
      e.preventDefault();
      if (!username.trim()) return;
      setSubmitting(true);
      router.push(`/create?username=${encodeURIComponent(username.trim())}`);
    },
    [username, router]
  );

  return (
    <div className="flex flex-col items-center">
      {/* Hero */}
      <section className="flex w-full flex-col items-center px-4 pb-16 pt-24 text-center sm:pt-32">
        <h1 className="max-w-2xl text-4xl font-bold tracking-tight sm:text-5xl lg:text-6xl">
          Clone any developer&apos;s{" "}
          <span className="bg-gradient-to-r from-chart-1 to-chart-2 bg-clip-text text-transparent">
            mind
          </span>
        </h1>
        <p className="mt-4 max-w-lg text-base text-muted-foreground sm:text-lg">
          Enter a GitHub username. We&apos;ll mine their commits, PRs, and
          reviews to create an AI that thinks like them.
        </p>

        {/* Input */}
        <form
          onSubmit={handleSubmit}
          className="mt-10 flex w-full max-w-md items-center gap-3"
        >
          <div className="relative flex-1">
            <div className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2">
              {avatarUrl ? (
                <Avatar className="h-6 w-6">
                  <AvatarImage src={avatarUrl} alt={username} />
                  <AvatarFallback className="text-[10px]">
                    <Github className="h-3.5 w-3.5" />
                  </AvatarFallback>
                </Avatar>
              ) : avatarLoading ? (
                <Skeleton className="h-6 w-6 rounded-full" />
              ) : (
                <Github className="h-4 w-4 text-muted-foreground" />
              )}
            </div>
            <Input
              type="text"
              placeholder="GitHub username"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              className="h-12 pl-12 font-mono text-sm"
              autoFocus
            />
          </div>
          <Button
            type="submit"
            size="lg"
            disabled={!username.trim() || submitting}
            className="h-12 gap-1.5"
          >
            Create Mini
            <ArrowRight className="h-4 w-4" />
          </Button>
        </form>
      </section>

      {/* Existing Minis */}
      {(minisLoading || minis.length > 0) && (
        <section className="w-full max-w-6xl px-4 pb-16">
          <h2 className="mb-6 text-sm font-medium uppercase tracking-wider text-muted-foreground">
            Existing Minis
          </h2>
          <div className="grid gap-4 grid-cols-1 sm:grid-cols-2 lg:grid-cols-3">
            {minisLoading
              ? Array.from({ length: 3 }).map((_, i) => (
                  <div key={i} className="space-y-3 rounded-xl border p-6">
                    <div className="flex items-center gap-3">
                      <Skeleton className="h-10 w-10 rounded-full" />
                      <div className="space-y-2">
                        <Skeleton className="h-4 w-24" />
                        <Skeleton className="h-3 w-16" />
                      </div>
                    </div>
                    <Skeleton className="h-8 w-full" />
                  </div>
                ))
              : minis.map((mini) => <MiniCard key={mini.id} mini={mini} />)}
          </div>
        </section>
      )}
    </div>
  );
}
