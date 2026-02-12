"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ArrowLeft } from "lucide-react";

function slugify(text: string): string {
  return text
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
}

export default function NewOrgPage() {
  const router = useRouter();
  const [displayName, setDisplayName] = useState("");
  const [name, setName] = useState("");
  const [nameEdited, setNameEdited] = useState(false);
  const [description, setDescription] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleDisplayNameChange = (value: string) => {
    setDisplayName(value);
    if (!nameEdited) {
      setName(slugify(value));
    }
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!name.trim() || !displayName.trim()) return;

    setSubmitting(true);
    setError(null);

    try {
      const { createOrg } = await import("@/lib/api");
      const org = await createOrg({
        name: name.trim(),
        display_name: displayName.trim(),
        ...(description.trim() && { description: description.trim() }),
      });
      router.push(`/orgs/${org.id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create organization");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="mx-auto max-w-lg px-4 py-12">
      <Link
        href="/orgs"
        className="mb-6 inline-flex items-center gap-1.5 text-sm text-muted-foreground transition-colors hover:text-foreground"
      >
        <ArrowLeft className="h-4 w-4" />
        Back to Organizations
      </Link>

      <h1 className="text-2xl font-bold tracking-tight">Create Organization</h1>
      <p className="mt-1 text-sm text-muted-foreground">
        Set up a new organization to collaborate with others.
      </p>

      <form onSubmit={handleSubmit} className="mt-8 space-y-6">
        <div className="space-y-2">
          <label htmlFor="displayName" className="text-sm font-medium">
            Display Name
          </label>
          <Input
            id="displayName"
            value={displayName}
            onChange={(e) => handleDisplayNameChange(e.target.value)}
            placeholder="My Organization"
            required
            className="bg-secondary/50"
          />
        </div>

        <div className="space-y-2">
          <label htmlFor="name" className="text-sm font-medium">
            Slug
            <span className="ml-1 text-muted-foreground">(URL-friendly identifier)</span>
          </label>
          <Input
            id="name"
            value={name}
            onChange={(e) => {
              setName(e.target.value);
              setNameEdited(true);
            }}
            placeholder="my-organization"
            required
            className="bg-secondary/50 font-mono text-sm"
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
            placeholder="What is this organization about?"
            rows={3}
            className="flex w-full rounded-md border border-input bg-secondary/50 px-3 py-2 text-sm ring-offset-background placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
          />
        </div>

        {error && (
          <p className="text-sm text-destructive">{error}</p>
        )}

        <div className="flex items-center gap-3">
          <Button type="submit" disabled={submitting || !name.trim() || !displayName.trim()}>
            {submitting ? "Creating..." : "Create Organization"}
          </Button>
          <Link href="/orgs">
            <Button type="button" variant="ghost">
              Cancel
            </Button>
          </Link>
        </div>
      </form>
    </div>
  );
}
