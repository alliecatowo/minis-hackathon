const API_BASE = "/api/proxy";

export interface Value {
  name: string;
  description: string;
  intensity: number;
}

export interface Mini {
  id: string;
  username: string;
  owner_id: string | null;
  visibility: "public" | "private" | "team";
  display_name: string;
  avatar_url: string;
  bio: string;
  spirit_content: string;
  system_prompt: string;
  values: Value[];
  status: "pending" | "processing" | "ready" | "failed";
  sources_used?: string | string[];
  roles?: { primary: string; secondary: string[] };
  skills?: string[];
  traits?: string[];
  created_at?: string;
}

export interface ChatMessage {
  role: "user" | "assistant";
  content: string;
  toolCalls?: Array<{ tool: string; args: Record<string, string>; result?: string }>;
}

export interface PipelineEvent {
  stage: string;
  message: string;
  progress: number;
}

export interface SourceInfo {
  id: string;
  name: string;
  description: string;
  available: boolean;
}

export async function getSources(): Promise<SourceInfo[]> {
  const res = await fetch(`${API_BASE}/minis/sources`);
  if (!res.ok) {
    return [
      { id: "github", name: "GitHub", description: "Commits, PRs, and reviews", available: true },
      { id: "claude_code", name: "Claude Code", description: "Conversation history", available: false },
    ];
  }
  return res.json();
}

export async function createMini(
  username: string,
  sources?: string[],
  sourceIdentifiers?: Record<string, string>,
): Promise<Mini> {
  const res = await fetch(`${API_BASE}/minis`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      username,
      ...(sources && { sources }),
      ...(sourceIdentifiers && Object.keys(sourceIdentifiers).length > 0 && {
        source_identifiers: sourceIdentifiers,
      }),
    }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: "Failed to create mini" }));
    throw new Error(err.detail || "Failed to create mini");
  }
  return res.json();
}

export async function getMiniById(id: string): Promise<Mini> {
  const res = await fetch(`${API_BASE}/minis/${id}`);
  if (!res.ok) {
    throw new Error("Failed to fetch mini");
  }
  return res.json();
}

export async function getMiniByUsername(username: string): Promise<Mini> {
  const res = await fetch(`${API_BASE}/minis/by-username/${username}`);
  if (!res.ok) {
    throw new Error("Failed to fetch mini");
  }
  return res.json();
}

/** @deprecated Use getMiniByUsername instead */
export const getMini = getMiniByUsername;

export async function getPromoMini(): Promise<Mini | null> {
  const res = await fetch(`${API_BASE}/minis/promo`);
  if (!res.ok) return null;
  return res.json();
}

export async function listMinis(): Promise<Mini[]> {
  const res = await fetch(`${API_BASE}/minis`);
  if (!res.ok) {
    throw new Error("Failed to fetch minis");
  }
  return res.json();
}

export async function getMyMinis(): Promise<Mini[]> {
  const res = await fetch(`${API_BASE}/minis?mine=true`);
  if (!res.ok) {
    throw new Error("Failed to fetch your minis");
  }
  return res.json();
}

export async function deleteMini(id: string): Promise<void> {
  const res = await fetch(`${API_BASE}/minis/${id}`, {
    method: "DELETE",
  });
  if (!res.ok) throw new Error("Failed to delete mini");
}

export function subscribePipelineStatus(id: string): EventSource {
  return new EventSource(`${API_BASE}/minis/${id}/status`);
}

export function streamChat(
  id: string,
  message: string,
): EventSource {
  const es = new EventSource(
    `${API_BASE}/minis/${id}/chat?message=${encodeURIComponent(message)}`
  );
  return es;
}

export async function fetchChatStream(
  id: string,
  message: string,
  history: ChatMessage[],
): Promise<Response> {
  return fetch(`${API_BASE}/minis/${id}/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message, history }),
  });
}

// --- Settings API functions ---

export interface UserSettings {
  llm_provider: string;
  preferred_model: string | null;
  has_api_key: boolean;
  is_admin: boolean;
}

export interface UsageInfo {
  mini_creates_today: number;
  mini_create_limit: number;
  chat_messages_today: number;
  chat_message_limit: number;
  is_exempt: boolean;
}

export interface ModelInfo {
  id: string;
  name: string;
}

export async function getSettings(): Promise<UserSettings> {
  const res = await fetch(`${API_BASE}/settings`);
  if (!res.ok) throw new Error("Failed to fetch settings");
  return res.json();
}

export async function updateSettings(data: {
  llm_api_key?: string;
  llm_provider?: string;
  preferred_model?: string;
}): Promise<UserSettings> {
  const res = await fetch(`${API_BASE}/settings`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  if (!res.ok) throw new Error("Failed to update settings");
  return res.json();
}

export async function getUsage(): Promise<UsageInfo> {
  const res = await fetch(`${API_BASE}/settings/usage`);
  if (!res.ok) throw new Error("Failed to fetch usage");
  return res.json();
}

export async function getAvailableModels(): Promise<Record<string, ModelInfo[]>> {
  const res = await fetch(`${API_BASE}/settings/models`);
  if (!res.ok) throw new Error("Failed to fetch models");
  return res.json();
}

// --- Mini repo API functions ---

export interface RepoInfo {
  name: string;
  full_name: string;
  language: string | null;
  stars: number;
  description: string | null;
  included: boolean;
}

export async function getMiniRepos(miniId: string): Promise<RepoInfo[]> {
  const res = await fetch(`${API_BASE}/minis/${miniId}/repos`);
  if (!res.ok) return [];
  return res.json();
}

export async function createMiniWithExclusions(
  username: string,
  sources: string[],
  excludedRepos: string[],
  sourceIdentifiers?: Record<string, string>,
): Promise<Mini> {
  const res = await fetch(`${API_BASE}/minis`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      username,
      sources,
      excluded_repos: excludedRepos,
      ...(sourceIdentifiers && Object.keys(sourceIdentifiers).length > 0 && {
        source_identifiers: sourceIdentifiers,
      }),
    }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: "Failed to create mini" }));
    throw new Error(err.detail || "Failed to create mini");
  }
  return res.json();
}

// --- Upload API functions ---

export async function uploadClaudeCode(files: File[]): Promise<{ files_saved: number; total_size: number }> {
  const formData = new FormData();
  files.forEach((f) => formData.append("files", f));

  const res = await fetch(`${API_BASE}/upload/claude-code`, {
    method: "POST",
    body: formData,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: "Upload failed" }));
    throw new Error(err.detail || "Upload failed");
  }
  return res.json();
}

// --- Team API functions ---

export interface Team {
  id: string;
  name: string;
  description: string | null;
  member_count: number;
  owner_username: string;
  created_at: string;
}

export interface TeamMember {
  mini_id: string;
  role: string;
}

export async function createTeam(name: string, description?: string): Promise<Team> {
  const res = await fetch(`${API_BASE}/teams`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, ...(description && { description }) }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: "Failed to create team" }));
    throw new Error(err.detail || "Failed to create team");
  }
  return res.json();
}

export async function listTeams(): Promise<Team[]> {
  const res = await fetch(`${API_BASE}/teams`);
  if (!res.ok) throw new Error("Failed to fetch teams");
  return res.json();
}

export async function getTeam(id: string): Promise<Team> {
  const res = await fetch(`${API_BASE}/teams/${id}`);
  if (!res.ok) throw new Error("Failed to fetch team");
  return res.json();
}

export async function updateTeam(id: string, data: { name?: string; description?: string }): Promise<Team> {
  const res = await fetch(`${API_BASE}/teams/${id}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  if (!res.ok) throw new Error("Failed to update team");
  return res.json();
}

export async function deleteTeam(id: string): Promise<void> {
  const res = await fetch(`${API_BASE}/teams/${id}`, {
    method: "DELETE",
  });
  if (!res.ok) throw new Error("Failed to delete team");
}

export async function addTeamMember(teamId: string, miniId: string, role?: string): Promise<TeamMember> {
  const res = await fetch(`${API_BASE}/teams/${teamId}/members`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ mini_id: miniId, ...(role && { role }) }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: "Failed to add member" }));
    throw new Error(err.detail || "Failed to add member");
  }
  return res.json();
}

export async function removeTeamMember(teamId: string, miniId: string): Promise<void> {
  const res = await fetch(`${API_BASE}/teams/${teamId}/members/${miniId}`, {
    method: "DELETE",
  });
  if (!res.ok) throw new Error("Failed to remove member");
}

// --- Org API functions ---

export interface OrgSummary {
  id: string;
  name: string;
  display_name: string;
  description: string | null;
  avatar_url: string | null;
  member_count: number;
  role: string;
  created_at: string;
}

export interface Org {
  id: string;
  name: string;
  display_name: string;
  description: string | null;
  avatar_url: string | null;
  owner_id: string;
  members?: OrgMember[];
  created_at: string;
}

export interface OrgMember {
  id: string;
  org_id: string;
  user_id: string;
  username: string | null;
  display_name: string | null;
  avatar_url: string | null;
  role: string;
  joined_at: string;
}

export async function createOrg(data: { name: string; display_name: string; description?: string }): Promise<Org> {
  const res = await fetch(`${API_BASE}/orgs`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: "Failed to create org" }));
    throw new Error(err.detail || "Failed to create org");
  }
  return res.json();
}

export async function listOrgs(): Promise<OrgSummary[]> {
  const res = await fetch(`${API_BASE}/orgs`);
  if (!res.ok) throw new Error("Failed to fetch orgs");
  return res.json();
}

export async function getOrg(id: string): Promise<Org> {
  const res = await fetch(`${API_BASE}/orgs/${id}`);
  if (!res.ok) throw new Error("Failed to fetch org");
  return res.json();
}

export async function updateOrg(id: string, data: { display_name?: string; description?: string }): Promise<Org> {
  const res = await fetch(`${API_BASE}/orgs/${id}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  if (!res.ok) throw new Error("Failed to update org");
  return res.json();
}

export async function deleteOrg(id: string): Promise<void> {
  const res = await fetch(`${API_BASE}/orgs/${id}`, {
    method: "DELETE",
  });
  if (!res.ok) throw new Error("Failed to delete org");
}

export async function generateInvite(orgId: string): Promise<{ invite_code: string }> {
  const res = await fetch(`${API_BASE}/orgs/${orgId}/invite`, {
    method: "POST",
  });
  if (!res.ok) throw new Error("Failed to generate invite");
  return res.json();
}

export async function joinOrg(code: string): Promise<OrgMember> {
  const res = await fetch(`${API_BASE}/orgs/join/${code}`, {
    method: "POST",
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: "Invalid or expired invite" }));
    throw new Error(err.detail || "Failed to join org");
  }
  return res.json();
}

export async function listOrgMembers(orgId: string): Promise<OrgMember[]> {
  const res = await fetch(`${API_BASE}/orgs/${orgId}/members`);
  if (!res.ok) throw new Error("Failed to fetch members");
  return res.json();
}

export async function removeOrgMember(orgId: string, userId: string): Promise<void> {
  const res = await fetch(`${API_BASE}/orgs/${orgId}/members/${userId}`, {
    method: "DELETE",
  });
  if (!res.ok) throw new Error("Failed to remove member");
}

export async function createOrgTeam(orgId: string, data: { name: string; description?: string }): Promise<Team> {
  const res = await fetch(`${API_BASE}/orgs/${orgId}/teams`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: "Failed to create team" }));
    throw new Error(err.detail || "Failed to create team");
  }
  return res.json();
}

export async function listOrgTeams(orgId: string): Promise<Team[]> {
  const res = await fetch(`${API_BASE}/orgs/${orgId}/teams`);
  if (!res.ok) throw new Error("Failed to fetch org teams");
  return res.json();
}
