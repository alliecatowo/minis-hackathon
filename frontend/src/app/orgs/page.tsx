"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { Skeleton } from "@/components/ui/skeleton";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Building2, Plus, Users } from "lucide-react";

interface OrgSummary {
  id: number;
  name: string;
  display_name: string;
  description: string | null;
  member_count: number;
  created_at: string;
}

export default function OrgsPage() {
  const [orgs, setOrgs] = useState<OrgSummary[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    import("@/lib/api").then(({ listOrgs }) =>
      listOrgs()
        .then(setOrgs)
        .catch(() => setOrgs([]))
        .finally(() => setLoading(false))
    );
  }, []);

  return (
    <div className="mx-auto max-w-6xl px-4 py-12">
      <div className="mb-8 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">My Organizations</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Collaborate with others in shared organizations.
          </p>
        </div>
        <Link href="/orgs/new">
          <Button size="sm" className="gap-1.5">
            <Plus className="h-3.5 w-3.5" />
            Create Org
          </Button>
        </Link>
      </div>

      {loading ? (
        <div className="grid gap-4 grid-cols-1 sm:grid-cols-2 lg:grid-cols-3">
          {Array.from({ length: 3 }).map((_, i) => (
            <div
              key={i}
              className="space-y-3 rounded-xl border border-border/50 p-6"
            >
              <div className="flex items-center gap-3">
                <Skeleton className="h-10 w-10 rounded-full" />
                <div className="space-y-2">
                  <Skeleton className="h-4 w-32" />
                  <Skeleton className="h-3 w-20" />
                </div>
              </div>
              <Skeleton className="h-3 w-full" />
              <Skeleton className="h-5 w-24 rounded-full" />
            </div>
          ))}
        </div>
      ) : orgs.length === 0 ? (
        <div className="flex min-h-[40vh] flex-col items-center justify-center gap-4">
          <div className="flex h-16 w-16 items-center justify-center rounded-full bg-secondary">
            <Building2 className="h-7 w-7 text-muted-foreground" />
          </div>
          <div className="text-center">
            <p className="font-medium text-foreground">No organizations yet</p>
            <p className="mt-1 text-sm text-muted-foreground">
              Create an org or join one with an invite link.
            </p>
          </div>
          <Link href="/orgs/new">
            <Button className="mt-2 gap-1.5">
              <Plus className="h-3.5 w-3.5" />
              Create Organization
            </Button>
          </Link>
        </div>
      ) : (
        <div className="grid gap-4 grid-cols-1 sm:grid-cols-2 lg:grid-cols-3">
          {orgs.map((org) => (
            <Link key={org.id} href={`/orgs/${org.id}`}>
              <Card className="group cursor-pointer border-border/50 transition-all duration-200 hover:border-border hover:bg-card/80 hover:shadow-lg hover:shadow-black/5">
                <CardHeader className="flex-row items-center gap-3">
                  <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-secondary">
                    <Building2 className="h-5 w-5 text-muted-foreground" />
                  </div>
                  <div className="min-w-0 flex-1">
                    <span className="truncate text-sm font-medium">
                      {org.display_name}
                    </span>
                    <p className="truncate font-mono text-xs text-muted-foreground">
                      {org.name}
                    </p>
                  </div>
                </CardHeader>
                <CardContent>
                  <p className="line-clamp-2 text-sm text-muted-foreground">
                    {org.description || "No description."}
                  </p>
                  <div className="mt-3 flex items-center gap-2">
                    <Badge variant="outline" className="text-[10px]">
                      <Users className="mr-1 h-3 w-3" />
                      {org.member_count} {org.member_count === 1 ? "member" : "members"}
                    </Badge>
                  </div>
                </CardContent>
              </Card>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
