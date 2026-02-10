"use client";

import { useEffect, useState } from "react";
import { Skeleton } from "@/components/ui/skeleton";
import { MiniCard } from "@/components/mini-card";
import { listMinis, type Mini } from "@/lib/api";

export default function GalleryPage() {
  const [minis, setMinis] = useState<Mini[]>([]);
  const [loading, setLoading] = useState(true);

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

      {loading ? (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {Array.from({ length: 6 }).map((_, i) => (
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
          ))}
        </div>
      ) : minis.length === 0 ? (
        <div className="flex min-h-[40vh] items-center justify-center">
          <p className="text-muted-foreground">
            No minis yet. Create one from the home page!
          </p>
        </div>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {minis.map((mini) => (
            <MiniCard key={mini.id} mini={mini} />
          ))}
        </div>
      )}
    </div>
  );
}
