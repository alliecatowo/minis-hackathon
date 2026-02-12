"use client";

import { useEffect, useState, useCallback } from "react";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Separator } from "@/components/ui/separator";
import { Skeleton } from "@/components/ui/skeleton";
import { useAuth } from "@/lib/auth";
import {
  ArrowLeft,
  Building2,
  Check,
  ClipboardCopy,
  Plus,
  Settings,
  Trash2,
  Users,
  X,
} from "lucide-react";

type Tab = "members" | "teams" | "settings";

interface OrgMember {
  user_id: number;
  username: string;
  display_name: string | null;
  avatar_url: string | null;
  role: string;
  joined_at: string;
}

interface OrgTeam {
  id: number;
  name: string;
  description: string | null;
  member_count: number;
}

interface OrgDetail {
  id: number;
  name: string;
  display_name: string;
  description: string | null;
  owner_id: number;
  created_at: string;
  members?: OrgMember[];
}

export default function OrgDetailPage() {
  const params = useParams();
  const router = useRouter();
  const orgId = Number(params.id);
  const { user } = useAuth();

  const [org, setOrg] = useState<OrgDetail | null>(null);
  const [members, setMembers] = useState<OrgMember[]>([]);
  const [teams, setTeams] = useState<OrgTeam[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<Tab>("members");

  // Members state
  const [removing, setRemoving] = useState<number | null>(null);

  // Teams state
  const [showNewTeam, setShowNewTeam] = useState(false);
  const [newTeamName, setNewTeamName] = useState("");
  const [newTeamDesc, setNewTeamDesc] = useState("");
  const [creatingTeam, setCreatingTeam] = useState(false);

  // Settings state
  const [editDisplayName, setEditDisplayName] = useState("");
  const [editDescription, setEditDescription] = useState("");
  const [saving, setSaving] = useState(false);
  const [inviteCode, setInviteCode] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [generatingInvite, setGeneratingInvite] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);

  const fetchOrg = useCallback(async () => {
    try {
      const { getOrg, listOrgMembers, listOrgTeams } = await import("@/lib/api");
      const [orgData, membersData, teamsData] = await Promise.all([
        getOrg(orgId),
        listOrgMembers(orgId).catch(() => []),
        listOrgTeams(orgId).catch(() => []),
      ]);
      setOrg(orgData);
      setMembers(orgData.members ?? membersData);
      setTeams(teamsData);
      setEditDisplayName(orgData.display_name);
      setEditDescription(orgData.description || "");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load organization");
    } finally {
      setLoading(false);
    }
  }, [orgId]);

  useEffect(() => {
    fetchOrg();
  }, [fetchOrg]);

  const isOwner = !!user && !!org && user.id === org.owner_id;

  const handleRemoveMember = async (userId: number) => {
    setRemoving(userId);
    try {
      const { removeOrgMember } = await import("@/lib/api");
      await removeOrgMember(orgId, userId);
      await fetchOrg();
    } catch {
      // Could show toast
    } finally {
      setRemoving(null);
    }
  };

  const handleCreateTeam = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newTeamName.trim()) return;
    setCreatingTeam(true);
    try {
      const { createOrgTeam } = await import("@/lib/api");
      await createOrgTeam(orgId, {
        name: newTeamName.trim(),
        ...(newTeamDesc.trim() && { description: newTeamDesc.trim() }),
      });
      setNewTeamName("");
      setNewTeamDesc("");
      setShowNewTeam(false);
      await fetchOrg();
    } catch {
      // Could show toast
    } finally {
      setCreatingTeam(false);
    }
  };

  const handleSaveSettings = async () => {
    setSaving(true);
    try {
      const { updateOrg } = await import("@/lib/api");
      await updateOrg(orgId, {
        display_name: editDisplayName.trim(),
        description: editDescription.trim() || undefined,
      });
      await fetchOrg();
    } catch {
      // Could show toast
    } finally {
      setSaving(false);
    }
  };

  const handleGenerateInvite = async () => {
    setGeneratingInvite(true);
    try {
      const { generateInvite } = await import("@/lib/api");
      const result = await generateInvite(orgId);
      setInviteCode(result.invite_code);
    } catch {
      // Could show toast
    } finally {
      setGeneratingInvite(false);
    }
  };

  const handleCopyInvite = () => {
    if (!inviteCode) return;
    const inviteUrl = `${window.location.origin}/orgs/join/${inviteCode}`;
    navigator.clipboard.writeText(inviteUrl);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const handleDelete = async () => {
    setDeleting(true);
    try {
      const { deleteOrg } = await import("@/lib/api");
      await deleteOrg(orgId);
      router.push("/orgs");
    } catch {
      setDeleting(false);
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

  if (error || !org) {
    return (
      <div className="mx-auto max-w-4xl px-4 py-12">
        <Link
          href="/orgs"
          className="mb-6 inline-flex items-center gap-1.5 text-sm text-muted-foreground transition-colors hover:text-foreground"
        >
          <ArrowLeft className="h-4 w-4" />
          Back to Organizations
        </Link>
        <div className="flex min-h-[40vh] flex-col items-center justify-center">
          <p className="text-sm text-destructive">{error || "Organization not found"}</p>
        </div>
      </div>
    );
  }

  const tabs: { key: Tab; label: string; icon: React.ReactNode }[] = [
    { key: "members", label: "Members", icon: <Users className="h-4 w-4" /> },
    { key: "teams", label: "Teams", icon: <Building2 className="h-4 w-4" /> },
    ...(isOwner
      ? [{ key: "settings" as Tab, label: "Settings", icon: <Settings className="h-4 w-4" /> }]
      : []),
  ];

  return (
    <div className="mx-auto max-w-4xl px-4 py-12">
      <Link
        href="/orgs"
        className="mb-6 inline-flex items-center gap-1.5 text-sm text-muted-foreground transition-colors hover:text-foreground"
      >
        <ArrowLeft className="h-4 w-4" />
        Back to Organizations
      </Link>

      <div className="mb-8">
        <h1 className="text-2xl font-bold tracking-tight">{org.display_name}</h1>
        {org.description && (
          <p className="mt-1 text-sm text-muted-foreground">{org.description}</p>
        )}
        <p className="mt-2 font-mono text-xs text-muted-foreground">{org.name}</p>
      </div>

      {/* Tabs */}
      <div className="mb-6 flex gap-1 rounded-lg bg-secondary/50 p-1">
        {tabs.map((tab) => (
          <button
            key={tab.key}
            type="button"
            onClick={() => setActiveTab(tab.key)}
            className={`flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm transition-colors ${
              activeTab === tab.key
                ? "bg-background font-medium text-foreground shadow-sm"
                : "text-muted-foreground hover:text-foreground"
            }`}
          >
            {tab.icon}
            {tab.label}
          </button>
        ))}
      </div>

      {/* Members Tab */}
      {activeTab === "members" && (
        <div>
          {members.length === 0 ? (
            <div className="flex min-h-[30vh] flex-col items-center justify-center gap-4">
              <div className="flex h-16 w-16 items-center justify-center rounded-full bg-secondary">
                <Users className="h-7 w-7 text-muted-foreground" />
              </div>
              <div className="text-center">
                <p className="font-medium text-foreground">No members yet</p>
                <p className="mt-1 text-sm text-muted-foreground">
                  Invite people to join your organization.
                </p>
              </div>
            </div>
          ) : (
            <div className="grid gap-4 grid-cols-1 sm:grid-cols-2 lg:grid-cols-3">
              {members.map((member) => (
                <div
                  key={member.user_id}
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
                        <span className="truncate text-sm font-medium">
                          {member.display_name || member.username}
                        </span>
                        <Badge
                          variant="secondary"
                          className={`shrink-0 text-[10px] ${
                            member.role === "owner"
                              ? "bg-amber-500/20 text-amber-400"
                              : member.role === "admin"
                                ? "bg-blue-500/20 text-blue-400"
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
                    {isOwner && member.role !== "owner" && (
                      <button
                        type="button"
                        onClick={() => handleRemoveMember(member.user_id)}
                        disabled={removing === member.user_id}
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
        </div>
      )}

      {/* Teams Tab */}
      {activeTab === "teams" && (
        <div>
          {isOwner && (
            <div className="mb-4">
              {showNewTeam ? (
                <form onSubmit={handleCreateTeam} className="rounded-xl border border-border/50 p-4 space-y-3">
                  <Input
                    value={newTeamName}
                    onChange={(e) => setNewTeamName(e.target.value)}
                    placeholder="Team name"
                    className="bg-secondary/50"
                    required
                  />
                  <Input
                    value={newTeamDesc}
                    onChange={(e) => setNewTeamDesc(e.target.value)}
                    placeholder="Description (optional)"
                    className="bg-secondary/50"
                  />
                  <div className="flex items-center gap-2">
                    <Button type="submit" size="sm" disabled={creatingTeam || !newTeamName.trim()}>
                      {creatingTeam ? "Creating..." : "Create"}
                    </Button>
                    <Button
                      type="button"
                      size="sm"
                      variant="ghost"
                      onClick={() => setShowNewTeam(false)}
                    >
                      Cancel
                    </Button>
                  </div>
                </form>
              ) : (
                <Button
                  size="sm"
                  className="gap-1.5"
                  onClick={() => setShowNewTeam(true)}
                >
                  <Plus className="h-3.5 w-3.5" />
                  Create Team
                </Button>
              )}
            </div>
          )}

          {teams.length === 0 && !showNewTeam ? (
            <div className="flex min-h-[30vh] flex-col items-center justify-center gap-4">
              <div className="flex h-16 w-16 items-center justify-center rounded-full bg-secondary">
                <Building2 className="h-7 w-7 text-muted-foreground" />
              </div>
              <div className="text-center">
                <p className="font-medium text-foreground">No teams yet</p>
                <p className="mt-1 text-sm text-muted-foreground">
                  Create teams within your organization.
                </p>
              </div>
            </div>
          ) : (
            <div className="grid gap-4 grid-cols-1 sm:grid-cols-2 lg:grid-cols-3">
              {teams.map((team) => (
                <Link key={team.id} href={`/teams/${team.id}`}>
                  <div className="group rounded-xl border border-border/50 p-4 transition-colors hover:border-border cursor-pointer">
                    <div className="flex items-center gap-3">
                      <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-secondary">
                        <Users className="h-5 w-5 text-muted-foreground" />
                      </div>
                      <div className="min-w-0 flex-1">
                        <span className="truncate text-sm font-medium">
                          {team.name}
                        </span>
                        <p className="truncate text-xs text-muted-foreground">
                          {team.description || "No description"}
                        </p>
                      </div>
                    </div>
                    <div className="mt-3">
                      <Badge variant="outline" className="text-[10px]">
                        <Users className="mr-1 h-3 w-3" />
                        {team.member_count ?? 0} members
                      </Badge>
                    </div>
                  </div>
                </Link>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Settings Tab */}
      {activeTab === "settings" && isOwner && (
        <div className="space-y-8">
          {/* Edit Org */}
          <div className="space-y-4">
            <h2 className="text-lg font-semibold">General</h2>
            <div className="space-y-3">
              <div className="space-y-2">
                <label htmlFor="editDisplayName" className="text-sm font-medium">
                  Display Name
                </label>
                <Input
                  id="editDisplayName"
                  value={editDisplayName}
                  onChange={(e) => setEditDisplayName(e.target.value)}
                  className="bg-secondary/50"
                />
              </div>
              <div className="space-y-2">
                <label htmlFor="editDescription" className="text-sm font-medium">
                  Description
                </label>
                <textarea
                  id="editDescription"
                  value={editDescription}
                  onChange={(e) => setEditDescription(e.target.value)}
                  rows={3}
                  className="flex w-full rounded-md border border-input bg-secondary/50 px-3 py-2 text-sm ring-offset-background placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
                />
              </div>
              <Button
                size="sm"
                onClick={handleSaveSettings}
                disabled={saving || !editDisplayName.trim()}
              >
                {saving ? "Saving..." : "Save Changes"}
              </Button>
            </div>
          </div>

          <Separator />

          {/* Invite Link */}
          <div className="space-y-4">
            <h2 className="text-lg font-semibold">Invite Members</h2>
            <p className="text-sm text-muted-foreground">
              Generate an invite link to share with others.
            </p>
            {inviteCode ? (
              <div className="flex items-center gap-2">
                <Input
                  readOnly
                  value={`${typeof window !== "undefined" ? window.location.origin : ""}/orgs/join/${inviteCode}`}
                  className="bg-secondary/50 font-mono text-xs"
                />
                <Button
                  size="sm"
                  variant="outline"
                  className="shrink-0 gap-1.5"
                  onClick={handleCopyInvite}
                >
                  {copied ? (
                    <>
                      <Check className="h-3.5 w-3.5" />
                      Copied
                    </>
                  ) : (
                    <>
                      <ClipboardCopy className="h-3.5 w-3.5" />
                      Copy
                    </>
                  )}
                </Button>
              </div>
            ) : (
              <Button
                size="sm"
                variant="outline"
                onClick={handleGenerateInvite}
                disabled={generatingInvite}
              >
                {generatingInvite ? "Generating..." : "Generate Invite Link"}
              </Button>
            )}
          </div>

          <Separator />

          {/* Danger Zone */}
          <div className="space-y-4">
            <h2 className="text-lg font-semibold text-destructive">Danger Zone</h2>
            <p className="text-sm text-muted-foreground">
              Permanently delete this organization. This action cannot be undone.
            </p>
            {confirmDelete ? (
              <div className="flex items-center gap-2">
                <Button
                  size="sm"
                  variant="destructive"
                  onClick={handleDelete}
                  disabled={deleting}
                  className="gap-1.5"
                >
                  <Trash2 className="h-3.5 w-3.5" />
                  {deleting ? "Deleting..." : "Yes, Delete"}
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => setConfirmDelete(false)}
                >
                  Cancel
                </Button>
              </div>
            ) : (
              <Button
                size="sm"
                variant="destructive"
                onClick={() => setConfirmDelete(true)}
                className="gap-1.5"
              >
                <Trash2 className="h-3.5 w-3.5" />
                Delete Organization
              </Button>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
