"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { MiniCard } from "@/components/mini-card";
import { listMinis, type Mini } from "@/lib/api";
import { Search, Users, ArrowUpDown } from "lucide-react";

type SortOption = "newest" | "oldest" | "name";

export default function GalleryPage() {
  const [minis, setMinis] = useState<Mini[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [sort, setSort] = useState<SortOption>("newest");

  useEffect(() => {
    listMinis()
      .then(setMinis)
      .catch(() => setMinis([]))
      .finally(() => setLoading(false));
  }, []);

  return (
    <div className="mx-auto max-w-6xl px-4 py-12">
      <div className="mb-8">
        <h1 className="text-2xl font-bold tracking-tight">Gallery</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Browse all created developer minis.
        </p>
      </div>

      <div className="mb-6 flex gap-3">
        <div className="relative flex-1">
          <div className="pointer-events-none absolute inset-y-0 left-0 flex items-center pl-3">
            <Search className="h-4 w-4 text-muted-foreground" />
          </div>
          <Input
            type="text"
            placeholder="Search minis..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="pl-9"
          />
        </div>
        <div className="relative">
          <div className="pointer-events-none absolute inset-y-0 left-0 flex items-center pl-3">
            <ArrowUpDown className="h-4 w-4 text-muted-foreground" />
          </div>
          <select
            value={sort}
            onChange={(e) => setSort(e.target.value as SortOption)}
            className="h-9 appearance-none rounded-md border border-input bg-background pl-9 pr-8 text-sm ring-offset-background focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2"
          >
            <option value="newest">Newest</option>
            <option value="oldest">Oldest</option>
            <option value="name">Name A-Z</option>
          </select>
        </div>
      </div>

      {loading ? (
        <div className="grid gap-4 grid-cols-1 sm:grid-cols-2 lg:grid-cols-3">
          {Array.from({ length: 6 }).map((_, i) => (
            <div
              key={i}
              className="space-y-3 rounded-xl border border-border/50 p-6"
            >
              <div className="flex items-center gap-3">
                <Skeleton className="h-10 w-10 rounded-full" />
                <div className="space-y-2">
                  <Skeleton className="h-4 w-24" />
                  <Skeleton className="h-3 w-16" />
                </div>
              </div>
              <Skeleton className="h-3 w-full" />
              <Skeleton className="h-3 w-3/4" />
              <div className="flex gap-1.5 pt-1">
                <Skeleton className="h-5 w-16 rounded-full" />
                <Skeleton className="h-5 w-20 rounded-full" />
              </div>
            </div>
          ))}
        </div>
      ) : minis.length === 0 ? (
        <div className="flex min-h-[40vh] flex-col items-center justify-center gap-4">
          <div className="flex h-16 w-16 items-center justify-center rounded-full bg-secondary">
            <Users className="h-7 w-7 text-muted-foreground" />
          </div>
          <div className="text-center">
            <p className="font-medium text-foreground">No minis yet</p>
            <p className="mt-1 text-sm text-muted-foreground">
              Create your first mini by entering a GitHub username.
            </p>
          </div>
          <Link
            href="/"
            className="mt-2 rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90"
          >
            Create a Mini
          </Link>
        </div>
      ) : (
        <div className="grid gap-4 grid-cols-1 sm:grid-cols-2 lg:grid-cols-3">
          {minis
            .filter(
              (m) =>
                m.username.includes(search.toLowerCase()) ||
                m.display_name?.toLowerCase().includes(search.toLowerCase())
            )
            .sort((a, b) => {
              if (sort === "newest")
                return new Date(b.created_at || 0).getTime() - new Date(a.created_at || 0).getTime();
              if (sort === "oldest")
                return new Date(a.created_at || 0).getTime() - new Date(b.created_at || 0).getTime();
              return (a.display_name || a.username).localeCompare(b.display_name || b.username);
            })
            .map((mini) => (
              <MiniCard key={mini.id} mini={mini} />
            ))}
        </div>
      )}
    </div>
  );
}
