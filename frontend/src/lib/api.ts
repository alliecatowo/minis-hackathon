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

export type AgreementTrendDirection = "up" | "down" | "flat" | "insufficient_data";

export interface AgreementScorecardTrend {
  direction: AgreementTrendDirection;
  delta: number | null;
}

export interface AgreementSummary {
  mini_id: string;
  username: string;
  cycles_count: number;
  approval_accuracy: number | null;
  blocker_precision: number | null;
  comment_overlap: number | null;
  trend: AgreementScorecardTrend;
}

export class AgreementSummaryUnavailableError extends Error {
  constructor(message = "Agreement summary endpoint is not available yet.") {
    super(message);
    this.name = "AgreementSummaryUnavailableError";
  }
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return typeof value === "object" && value !== null ? (value as Record<string, unknown>) : null;
}

function asNumber(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function asAgreementTrendDirection(value: unknown): AgreementTrendDirection | null {
  switch (value) {
    case "up":
    case "down":
    case "flat":
    case "insufficient_data":
      return value;
    default:
      return null;
  }
}

function normalizeAgreementSummary(miniId: string, payload: unknown): AgreementSummary {
  const source = asRecord(payload);
  if (!source) {
    throw new Error("Agreement summary contract was not an object.");
  }

  const cyclesCount = asNumber(source.cycles_count);
  const trend = asRecord(source.trend);
  const approvalAccuracy = asNumber(source.approval_accuracy);
  const blockerPrecision = asNumber(source.blocker_precision);
  const commentOverlap = asNumber(source.comment_overlap);

  if (cyclesCount === null) {
    throw new Error("Agreement summary contract was missing cycles_count.");
  }

  if (
    cyclesCount > 0 &&
    [approvalAccuracy, blockerPrecision, commentOverlap].some((metric) => metric === null)
  ) {
    throw new Error("Agreement summary contract was missing required metric values.");
  }

  const direction = asAgreementTrendDirection(trend?.direction);
  if (!direction) {
    throw new Error("Agreement summary contract was missing a valid trend.direction.");
  }

  return {
    mini_id:
      typeof source.mini_id === "string" && source.mini_id.trim()
        ? source.mini_id
        : miniId,
    username:
      typeof source.username === "string" && source.username.trim()
        ? source.username
        : "",
    cycles_count: cyclesCount,
    approval_accuracy: approvalAccuracy,
    blocker_precision: blockerPrecision,
    comment_overlap: commentOverlap,
    trend: {
      direction,
      delta: asNumber(trend?.delta),
    },
  };
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

export async function getAgreementSummary(miniId: string): Promise<AgreementSummary> {
  const res = await fetch(
    `${API_BASE}/minis/${encodeURIComponent(miniId)}/agreement-scorecard-summary`,
  );

  if (res.status === 404) {
    throw new AgreementSummaryUnavailableError(
      "Waiting on backend GET /api/minis/:id/agreement-scorecard-summary endpoint.",
    );
  }

  if (!res.ok) {
    const detail = await res
      .json()
      .then((body: unknown) => asRecord(body)?.detail)
      .catch(() => null);
    throw new Error(
      typeof detail === "string" && detail.trim()
        ? detail
        : "Failed to fetch agreement summary",
    );
  }

  if (res.status === 204) {
    return normalizeAgreementSummary(miniId, {
      mini_id: miniId,
      username: "",
      cycles_count: 0,
      approval_accuracy: null,
      blocker_precision: null,
      comment_overlap: null,
      trend: {
        direction: "insufficient_data",
        delta: null,
      },
    });
  }

  return normalizeAgreementSummary(miniId, await res.json());
}

// --- Decision Frameworks ---

export interface DecisionFramework {
  framework_id: string | null;
  confidence: number;
  revision: number;
  trigger: string | null;
  action: string | null;
  value: string | null;
  /** "high" (>0.7), "low" (<0.3), or null */
  badge: "high" | "low" | null;
}

export interface DecisionFrameworksResponse {
  username: string;
  frameworks: DecisionFramework[];
  summary: {
    total: number;
    mean_confidence: number;
    max_revision: number;
  };
}

export async function getDecisionFrameworks(
  username: string,
  limit = 10,
): Promise<DecisionFrameworksResponse> {
  const res = await fetch(
    `${API_BASE}/minis/by-username/${encodeURIComponent(username)}/decision-frameworks?limit=${limit}`,
  );
  if (!res.ok) {
    throw new Error("Failed to fetch decision frameworks");
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
  conversationId?: string,
): Promise<Response> {
  return fetch(`${API_BASE}/minis/${id}/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      message,
      history,
      ...(conversationId && { conversation_id: conversationId }),
    }),
  });
}

export type ArtifactReviewType = "design_doc" | "issue_plan";

export interface ArtifactReviewRequest {
  artifact_type: ArtifactReviewType;
  title: string;
  artifact_summary: string;
}

export interface ReviewPredictionEvidence {
  source:
    | "behavioral_context"
    | "motivations"
    | "principles"
    | "memory"
    | "evidence"
    | "input";
  detail: string;
}

export interface ReviewPredictionSignal {
  key: string;
  summary: string;
  rationale: string;
  confidence: number;
  evidence: ReviewPredictionEvidence[];
}

export interface ReviewPredictionPrivateAssessment {
  blocking_issues: ReviewPredictionSignal[];
  non_blocking_issues: ReviewPredictionSignal[];
  open_questions: ReviewPredictionSignal[];
  positive_signals: ReviewPredictionSignal[];
  confidence: number;
}

export interface ReviewPredictionDeliveryPolicy {
  author_model: "junior_peer" | "trusted_peer" | "senior_peer" | "unknown";
  context: "hotfix" | "normal" | "exploratory" | "incident";
  strictness: "low" | "medium" | "high";
  teaching_mode: boolean;
  shield_author_from_noise: boolean;
  rationale: string;
}

export interface ReviewPredictionComment {
  type: "blocker" | "note" | "question" | "praise";
  disposition: "request_changes" | "comment" | "approve";
  issue_key: string | null;
  summary: string;
  rationale: string;
}

export interface ReviewArtifactSummary {
  artifact_type: "pull_request" | ArtifactReviewType;
  title: string | null;
}

export interface ArtifactReviewResponse {
  version: "review_prediction_v1";
  reviewer_username: string;
  repo_name: string | null;
  artifact_summary: ReviewArtifactSummary | null;
  private_assessment: ReviewPredictionPrivateAssessment;
  delivery_policy: ReviewPredictionDeliveryPolicy;
  expressed_feedback: {
    summary: string;
    comments: ReviewPredictionComment[];
    approval_state: "approve" | "comment" | "request_changes" | "uncertain";
  };
}

export async function reviewArtifact(
  miniId: string,
  body: ArtifactReviewRequest,
): Promise<ArtifactReviewResponse> {
  const res = await fetch(`${API_BASE}/minis/${miniId}/artifact-review`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });

  if (!res.ok) {
    const err = (await res.json().catch(() => null)) as
      | { detail?: string | { msg?: string }[] }
      | null;
    const validationError = Array.isArray(err?.detail)
      ? err.detail.map((item) => item.msg).filter(Boolean).join(", ")
      : null;
    const detail = typeof err?.detail === "string" ? err.detail : validationError;
    const endpointUnavailable =
      res.status === 404 && (!detail || detail.toLowerCase() === "not found");

    throw new Error(
      (endpointUnavailable
        ? "Artifact review endpoint unavailable. This UI depends on POST /api/minis/{id}/artifact-review."
        : detail) || "Failed to review artifact",
    );
  }

  return res.json();
}

export type ArtifactReviewOutcomeValue = "accepted" | "rejected" | "revised" | "deferred";

export interface SuggestionOutcome {
  suggestion_key: string;
  outcome: ArtifactReviewOutcomeValue;
  summary?: string;
}

export interface ArtifactOutcomeCapture {
  artifact_outcome?: ArtifactReviewOutcomeValue;
  final_disposition?: string;
  reviewer_summary?: string;
  suggestion_outcomes: SuggestionOutcome[];
}

export interface ReviewCyclePredictionRequest {
  external_id: string;
  source_type: string;
  predicted_state: {
    private_assessment: ArtifactReviewResponse["private_assessment"];
    expressed_feedback: ArtifactReviewResponse["expressed_feedback"];
    delivery_policy: ArtifactReviewResponse["delivery_policy"];
  };
}

export interface ReviewCycleOutcomeRequest {
  external_id: string;
  source_type: string;
  human_review_outcome: {
    private_assessment: {
      blocking_issues: unknown[];
      non_blocking_issues: unknown[];
      open_questions: unknown[];
      positive_signals: unknown[];
      confidence: number;
    };
    expressed_feedback: {
      summary: string;
      comments: unknown[];
      approval_state: "approve" | "comment" | "request_changes" | "uncertain";
    };
    outcome_capture: ArtifactOutcomeCapture;
  };
}

export async function saveReviewCyclePrediction(
  miniId: string,
  body: ReviewCyclePredictionRequest,
): Promise<void> {
  const res = await fetch(`${API_BASE}/minis/trusted/${miniId}/review-cycles`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    console.warn("[api] saveReviewCyclePrediction failed:", res.status);
  }
}

export async function saveReviewCycleOutcome(
  miniId: string,
  body: ReviewCycleOutcomeRequest,
): Promise<void> {
  const res = await fetch(`${API_BASE}/minis/trusted/${miniId}/review-cycles`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const detail = await res.json().catch(() => null) as { detail?: string } | null;
    throw new Error(detail?.detail ?? "Failed to save outcome");
  }
}

// --- Conversation API functions ---

export interface Conversation {
  id: string;
  mini_id: string;
  title: string;
  created_at: string;
  updated_at: string;
  message_count: number;
}

export interface ConversationMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  created_at: string;
}

export async function getConversations(miniId: string): Promise<Conversation[]> {
  try {
    const res = await fetch(`${API_BASE}/minis/${miniId}/conversations`);
    if (!res.ok) return [];
    return res.json();
  } catch {
    return [];
  }
}

export async function getConversation(
  miniId: string,
  conversationId: string,
): Promise<{ conversation: Conversation; messages: ConversationMessage[] } | null> {
  try {
    const res = await fetch(`${API_BASE}/minis/${miniId}/conversations/${conversationId}`);
    if (!res.ok) return null;
    return res.json();
  } catch {
    return null;
  }
}

export async function deleteConversation(miniId: string, conversationId: string): Promise<boolean> {
  try {
    const res = await fetch(`${API_BASE}/minis/${miniId}/conversations/${conversationId}`, {
      method: "DELETE",
    });
    return res.ok;
  } catch {
    return false;
  }
}

export async function updateConversationTitle(
  miniId: string,
  conversationId: string,
  title: string,
): Promise<boolean> {
  try {
    const res = await fetch(`${API_BASE}/minis/${miniId}/conversations/${conversationId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title }),
    });
    return res.ok;
  } catch {
    return false;
  }
}

// --- Settings API functions ---

export interface UserSettings {
  llm_provider: string;
  preferred_model: string | null;
  has_api_key: boolean;
  is_admin: boolean;
  model_preferences: Record<string, string> | null;
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

export interface TierModelsResponse {
  providers: Record<string, Record<string, ModelInfo[]>>;
  tiers: string[];
  defaults: Record<string, Record<string, string>>;
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
  model_preferences?: Record<string, string>;
}): Promise<UserSettings> {
  const res = await fetch(`${API_BASE}/settings`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  if (!res.ok) throw new Error("Failed to update settings");
  return res.json();
}

export async function testApiKey(
  provider: string,
  apiKey: string,
): Promise<{ valid: boolean; message: string }> {
  const res = await fetch(`${API_BASE}/settings/test-key`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ provider, api_key: apiKey }),
  });
  if (!res.ok) throw new Error("Failed to test API key");
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

export async function getTierModels(): Promise<TierModelsResponse> {
  const res = await fetch(`${API_BASE}/settings/models/tiers`);
  if (!res.ok) throw new Error("Failed to fetch tier models");
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

// --- Frameworks-at-risk API functions ---

export type AtRiskReason = "low_band" | "declining_trend" | "low_evidence";

export interface AtRiskFramework {
  framework_id: string;
  condition: string;
  action: string;
  value: string;
  confidence: number;
  revision: number;
  confidence_history: unknown[];
  reason: AtRiskReason;
  trend_summary: string | null;
  retired: boolean;
}

export async function getFrameworksAtRisk(miniId: string): Promise<AtRiskFramework[]> {
  const res = await fetch(`${API_BASE}/minis/${encodeURIComponent(miniId)}/frameworks-at-risk`);
  if (!res.ok) {
    throw new Error("Failed to fetch frameworks at risk");
  }
  return res.json();
}

export async function retireFramework(
  miniId: string,
  frameworkId: string,
): Promise<{ framework_id: string; retired: boolean; message: string }> {
  const res = await fetch(
    `${API_BASE}/minis/${encodeURIComponent(miniId)}/frameworks/${encodeURIComponent(frameworkId)}/retire`,
    { method: "POST" },
  );
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: "Failed to retire framework" }));
    throw new Error(err.detail || "Failed to retire framework");
  }
  return res.json();
}
