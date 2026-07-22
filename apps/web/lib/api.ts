export type DiskMetric = { path: string; used_bytes: number; total_bytes: number; used_percent: number };
export type Metric = { cpu_percent: number; memory_percent: number; memory_used_bytes: number; memory_total_bytes: number; disks: DiskMetric[]; collected_at: string };
export type Service = { kind: string; key: string; name: string; state: string; detail: string | null; healthy: boolean | null; observed_at: string };
export type Agent = { id: string; name: string; hostname: string; os: string; arch: string; version: string; online: boolean; last_seen_at: string | null; latest_metrics: Metric | null; service_counts: Record<string, number>; service_kind_counts: Record<string, number>; service_problem_count: number };
export type AgentDetail = Agent & { capabilities: string[]; services: Service[] };
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
export type OperationTransition = { from_status: string | null; to_status: string; actor_type: string; actor_id: string | null; reason: string | null; details: Record<string, unknown>; created_at: string };
export type Operation = {
  id: string; instance_id: string; agent_id: string; source_event_id: string | null; source_diagnostic_id: string | null;
  action_type: string; status: string; requested_by: string; confirmed_by: string | null; risk_level: string; impact_summary: string;
  plan_snapshot: Record<string, unknown>; precheck_result: Record<string, boolean>; verification_policy: Record<string, unknown>; verification_result: Record<string, unknown> | null;
  expires_at: string; requested_at: string; confirmed_at: string | null; claimed_at: string | null; started_at: string | null;
  execution_completed_at: string | null; completed_at: string | null; exit_code: number | null; output: string | null; output_truncated: boolean;
  error_code: string | null; error_detail: string | null; transitions: OperationTransition[];
};

const apiURL = process.env.API_INTERNAL_URL ?? process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

async function request<T>(path: string): Promise<T> {
  const response = await fetch(`${apiURL}${path}`, { cache: "no-store" });
  if (!response.ok) throw new Error(`API returned ${response.status}`);
  return response.json() as Promise<T>;
}

export const getAgents = () => request<Agent[]>("/api/v1/agents");
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
export const getOperation = (id: string) => request<Operation>(`/api/v1/operations/${id}`);
export function formatBytes(value: number) {
  if (!Number.isFinite(value) || value <= 0) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  const unit = Math.min(Math.floor(Math.log(value) / Math.log(1024)), units.length - 1);
  const amount = value / 1024 ** unit;
  return `${unit === 0 ? amount.toFixed(0) : amount.toFixed(1)} ${units[unit]}`;
}
