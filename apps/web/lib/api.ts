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
export const getEvents = () => request<AlertEvent[]>("/api/v1/events");
export const getEvent = (id: string) => request<AlertEvent>(`/api/v1/events/${id}`);
export const getEventDiagnostics = (id: string) =>
  request<Diagnostic[]>(`/api/v1/events/${id}/diagnostics`);
export function formatBytes(value: number) {
  if (!Number.isFinite(value) || value <= 0) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  const unit = Math.min(Math.floor(Math.log(value) / Math.log(1024)), units.length - 1);
  const amount = value / 1024 ** unit;
  return `${unit === 0 ? amount.toFixed(0) : amount.toFixed(1)} ${units[unit]}`;
}
