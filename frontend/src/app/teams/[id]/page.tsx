"use client";

import { useEffect, useState, useCallback } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { AddMiniDialog } from "@/components/add-mini-dialog";
import { ArrowLeft, Plus, X, Users } from "lucide-react";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "/api";

interface TeamMember {
  username: string;
  role: string;
  display_name: string | null;
  avatar_url: string | null;
  added_at: string;
}

interface TeamDetail {
  id: number;
  name: string;
  description: string | null;
  owner_username: string;
  members: TeamMember[];
  created_at: string;
}

export default function TeamDetailPage() {
  const params = useParams();
  const teamId = Number(params.id);

  const [team, setTeam] = useState<TeamDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [removing, setRemoving] = useState<string | null>(null);

  const fetchTeam = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/teams/${teamId}`);
      if (!res.ok) throw new Error("Team not found");
      const data = await res.json();
      setTeam(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load team");
    } finally {
      setLoading(false);
    }
  }, [teamId]);

  useEffect(() => {
    fetchTeam();
  }, [fetchTeam]);

  const isOwner = (() => {
    if (!team) return false;
    // Check if the logged-in user is the owner
    // We compare with stored username if available
    const token = localStorage.getItem("minis_token");
    const storedUser = localStorage.getItem("minis_username");
    return !!token && storedUser === team.owner_username;
  })();

  const handleRemove = async (username: string) => {
    setRemoving(username);
    const token = localStorage.getItem("minis_token");
    try {
      const res = await fetch(
        `${API_BASE}/teams/${teamId}/members/${username}`,
        {
          method: "DELETE",
          headers: token ? { Authorization: `Bearer ${token}` } : {},
        }
      );
      if (!res.ok) throw new Error("Failed to remove member");
      await fetchTeam();
    } catch {
      // Silently fail, could show toast
    } finally {
      setRemoving(null);
    }
  };

  if (loading) {
    return (
      <div className="mx-auto max-w-4xl px-4 py-12">
        <Skeleton className="mb-6 h-4 w-24" />
        <Skeleton className="mb-2 h-8 w-48" />
        <Skeleton className="mb-8 h-4 w-64" />
        <div className="grid gap-4 grid-cols-1 sm:grid-cols-2 lg:grid-cols-3">
          {Array.from({ length: 3 }).map((_, i) => (
            <div key={i} className="rounded-xl border border-border/50 p-4">
              <div className="flex items-center gap-3">
                <Skeleton className="h-10 w-10 rounded-full" />
                <div className="space-y-2">
                  <Skeleton className="h-4 w-24" />
                  <Skeleton className="h-3 w-16" />
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>
    );
  }

  if (error || !team) {
    return (
      <div className="mx-auto max-w-4xl px-4 py-12">
        <Link
          href="/teams"
          className="mb-6 inline-flex items-center gap-1.5 text-sm text-muted-foreground transition-colors hover:text-foreground"
        >
          <ArrowLeft className="h-4 w-4" />
          Back to Teams
        </Link>
        <div className="flex min-h-[40vh] flex-col items-center justify-center">
          <p className="text-sm text-destructive">{error || "Team not found"}</p>
        </div>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-4xl px-4 py-12">
      <Link
        href="/teams"
        className="mb-6 inline-flex items-center gap-1.5 text-sm text-muted-foreground transition-colors hover:text-foreground"
      >
        <ArrowLeft className="h-4 w-4" />
        Back to Teams
      </Link>

      <div className="mb-8 flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">{team.name}</h1>
          {team.description && (
            <p className="mt-1 text-sm text-muted-foreground">
              {team.description}
            </p>
          )}
          <p className="mt-2 font-mono text-xs text-muted-foreground">
            by @{team.owner_username}
          </p>
        </div>
        {isOwner && (
          <Button
            size="sm"
            className="gap-1.5"
            onClick={() => setDialogOpen(true)}
          >
            <Plus className="h-3.5 w-3.5" />
            Add Mini
          </Button>
        )}
      </div>

      {team.members.length === 0 ? (
        <div className="flex min-h-[30vh] flex-col items-center justify-center gap-4">
          <div className="flex h-16 w-16 items-center justify-center rounded-full bg-secondary">
            <Users className="h-7 w-7 text-muted-foreground" />
          </div>
          <div className="text-center">
            <p className="font-medium text-foreground">No members yet</p>
            <p className="mt-1 text-sm text-muted-foreground">
              Add minis to your team to get started.
            </p>
          </div>
          {isOwner && (
            <Button
              className="mt-2 gap-1.5"
              onClick={() => setDialogOpen(true)}
            >
              <Plus className="h-3.5 w-3.5" />
              Add Mini
            </Button>
          )}
        </div>
      ) : (
        <div className="grid gap-4 grid-cols-1 sm:grid-cols-2 lg:grid-cols-3">
          {team.members.map((member) => (
            <div
              key={member.username}
              className="group relative rounded-xl border border-border/50 p-4 transition-colors hover:border-border"
            >
              <div className="flex items-center gap-3">
                <Avatar className="h-10 w-10">
                  <AvatarImage
                    src={member.avatar_url || undefined}
                    alt={member.username}
                  />
                  <AvatarFallback className="font-mono text-xs">
                    {member.username.slice(0, 2).toUpperCase()}
                  </AvatarFallback>
                </Avatar>
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <Link
                      href={`/m/${member.username}`}
                      className="truncate text-sm font-medium hover:underline"
                    >
                      {member.display_name || member.username}
                    </Link>
                    <Badge
                      variant="secondary"
                      className={`shrink-0 text-[10px] ${
                        member.role === "lead"
                          ? "bg-amber-500/20 text-amber-400"
                          : "bg-secondary text-muted-foreground"
                      }`}
                    >
                      {member.role}
                    </Badge>
                  </div>
                  <p className="truncate font-mono text-xs text-muted-foreground">
                    @{member.username}
                  </p>
                </div>
                {isOwner && (
                  <button
                    type="button"
                    onClick={() => handleRemove(member.username)}
                    disabled={removing === member.username}
                    className="shrink-0 rounded-md p-1 text-muted-foreground opacity-0 transition-all hover:bg-destructive/10 hover:text-destructive group-hover:opacity-100 disabled:opacity-50"
                    title="Remove member"
                  >
                    <X className="h-4 w-4" />
                  </button>
                )}
              </div>
            </div>
          ))}
        </div>
      )}

      <AddMiniDialog
        teamId={teamId}
        open={dialogOpen}
        onOpenChange={setDialogOpen}
        onAdded={() => fetchTeam()}
      />
    </div>
  );
}
