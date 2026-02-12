import { authHeaders } from "@/lib/auth";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "/api";

export interface Value {
  name: string;
  description: string;
  intensity: number;
}

export interface Mini {
  id: number;
  username: string;
  owner_id: number | null;
  visibility: "public" | "private" | "team";
  display_name: string;
  avatar_url: string;
  bio: string;
  spirit_content: string;
  system_prompt: string;
  values: Value[];
  status: "pending" | "processing" | "ready" | "failed";
  sources_used?: string;
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
    // Fallback to default if endpoint not yet available
    return [
      { id: "github", name: "GitHub", description: "Commits, PRs, and reviews", available: true },
      { id: "claude_code", name: "Claude Code", description: "Conversation history", available: false },
    ];
  }
  return res.json();
}

export async function createMini(username: string, sources?: string[]): Promise<Mini> {
  const res = await fetch(`${API_BASE}/minis`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify({ username, ...(sources && { sources }) }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: "Failed to create mini" }));
    throw new Error(err.detail || "Failed to create mini");
  }
  return res.json();
}

export async function getMiniById(id: number): Promise<Mini> {
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

export async function listMinis(): Promise<Mini[]> {
  const res = await fetch(`${API_BASE}/minis`);
  if (!res.ok) {
    throw new Error("Failed to fetch minis");
  }
  return res.json();
}

export async function getMyMinis(): Promise<Mini[]> {
  const res = await fetch(`${API_BASE}/minis?mine=true`, {
    headers: authHeaders(),
  });
  if (!res.ok) {
    throw new Error("Failed to fetch your minis");
  }
  return res.json();
}

export async function deleteMini(id: number): Promise<void> {
  const res = await fetch(`${API_BASE}/minis/${id}`, {
    method: "DELETE",
    headers: authHeaders(),
  });
  if (!res.ok) throw new Error("Failed to delete mini");
}

export function subscribePipelineStatus(id: number): EventSource {
  return new EventSource(`${API_BASE}/minis/${id}/status`);
}

export function streamChat(
  id: number,
  message: string,
  history: ChatMessage[]
): EventSource {
  const es = new EventSource(
    `${API_BASE}/minis/${id}/chat?message=${encodeURIComponent(message)}`
  );
  return es;
}

export async function fetchChatStream(
  id: number,
  message: string,
  history: ChatMessage[],
  context?: string
): Promise<Response> {
  return fetch(`${API_BASE}/minis/${id}/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify({ message, history, ...(context && { context }) }),
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
  const res = await fetch(`${API_BASE}/settings`, {
    headers: authHeaders(),
  });
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
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify(data),
  });
  if (!res.ok) throw new Error("Failed to update settings");
  return res.json();
}

export async function getUsage(): Promise<UsageInfo> {
  const res = await fetch(`${API_BASE}/settings/usage`, {
    headers: authHeaders(),
  });
  if (!res.ok) throw new Error("Failed to fetch usage");
  return res.json();
}

export async function getAvailableModels(): Promise<Record<string, ModelInfo[]>> {
  const res = await fetch(`${API_BASE}/settings/models`);
  if (!res.ok) throw new Error("Failed to fetch models");
  return res.json();
}

// --- Mini context API functions ---

export interface MiniContext {
  id: number;
  context_key: string;
  display_name: string;
  description: string;
  voice_modulation: string;
  confidence: number;
}

export async function getMiniContexts(miniId: number): Promise<MiniContext[]> {
  const res = await fetch(`${API_BASE}/minis/${miniId}/contexts`);
  if (!res.ok) return [];
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

export async function getMiniRepos(miniId: number): Promise<RepoInfo[]> {
  const res = await fetch(`${API_BASE}/minis/${miniId}/repos`, {
    headers: authHeaders(),
  });
  if (!res.ok) return [];
  return res.json();
}

export async function createMiniWithExclusions(
  username: string,
  sources: string[],
  excludedRepos: string[]
): Promise<Mini> {
  const res = await fetch(`${API_BASE}/minis`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify({ username, sources, excluded_repos: excludedRepos }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: "Failed to create mini" }));
    throw new Error(err.detail || "Failed to create mini");
  }
  return res.json();
}

// --- Auth API functions ---

export async function exchangeGithubCode(code: string): Promise<{ token: string; user: any }> {
  const res = await fetch(`${API_BASE}/auth/github`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ code }),
  });
  if (!res.ok) throw new Error("Auth failed");
  return res.json();
}

export async function getCurrentUser(token: string): Promise<any> {
  const res = await fetch(`${API_BASE}/auth/me`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) throw new Error("Invalid token");
  return res.json();
}

// --- Upload API functions ---

export async function uploadClaudeCode(files: File[]): Promise<{ files_saved: number; total_size: number }> {
  const formData = new FormData();
  files.forEach((f) => formData.append("files", f));

  const res = await fetch(`${API_BASE}/upload/claude-code`, {
    method: "POST",
    headers: authHeaders(),
    body: formData,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: "Upload failed" }));
    throw new Error(err.detail || "Upload failed");
  }
  return res.json();
}

// --- Team API functions ---

export async function createTeam(name: string, description?: string): Promise<any> {
  const res = await fetch(`${API_BASE}/teams`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify({ name, ...(description && { description }) }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: "Failed to create team" }));
    throw new Error(err.detail || "Failed to create team");
  }
  return res.json();
}

export async function listTeams(): Promise<any[]> {
  const res = await fetch(`${API_BASE}/teams`, {
    headers: authHeaders(),
  });
  if (!res.ok) throw new Error("Failed to fetch teams");
  return res.json();
}

export async function getTeam(id: number): Promise<any> {
  const res = await fetch(`${API_BASE}/teams/${id}`, {
    headers: authHeaders(),
  });
  if (!res.ok) throw new Error("Failed to fetch team");
  return res.json();
}

export async function updateTeam(id: number, data: { name?: string; description?: string }): Promise<any> {
  const res = await fetch(`${API_BASE}/teams/${id}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify(data),
  });
  if (!res.ok) throw new Error("Failed to update team");
  return res.json();
}

export async function deleteTeam(id: number): Promise<void> {
  const res = await fetch(`${API_BASE}/teams/${id}`, {
    method: "DELETE",
    headers: authHeaders(),
  });
  if (!res.ok) throw new Error("Failed to delete team");
}

export async function addTeamMember(teamId: number, miniId: number, role?: string): Promise<any> {
  const res = await fetch(`${API_BASE}/teams/${teamId}/members`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify({ mini_id: miniId, ...(role && { role }) }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: "Failed to add member" }));
    throw new Error(err.detail || "Failed to add member");
  }
  return res.json();
}

export async function removeTeamMember(teamId: number, miniId: number): Promise<void> {
  const res = await fetch(`${API_BASE}/teams/${teamId}/members/${miniId}`, {
    method: "DELETE",
    headers: authHeaders(),
  });
  if (!res.ok) throw new Error("Failed to remove member");
}

// --- Org API functions ---

export async function createOrg(data: { name: string; display_name: string; description?: string }): Promise<any> {
  const res = await fetch(`${API_BASE}/orgs`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify(data),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: "Failed to create org" }));
    throw new Error(err.detail || "Failed to create org");
  }
  return res.json();
}

export async function listOrgs(): Promise<any[]> {
  const res = await fetch(`${API_BASE}/orgs`, {
    headers: authHeaders(),
  });
  if (!res.ok) throw new Error("Failed to fetch orgs");
  return res.json();
}

export async function getOrg(id: number): Promise<any> {
  const res = await fetch(`${API_BASE}/orgs/${id}`, {
    headers: authHeaders(),
  });
  if (!res.ok) throw new Error("Failed to fetch org");
  return res.json();
}

export async function updateOrg(id: number, data: { display_name?: string; description?: string }): Promise<any> {
  const res = await fetch(`${API_BASE}/orgs/${id}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify(data),
  });
  if (!res.ok) throw new Error("Failed to update org");
  return res.json();
}

export async function deleteOrg(id: number): Promise<void> {
  const res = await fetch(`${API_BASE}/orgs/${id}`, {
    method: "DELETE",
    headers: authHeaders(),
  });
  if (!res.ok) throw new Error("Failed to delete org");
}

export async function generateInvite(orgId: number): Promise<{ invite_code: string }> {
  const res = await fetch(`${API_BASE}/orgs/${orgId}/invite`, {
    method: "POST",
    headers: authHeaders(),
  });
  if (!res.ok) throw new Error("Failed to generate invite");
  return res.json();
}

export async function joinOrg(code: string): Promise<any> {
  const res = await fetch(`${API_BASE}/orgs/join/${code}`, {
    method: "POST",
    headers: authHeaders(),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: "Invalid or expired invite" }));
    throw new Error(err.detail || "Failed to join org");
  }
  return res.json();
}

export async function listOrgMembers(orgId: number): Promise<any[]> {
  const res = await fetch(`${API_BASE}/orgs/${orgId}/members`, {
    headers: authHeaders(),
  });
  if (!res.ok) throw new Error("Failed to fetch members");
  return res.json();
}

export async function removeOrgMember(orgId: number, userId: number): Promise<void> {
  const res = await fetch(`${API_BASE}/orgs/${orgId}/members/${userId}`, {
    method: "DELETE",
    headers: authHeaders(),
  });
  if (!res.ok) throw new Error("Failed to remove member");
}

export async function createOrgTeam(orgId: number, data: { name: string; description?: string }): Promise<any> {
  const res = await fetch(`${API_BASE}/orgs/${orgId}/teams`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify(data),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: "Failed to create team" }));
    throw new Error(err.detail || "Failed to create team");
  }
  return res.json();
}

export async function listOrgTeams(orgId: number): Promise<any[]> {
  const res = await fetch(`${API_BASE}/orgs/${orgId}/teams`, {
    headers: authHeaders(),
  });
  if (!res.ok) throw new Error("Failed to fetch org teams");
  return res.json();
}
