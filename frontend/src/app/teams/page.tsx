"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { Skeleton } from "@/components/ui/skeleton";
import { Button } from "@/components/ui/button";
import { TeamCard } from "@/components/team-card";
import { AuthGate } from "@/components/auth-gate";
import { Team } from "@/lib/api";
import { Users, Plus } from "lucide-react";

export default function TeamsPage() {
  const [teams, setTeams] = useState<Team[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    import("@/lib/api").then(({ listTeams }) =>
      listTeams()
        .then(setTeams)
        .catch(() => setTeams([]))
        .finally(() => setLoading(false))
    );
  }, []);

  return (
    <AuthGate icon={Users} message="Sign in to manage your teams.">
    <div className="mx-auto max-w-6xl px-4 py-12">
      <div className="mb-8 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">My Teams</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Organize your minis into teams.
          </p>
        </div>
        <Link href="/teams/new">
          <Button size="sm" className="gap-1.5">
            <Plus className="h-3.5 w-3.5" />
            Create Team
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
      ) : teams.length === 0 ? (
        <div className="flex min-h-[40vh] flex-col items-center justify-center gap-4">
          <div className="flex h-16 w-16 items-center justify-center rounded-full bg-secondary">
            <Users className="h-7 w-7 text-muted-foreground" />
          </div>
          <div className="text-center">
            <p className="font-medium text-foreground">No teams yet</p>
            <p className="mt-1 text-sm text-muted-foreground">
              No teams yet. Create one to organize your minis.
            </p>
          </div>
          <Link href="/teams/new">
            <Button className="mt-2 gap-1.5">
              <Plus className="h-3.5 w-3.5" />
              Create Team
            </Button>
          </Link>
        </div>
      ) : (
        <div className="grid gap-4 grid-cols-1 sm:grid-cols-2 lg:grid-cols-3">
          {teams.map((team) => (
            <TeamCard key={team.id} team={team} />
          ))}
        </div>
      )}
    </div>
    </AuthGate>
  );
}
