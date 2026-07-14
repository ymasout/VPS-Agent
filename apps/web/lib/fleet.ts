import { Agent } from "./api";

export function summarizeFleet(agents: Agent[]) {
  return agents.reduce(
    (summary, agent) => ({
      total: summary.total + 1,
      online: summary.online + Number(agent.online),
      offline: summary.offline + Number(!agent.online),
      problems: summary.problems + agent.service_problem_count,
    }),
    { total: 0, online: 0, offline: 0, problems: 0 },
  );
}
