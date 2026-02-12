"use client";

import { useState, useEffect, useCallback } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { Card, CardContent } from "@/components/ui/card";
import { MiniCard } from "@/components/mini-card";
import { listMinis, type Mini } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import {
  ArrowRight,
  Github,
  Users,
  Search,
  Bot,
  Radar,
  Wrench,
  Download,
} from "lucide-react";

function HeroInput() {
  const router = useRouter();
  const [username, setUsername] = useState("");
  const [avatarUrl, setAvatarUrl] = useState<string | null>(null);
  const [avatarLoading, setAvatarLoading] = useState(false);
  const [submitting, setSubmitting] = useState(false);

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
  );
}

const steps = [
  {
    number: "1",
    title: "Enter a Username",
    description: "Point us at any GitHub profile",
  },
  {
    number: "2",
    title: "We Analyze Everything",
    description: "Commits, PRs, reviews, comments, blog posts",
  },
  {
    number: "3",
    title: "Chat with Their Clone",
    description: "An AI that thinks, writes, and argues like them",
  },
];

const highlights = [
  {
    icon: Search,
    title: "Multi-Source Analysis",
    description: "GitHub, Stack Overflow, Hacker News, blogs",
  },
  {
    icon: Bot,
    title: "Agentic Pipeline",
    description: "Explorer agents mine personality from each source",
  },
  {
    icon: Users,
    title: "Team Collaboration",
    description: "Assemble teams of minis for reviews and brainstorms",
  },
  {
    icon: Wrench,
    title: "MCP Integration",
    description: "Use minis as tools in Claude Code",
  },
  {
    icon: Download,
    title: "Subagent Export",
    description: "Export as Claude Code agent definitions",
  },
  {
    icon: Radar,
    title: "Developer Radar",
    description: "Visualize skills, traits, and engineering values",
  },
];

function LandingPage() {
  const { login } = useAuth();
  const [minis, setMinis] = useState<Mini[]>([]);
  const [minisLoading, setMinisLoading] = useState(true);

  useEffect(() => {
    listMinis()
      .then(setMinis)
      .catch(() => setMinis([]))
      .finally(() => setMinisLoading(false));
  }, []);

  const readyMinis = minis.filter((m) => m.status === "ready").slice(0, 6);

  return (
    <div className="flex flex-col items-center">
      {/* Hero */}
      <section className="flex w-full flex-col items-center px-4 pb-20 pt-24 text-center sm:pt-32">
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
        <HeroInput />
      </section>

      {/* How it Works */}
      <section className="w-full border-t border-border/50 py-24">
        <div className="mx-auto max-w-6xl px-4">
          <h2 className="mb-12 text-center text-2xl font-bold tracking-tight sm:text-3xl">
            How it Works
          </h2>
          <div className="grid gap-8 sm:grid-cols-3">
            {steps.map((step) => (
              <div key={step.number} className="text-center">
                <div className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-full bg-gradient-to-r from-chart-1 to-chart-2 font-mono text-lg font-bold text-white">
                  {step.number}
                </div>
                <h3 className="text-base font-medium">{step.title}</h3>
                <p className="mt-1 text-sm text-muted-foreground">
                  {step.description}
                </p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Features Grid */}
      <section className="w-full border-t border-border/50 py-24">
        <div className="mx-auto max-w-6xl px-4">
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {highlights.map((item) => (
              <Card
                key={item.title}
                className="border-border/50 transition-colors hover:border-border"
              >
                <CardContent className="flex items-start gap-4 pt-6">
                  <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-secondary">
                    <item.icon className="h-4 w-4 text-muted-foreground" />
                  </div>
                  <div>
                    <h3 className="text-sm font-medium">{item.title}</h3>
                    <p className="mt-1 text-xs text-muted-foreground">
                      {item.description}
                    </p>
                  </div>
                </CardContent>
              </Card>
            ))}
          </div>
        </div>
      </section>

      {/* Gallery Preview */}
      {!minisLoading && readyMinis.length > 0 && (
        <section className="w-full border-t border-border/50 py-24">
          <div className="mx-auto max-w-6xl px-4">
            <div className="mb-8 flex items-center justify-between">
              <h2 className="text-2xl font-bold tracking-tight">
                See who&apos;s already been cloned
              </h2>
              <Link
                href="/gallery"
                className="text-sm text-muted-foreground transition-colors hover:text-foreground"
              >
                View all &rarr;
              </Link>
            </div>
            <div className="grid gap-4 grid-cols-1 sm:grid-cols-2 lg:grid-cols-3">
              {readyMinis.map((mini) => (
                <MiniCard key={mini.id} mini={mini} />
              ))}
            </div>
          </div>
        </section>
      )}

      {/* Final CTA */}
      <section className="w-full border-t border-border/50 py-24">
        <div className="mx-auto flex max-w-2xl flex-col items-center px-4 text-center">
          <h2 className="text-2xl font-bold tracking-tight sm:text-3xl">
            Ready to clone a developer?
          </h2>
          <p className="mt-3 text-muted-foreground">
            Create your first mini in under a minute.
          </p>
          <Button size="lg" className="mt-8 gap-1.5" onClick={login}>
            Get Started
            <ArrowRight className="h-4 w-4" />
          </Button>
        </div>
      </section>
    </div>
  );
}

function Dashboard() {
  const router = useRouter();
  const { user } = useAuth();
  const [username, setUsername] = useState("");
  const [avatarUrl, setAvatarUrl] = useState<string | null>(null);
  const [avatarLoading, setAvatarLoading] = useState(false);
  const [minis, setMinis] = useState<Mini[]>([]);
  const [minisLoading, setMinisLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [myMini, setMyMini] = useState<Mini | null>(null);

  useEffect(() => {
    if (!user) return;
    import("@/lib/api").then(({ getMiniByUsername }) =>
      getMiniByUsername(user.github_username)
        .then(setMyMini)
        .catch(() => setMyMini(null))
    );
  }, [user]);

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

      {/* Dashboard CTAs */}
      {user && (
        <section className="w-full max-w-6xl px-4 pb-8">
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            <Link
              href={
                myMini
                  ? `/m/${user.github_username}`
                  : `/create?username=${user.github_username}`
              }
              className="group"
            >
              <div className="flex items-center gap-4 rounded-xl border border-chart-1/30 bg-chart-1/5 p-6 transition-all hover:border-chart-1/50">
                <Avatar className="h-12 w-12">
                  <AvatarImage
                    src={user.avatar_url || undefined}
                    alt={user.github_username}
                  />
                  <AvatarFallback className="font-mono">
                    {user.github_username.slice(0, 2).toUpperCase()}
                  </AvatarFallback>
                </Avatar>
                <div>
                  <p className="font-medium">
                    {myMini ? "My Mini" : "Create My Mini"}
                  </p>
                  <p className="text-xs text-muted-foreground">
                    @{user.github_username}
                  </p>
                </div>
              </div>
            </Link>
            <Link href="/teams" className="group">
              <div className="flex items-center gap-4 rounded-xl border border-border/50 p-6 transition-all hover:border-border hover:bg-secondary/30">
                <div className="flex h-12 w-12 items-center justify-center rounded-full bg-secondary">
                  <Users className="h-5 w-5 text-muted-foreground" />
                </div>
                <div>
                  <p className="font-medium">My Teams</p>
                  <p className="text-xs text-muted-foreground">
                    Manage mini rosters
                  </p>
                </div>
              </div>
            </Link>
          </div>
        </section>
      )}

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

export default function Home() {
  const { user, loading } = useAuth();

  if (loading) {
    return (
      <div className="flex min-h-[60vh] items-center justify-center">
        <Skeleton className="h-8 w-48" />
      </div>
    );
  }

  return user ? <Dashboard /> : <LandingPage />;
}
