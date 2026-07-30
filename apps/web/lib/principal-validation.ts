import { timingSafeEqual } from "node:crypto";

export type PrincipalForwardHeaders = Record<string, string>;

const principalIdHeader = "x-vps-agent-principal-id";
const principalSourceHeader = "x-vps-agent-principal-source";
const principalTokenHeader = "x-vps-agent-principal-proxy-token";
const userIdPattern = /^[A-Za-z0-9][A-Za-z0-9._@-]{0,127}$/;

function equalSecret(left: string, right: string) {
  const leftBytes = Buffer.from(left);
  const rightBytes = Buffer.from(right);
  return leftBytes.length === rightBytes.length && timingSafeEqual(leftBytes, rightBytes);
}

export function validatePrincipalHeaders(
  incoming: Pick<Headers, "get">,
  configuredToken: string | undefined,
): PrincipalForwardHeaders {
  const principalId = incoming.get(principalIdHeader) ?? "";
  const source = incoming.get(principalSourceHeader) ?? "";
  const suppliedToken = incoming.get(principalTokenHeader) ?? "";
  if (
    !configuredToken ||
    configuredToken.length < 32 ||
    !equalSecret(suppliedToken, configuredToken) ||
    source !== "caddy_basic" ||
    !userIdPattern.test(principalId)
  ) {
    throw new Error("Invalid trusted principal context");
  }
  return {
    "X-VPS-Agent-Principal-Id": principalId,
    "X-VPS-Agent-Principal-Source": source,
    "X-VPS-Agent-Principal-Proxy-Token": configuredToken,
  };
}
