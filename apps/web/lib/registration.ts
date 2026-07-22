export function isSameOrigin(origin: string | null, host: string | null, protocol: string | null) {
  if (!origin || !host) return false;
  try {
    const requestOrigin = new URL(origin);
    const expectedProtocol = protocol === "https" ? "https:" : "http:";
    return requestOrigin.protocol === expectedProtocol && requestOrigin.host === host;
  } catch {
    return false;
  }
}

export function validAgentName(value: unknown): value is string {
  return typeof value === "string" && value.trim().length >= 1 && value.trim().length <= 255 && !/[\r\n]/.test(value);
}

export function shellQuote(value: string) {
  return `'${value.replaceAll("'", `'"'"'`)}'`;
}

export function buildInstallCommand(
  controlPlaneURL: string,
  agentName: string,
  evidencePolicy: "disabled" | "docker-logs" | "systemd-journal" | "docker-systemd" = "disabled",
  operation?: { policy: "disabled" | "docker-restart"; keyId?: string; publicKey?: string },
  deployPolicy: "disabled" | "plan-only" = "disabled",
) {
  const baseURL = controlPlaneURL.replace(/\/$/, "");
  const downloadBaseURL = `${baseURL}/agent-downloads`;
  const operationArgs = operation?.policy === "docker-restart" && operation.keyId && operation.publicKey
    ? ` --operation-policy docker-restart --operation-key-id ${shellQuote(operation.keyId)} --operation-public-key ${shellQuote(operation.publicKey)}`
    : " --operation-policy disabled";
  return `curl -fsSL --proto '=https' --tlsv1.2 ${downloadBaseURL}/latest/install-agent.sh | bash -s -- --url ${baseURL} --download-base-url ${downloadBaseURL} --name ${shellQuote(agentName)} --evidence-policy ${evidencePolicy}${operationArgs} --deploy-policy ${deployPolicy}`;
}
