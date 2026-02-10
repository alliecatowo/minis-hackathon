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
}

export interface ChatMessage {
  role: "user" | "assistant";
  content: string;
}

export interface PipelineEvent {
  step: string;
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
    headers: { "Content-Type": "application/json" },
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

export function subscribePipelineStatus(username: string): EventSource {
  return new EventSource(`${API_BASE}/minis/${username}/status`);
}

export function streamChat(
  username: string,
  message: string,
  history: ChatMessage[]
): EventSource {
  // We use fetch + ReadableStream for POST-based SSE
  // But EventSource only supports GET, so we'll handle this differently in the component
  // This returns a URL for reference; actual streaming is done via fetch in the component
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
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message, history }),
  });
}
