export type DiskMetric = { path: string; used_bytes: number; total_bytes: number; used_percent: number };
export type Metric = { cpu_percent: number; memory_percent: number; memory_used_bytes: number; memory_total_bytes: number; disks: DiskMetric[]; collected_at: string };
export type Service = { kind: string; key: string; name: string; state: string; detail: string | null; healthy: boolean | null; observed_at: string };
export type Agent = { id: string; name: string; hostname: string; os: string; arch: string; version: string; online: boolean; last_seen_at: string | null; latest_metrics: Metric | null; service_counts: Record<string, number>; service_kind_counts: Record<string, number>; service_problem_count: number };
export type AgentDetail = Agent & { capabilities: string[]; services: Service[] };

const apiURL = process.env.API_INTERNAL_URL ?? process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

async function request<T>(path: string): Promise<T> {
  const response = await fetch(`${apiURL}${path}`, { cache: "no-store" });
  if (!response.ok) throw new Error(`API returned ${response.status}`);
  return response.json() as Promise<T>;
}

export const getAgents = () => request<Agent[]>("/api/v1/agents");
export const getAgent = (id: string) => request<AgentDetail>(`/api/v1/agents/${id}`);
export const formatBytes = (value: number) => value < 1 ? "0 B" : `${(value / 1024 ** 3).toFixed(1)} GB`;
