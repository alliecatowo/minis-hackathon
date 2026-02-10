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
  display_name: string;
  avatar_url: string;
  bio: string;
  spirit_content: string;
  system_prompt: string;
  values: Value[];
  status: "pending" | "processing" | "ready" | "failed";
  sources_used?: string;
}

export interface ChatMessage {
  role: "user" | "assistant";
  content: string;
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

export async function getMini(username: string): Promise<Mini> {
  const res = await fetch(`${API_BASE}/minis/${username}`);
  if (!res.ok) {
    throw new Error("Failed to fetch mini");
  }
  return res.json();
}

export async function listMinis(): Promise<Mini[]> {
  const res = await fetch(`${API_BASE}/minis`);
  if (!res.ok) {
    throw new Error("Failed to fetch minis");
  }
  return res.json();
}

export async function deleteMini(username: string): Promise<void> {
  const res = await fetch(`${API_BASE}/minis/${username}`, {
    method: "DELETE",
    headers: authHeaders(),
  });
  if (!res.ok) throw new Error("Failed to delete mini");
}

export function subscribePipelineStatus(username: string): EventSource {
  return new EventSource(`${API_BASE}/minis/${username}/status`);
}

export function streamChat(
  username: string,
  message: string,
  history: ChatMessage[]
): EventSource {
  const es = new EventSource(
    `${API_BASE}/minis/${username}/chat?message=${encodeURIComponent(message)}`
  );
  return es;
}

export async function fetchChatStream(
  username: string,
  message: string,
  history: ChatMessage[]
): Promise<Response> {
  return fetch(`${API_BASE}/minis/${username}/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify({ message, history }),
  });
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

export async function addTeamMember(teamId: number, username: string, role?: string): Promise<any> {
  const res = await fetch(`${API_BASE}/teams/${teamId}/members`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify({ username, ...(role && { role }) }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: "Failed to add member" }));
    throw new Error(err.detail || "Failed to add member");
  }
  return res.json();
}

export async function removeTeamMember(teamId: number, username: string): Promise<void> {
  const res = await fetch(`${API_BASE}/teams/${teamId}/members/${username}`, {
    method: "DELETE",
    headers: authHeaders(),
  });
  if (!res.ok) throw new Error("Failed to remove member");
}
