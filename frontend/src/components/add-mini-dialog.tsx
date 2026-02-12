"use client";

import { useEffect, useState } from "react";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { listMinis, type Mini } from "@/lib/api";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "/api";

interface AddMiniDialogProps {
  teamId: number;
  onAdded: () => void;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function AddMiniDialog({
  teamId,
  onAdded,
  open,
  onOpenChange,
}: AddMiniDialogProps) {
  const [minis, setMinis] = useState<Mini[]>([]);
  const [search, setSearch] = useState("");
  const [role, setRole] = useState<"member" | "lead">("member");
  const [adding, setAdding] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (open) {
      listMinis()
        .then((all) => setMinis(all.filter((m) => m.status === "ready")))
        .catch(() => setMinis([]));
      setSearch("");
      setRole("member");
      setError(null);
    }
  }, [open]);

  const filtered = minis.filter(
    (m) =>
      m.username.toLowerCase().includes(search.toLowerCase()) ||
      (m.display_name || "").toLowerCase().includes(search.toLowerCase())
  );

  const handleAdd = async (mini: Mini) => {
    setAdding(mini.username);
    setError(null);
    const token = localStorage.getItem("minis_token");
    try {
      const res = await fetch(`${API_BASE}/teams/${teamId}/members`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify({ mini_id: mini.id, role }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: "Failed to add member" }));
        throw new Error(err.detail || "Failed to add member");
      }
      onAdded();
      onOpenChange(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to add member");
    } finally {
      setAdding(null);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Add Mini to Team</DialogTitle>
          <DialogDescription>
            Search for a mini to add to your team.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          <Input
            placeholder="Search minis..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="bg-secondary/50"
          />

          <div className="flex items-center gap-2">
            <span className="text-xs text-muted-foreground">Role:</span>
            <button
              type="button"
              onClick={() => setRole("member")}
              className={`rounded-md px-3 py-1 text-xs transition-colors ${
                role === "member"
                  ? "bg-primary text-primary-foreground"
                  : "bg-secondary text-muted-foreground hover:text-foreground"
              }`}
            >
              Member
            </button>
            <button
              type="button"
              onClick={() => setRole("lead")}
              className={`rounded-md px-3 py-1 text-xs transition-colors ${
                role === "lead"
                  ? "bg-primary text-primary-foreground"
                  : "bg-secondary text-muted-foreground hover:text-foreground"
              }`}
            >
              Lead
            </button>
          </div>

          {error && (
            <p className="text-sm text-destructive">{error}</p>
          )}

          <div className="max-h-60 space-y-1 overflow-y-auto">
            {filtered.length === 0 ? (
              <p className="py-4 text-center text-sm text-muted-foreground">
                No minis found.
              </p>
            ) : (
              filtered.map((mini) => (
                <button
                  key={mini.id}
                  type="button"
                  disabled={adding !== null}
                  onClick={() => handleAdd(mini)}
                  className="flex w-full items-center gap-3 rounded-lg px-3 py-2 text-left transition-colors hover:bg-secondary/80 disabled:opacity-50"
                >
                  <Avatar className="h-8 w-8">
                    <AvatarImage src={mini.avatar_url} alt={mini.username} />
                    <AvatarFallback className="font-mono text-xs">
                      {mini.username.slice(0, 2).toUpperCase()}
                    </AvatarFallback>
                  </Avatar>
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm font-medium">
                      {mini.display_name || mini.username}
                    </p>
                    <p className="truncate font-mono text-xs text-muted-foreground">
                      @{mini.username}
                    </p>
                  </div>
                  {adding === mini.username && (
                    <span className="text-xs text-muted-foreground">Adding...</span>
                  )}
                </button>
              ))
            )}
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
