import { Service } from "./api";

const goodStates = new Set(["active", "running", "healthy"]);
const warningStates = new Set(["activating", "deactivating", "reloading"]);

export function isGoodState(state: string) {
  return goodStates.has(state);
}

export function isServiceProblem(service: Service) {
  if (service.healthy === false) return true;
  if (service.state === "failed" || service.state === "unhealthy") return true;
  return service.kind === "docker" && service.state === "exited";
}

export function serviceStatusTone(service: Service) {
  if (isServiceProblem(service)) return "bad";
  if (service.healthy === true || isGoodState(service.state)) return "good";
  if (warningStates.has(service.state)) return "warn";
  return "neutral";
}
