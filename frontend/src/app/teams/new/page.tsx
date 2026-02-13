"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { AuthGate } from "@/components/auth-gate";
import { ArrowLeft, Users } from "lucide-react";

function NewTeamForm() {
  const router = useRouter();
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!name.trim()) return;

    setSubmitting(true);
    setError(null);

    try {
      const { createTeam } = await import("@/lib/api");
      const team = await createTeam(name.trim(), description.trim() || undefined);
      router.push(`/teams/${team.id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create team");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="mx-auto max-w-lg px-4 py-12">
      <Link
        href="/teams"
        className="mb-6 inline-flex items-center gap-1.5 text-sm text-muted-foreground transition-colors hover:text-foreground"
      >
        <ArrowLeft className="h-4 w-4" />
        Back to Teams
      </Link>

      <h1 className="text-2xl font-bold tracking-tight">Create Team</h1>
      <p className="mt-1 text-sm text-muted-foreground">
        Organize your minis into a team.
      </p>

      <form onSubmit={handleSubmit} className="mt-8 space-y-6">
        <div className="space-y-2">
          <label htmlFor="name" className="text-sm font-medium">
            Team Name
          </label>
          <Input
            id="name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="My Dream Team"
            required
            className="bg-secondary/50"
          />
        </div>

        <div className="space-y-2">
          <label htmlFor="description" className="text-sm font-medium">
            Description
            <span className="ml-1 text-muted-foreground">(optional)</span>
          </label>
          <textarea
            id="description"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder="What is this team about?"
            rows={3}
            className="flex w-full rounded-md border border-input bg-secondary/50 px-3 py-2 text-sm ring-offset-background placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
          />
        </div>

        {error && (
          <p className="text-sm text-destructive">{error}</p>
        )}

        <div className="flex items-center gap-3">
          <Button type="submit" disabled={submitting || !name.trim()}>
            {submitting ? "Creating..." : "Create Team"}
          </Button>
          <Link href="/teams">
            <Button type="button" variant="ghost">
              Cancel
            </Button>
          </Link>
        </div>
      </form>
    </div>
  );
}

export default function NewTeamPage() {
  return (
    <AuthGate icon={Users} message="Sign in to create a team.">
      <NewTeamForm />
    </AuthGate>
  );
}
