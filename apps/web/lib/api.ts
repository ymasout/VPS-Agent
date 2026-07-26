export type DiskMetric = { path: string; used_bytes: number; total_bytes: number; used_percent: number };
export type Metric = { cpu_percent: number; memory_percent: number; memory_used_bytes: number; memory_total_bytes: number; disks: DiskMetric[]; collected_at: string };
export type Service = { kind: string; key: string; name: string; state: string; detail: string | null; healthy: boolean | null; observed_at: string };
export type Agent = { id: string; name: string; hostname: string; os: string; arch: string; version: string; online: boolean; last_seen_at: string | null; latest_metrics: Metric | null; service_counts: Record<string, number>; service_kind_counts: Record<string, number>; service_problem_count: number };
export type AgentDetail = Agent & { capabilities: string[]; services: Service[] };
export type SystemInfo = {
  instance_id: string;
  version: string;
  commit_sha: string;
  build_time: string;
  alembic_revision: string[];
  expected_alembic_revision: string[];
  schema_current: boolean;
};
export type ServiceMappingCandidate = {
  agent_id: string;
  service_kind: string;
  service_key: string;
  service_name: string;
  state: string;
  healthy: boolean | null;
  log_source_key: string;
  log_source_name: string;
  mapped: boolean;
  instance_id: string | null;
  operation_capable: boolean;
  restart_enabled: boolean;
  criticality: string;
};
export type DeploymentCandidate = {
  agent_id: string;
  service_kind: string;
  service_key: string;
  repository: string | null;
  current_digest: string | null;
  eligible: boolean;
  reason_code: string | null;
  observed_at: string;
  mapped: boolean;
  instance_id: string | null;
  service_name: string | null;
  criticality: string;
  state: string | null;
  healthy: boolean | null;
  deploy_capable: boolean;
  deploy_enabled: boolean;
};
export type GitHubRepository = {
  id: string;
  full_name: string;
  default_branch: string;
  private: boolean;
  head_sha: string | null;
  synchronized_at: string | null;
  last_error: string | null;
};
export type GitHubStatus = {
  configured: boolean;
  app_slug: string | null;
  installation_url: string | null;
  allowed_file_paths: string[];
  repository_count: number;
  repository_chat_enabled: boolean;
};
export type AlertEvent = {
  id: string;
  agent_id: string;
  source: string;
  service_kind: string | null;
  service_key: string | null;
  title: string;
  severity: string;
  status: string;
  observation_count: number;
  detail: string | null;
  first_observed_at: string;
  last_observed_at: string;
  firing_at: string | null;
  acknowledged_at: string | null;
  silenced_until: string | null;
  resolved_at: string | null;
};
export type DiagnosticFact = { statement: string; evidence_ids: string[] };
export type DiagnosticInference = DiagnosticFact & { confidence: "low" | "medium" | "high" };
export type DiagnosticRecommendation = {
  action: string;
  risk: "low" | "medium" | "high";
  requires_confirmation: boolean;
  prerequisites: string[];
};
export type DiagnosticResult = {
  summary: string;
  facts: DiagnosticFact[];
  inferences: DiagnosticInference[];
  recommendations: DiagnosticRecommendation[];
  missing_evidence: string[];
};
export type Evidence = {
  id: string;
  evidence_type: string;
  source_label: string;
  content: string;
  redacted: boolean;
  truncated: boolean;
  collected_at: string;
  source_metadata: Record<string, unknown>;
};
export type Diagnostic = {
  id: string;
  event_id: string;
  instance_id: string | null;
  status: string;
  trigger: string;
  provider: string;
  result: DiagnosticResult | null;
  error_code: string | null;
  error_detail: string | null;
  evidence: Evidence[];
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
};
export type ConversationFact = { statement: string; citation_ids: string[] };
export type ConversationInference = ConversationFact & {
  confidence: "low" | "medium" | "high";
};
export type ConversationRecommendation = {
  action: string;
  risk: "low" | "medium" | "high";
  requires_confirmation: boolean;
  citation_ids: string[];
};
export type ConversationAnswer = {
  summary: string;
  facts: ConversationFact[];
  inferences: ConversationInference[];
  recommendations: ConversationRecommendation[];
  missing_evidence: string[];
};
export type ConversationCitation = {
  id: string;
  source_type: string;
  source_id: string | null;
  source_label: string;
  source_collected_at: string;
  href: string | null;
  repository: {
    full_name: string;
    path: string;
    commit_sha: string;
    deployment_commit_sha: string | null;
    deployment_relation: "aligned" | "mismatch" | "unknown";
    basis: "deployment" | "snapshot";
    synchronized_at: string | null;
    truncated: boolean;
    stale: boolean;
    available: boolean;
  } | null;
  fleet?: {
    captured_at: string;
    content_sha256: string;
    available: boolean;
  } | null;
};
export type ConversationTurn = {
  id: string;
  session_id: string;
  client_request_id: string;
  question: string;
  status: string;
  provider: string;
  answer: ConversationAnswer | null;
  citations: ConversationCitation[];
  context_manifest: Record<string, unknown>;
  error_code: string | null;
  error_detail: string | null;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
};
export type EventConversation = {
  event_id: string;
  session_id: string | null;
  turns: ConversationTurn[];
};
export type RepositoryFileMetadata = {
  id: string;
  path: string;
  byte_size: number;
  content_sha256: string;
  redacted: boolean;
  truncated: boolean;
  fetched_at: string;
};
export type RepositoryDetail = {
  id: string;
  full_name: string;
  default_branch: string;
  private: boolean | null;
  enabled: boolean;
  head_sha: string | null;
  synchronized_at: string | null;
  last_error: string | null;
  conversation_available: boolean;
  unavailable_reason: string | null;
  files: RepositoryFileMetadata[];
};
export type RepositoryConversation = {
  repository_id: string;
  session_id: string | null;
  available: boolean;
  unavailable_reason: string | null;
  turns: ConversationTurn[];
};
export type ContextConversation = {
  scope_type: "agent" | "service" | "fleet";
  target_id: string;
  parent_agent_id: string;
  title: string;
  session_id: string | null;
  available: boolean;
  unavailable_reason: string | null;
  turns: ConversationTurn[];
};
export type FleetConversation = {
  session_id: string | null;
  available: boolean;
  unavailable_reason: string | null;
  turns: ConversationTurn[];
};
export type EventHistoryItem = {
  id: string;
  item_type: "event" | "diagnostic" | "conversation" | "operation";
  status: string;
  summary: string;
  occurred_at: string;
  href: string;
};
export type EventHistory = { event_id: string; items: EventHistoryItem[]; next_cursor?: string | null };
export type SimilarEvent = {
  id: string;
  title: string;
  severity: string;
  status: string;
  score_band: "high" | "medium" | "low";
  match_reasons: string[];
  same_agent: boolean;
  same_service: boolean;
  diagnostic_summary: string | null;
  last_observed_at: string;
  href: string;
};
export type SimilarEvents = {
  event_id: string;
  algorithm: "m5.6-similarity-v1";
  items: SimilarEvent[];
  next_cursor?: string | null;
};
export type EventReview = {
  event_id: string;
  provisional: boolean;
  summary: string;
  facts: string[];
  inferences: string[];
  operation_results: string[];
  missing_evidence: string[];
  sources: Array<{
    source_type: string;
    source_id: string;
    label: string;
    occurred_at: string;
    href: string;
  }>;
};
export type RunbookDraft = {
  id: string;
  source_turn_id: string | null;
  source_event_id: string | null;
  service_id: string | null;
  title: string;
  content: {
    schema_version?: string;
    objective?: string;
    prerequisites?: string[];
    display_steps?: string[];
    risk?: string;
    requires_confirmation?: boolean;
    executable?: boolean;
  };
  status: "draft";
  source_available: boolean;
  citations: Array<{
    id: string;
    source_type: string | null;
    source_label: string;
    href: string | null;
    available: boolean;
  }>;
  created_at: string;
  updated_at: string;
};
export type ConversationOperationCandidate = {
  action_type: "docker_restart" | "docker_compose_rollback";
  available: boolean;
  reason_code: string | null;
  impact_summary: string;
  requires_plan_creation: boolean;
  requires_confirmation: boolean;
};
export type ConversationOperationCandidates = {
  event_id: string;
  candidates: ConversationOperationCandidate[];
};
export type ConversationOperationTimelineTransition = {
  from_status: string | null;
  to_status: string;
  actor_type: string;
  created_at: string;
};
export type ConversationOperationTimelineItem = {
  id: string;
  source_conversation_turn_id: string | null;
  action_type: string;
  status: string;
  impact_summary: string;
  verification_status: string | null;
  error_code: string | null;
  error_summary: string | null;
  requested_at: string;
  completed_at: string | null;
  transitions: ConversationOperationTimelineTransition[];
};
export type ConversationOperationTimeline = {
  event_id: string;
  available: boolean;
  unavailable_reason: string | null;
  operations: ConversationOperationTimelineItem[];
};
export type OperationTransition = { from_status: string | null; to_status: string; actor_type: string; actor_id: string | null; reason: string | null; details: Record<string, unknown>; created_at: string };
export type Operation = {
  id: string; instance_id: string; agent_id: string; source_event_id: string | null; source_diagnostic_id: string | null; source_conversation_turn_id: string | null;
  action_type: string; status: string; requested_by: string; confirmed_by: string | null; risk_level: string; impact_summary: string;
  plan_snapshot: Record<string, unknown>; precheck_result: Record<string, boolean>; verification_policy: Record<string, unknown>; verification_result: Record<string, unknown> | null;
  expires_at: string; requested_at: string; confirmed_at: string | null; claimed_at: string | null; started_at: string | null;
  execution_completed_at: string | null; completed_at: string | null; exit_code: number | null; output: string | null; output_truncated: boolean;
  error_code: string | null; error_detail: string | null; transitions: OperationTransition[];
  current_digest: string | null; target_digest: string | null; rollback_of: string | null;
};

const apiURL = process.env.API_INTERNAL_URL ?? process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export class ControlPlaneApiError extends Error {
  constructor(public readonly status: number) {
    super(`API returned ${status}`);
    this.name = "ControlPlaneApiError";
  }
}

async function request<T>(path: string): Promise<T> {
  const response = await fetch(`${apiURL}${path}`, { cache: "no-store" });
  if (!response.ok) throw new ControlPlaneApiError(response.status);
  return response.json() as Promise<T>;
}

async function adminRequest<T>(path: string): Promise<T> {
  const token = process.env.ADMIN_API_TOKEN;
  if (!token) throw new Error("ADMIN_API_TOKEN is required for managed API requests");
  const response = await fetch(`${apiURL}${path}`, {
    cache: "no-store",
    headers: { "X-Admin-Token": token },
  });
  if (!response.ok) throw new ControlPlaneApiError(response.status);
  return response.json() as Promise<T>;
}

export const getAgents = () => request<Agent[]>("/api/v1/agents");
export const getSystemInfo = () => adminRequest<SystemInfo>("/api/v1/system-info");
export const getAgent = (id: string) => request<AgentDetail>(`/api/v1/agents/${id}`);
export const getServiceMappingCandidates = (id: string) =>
  request<ServiceMappingCandidate[]>(`/api/v1/agents/${id}/service-mapping-candidates`);
export const getDeploymentCandidates = (id: string) =>
  request<DeploymentCandidate[]>(`/api/v1/agents/${id}/deployment-candidates`);
export const getGitHubStatus = () => request<GitHubStatus>("/api/v1/github/status");
export const getGitHubRepositories = () => request<GitHubRepository[]>("/api/v1/github/repositories");
export const getEvents = () => request<AlertEvent[]>("/api/v1/events");
export const getEvent = (id: string) => request<AlertEvent>(`/api/v1/events/${id}`);
export const getEventDiagnostics = (id: string) =>
  request<Diagnostic[]>(`/api/v1/events/${id}/diagnostics`);
export const getEventConversation = (id: string) =>
  request<EventConversation>(`/api/v1/events/${id}/conversation`);
export const getRepositoryDetail = (id: string) =>
  request<RepositoryDetail>(`/api/v1/repositories/${id}`);
export const getRepositoryConversation = (id: string) =>
  request<RepositoryConversation>(`/api/v1/repositories/${id}/conversation`);
export const getAgentConversation = (id: string) =>
  request<ContextConversation>(`/api/v1/agents/${id}/conversation`);
export const getServiceConversation = (id: string) =>
  request<ContextConversation>(`/api/v1/service-instances/${id}/conversation`);
export const getFleetConversation = () =>
  request<FleetConversation>("/api/v1/fleet/conversation");
export const getEventHistory = (id: string) =>
  request<EventHistory>(`/api/v1/events/${id}/history`);
export const getSimilarEvents = (id: string) =>
  request<SimilarEvents>(`/api/v1/events/${id}/similar-events`);
export const getEventReview = (id: string) =>
  request<EventReview>(`/api/v1/events/${id}/review`);
export const getRunbookDraft = (id: string) =>
  request<RunbookDraft>(`/api/v1/runbook-drafts/${id}`);
export const getConversationOperationCandidates = (id: string) =>
  request<ConversationOperationCandidates>(
    `/api/v1/events/${id}/conversation/operation-candidates`,
  );
export const getConversationOperationTimeline = (id: string) =>
  request<ConversationOperationTimeline>(
    `/api/v1/events/${id}/conversation/operations`,
  );
export const getOperation = (id: string) => request<Operation>(`/api/v1/operations/${id}`);
export function formatBytes(value: number) {
  if (!Number.isFinite(value) || value <= 0) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  const unit = Math.min(Math.floor(Math.log(value) / Math.log(1024)), units.length - 1);
  const amount = value / 1024 ** unit;
  return `${unit === 0 ? amount.toFixed(0) : amount.toFixed(1)} ${units[unit]}`;
}
