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
  deployPolicy: "disabled" | "plan-only" | "docker-compose-deploy" = "disabled",
  deployAllowedRoot = "",
) {
  const baseURL = controlPlaneURL.replace(/\/$/, "");
  const downloadBaseURL = `${baseURL}/agent-downloads`;
  const needsSigningKey = operation?.policy === "docker-restart" || deployPolicy === "docker-compose-deploy";
  const operationArgs = operation?.policy === "docker-restart" ? " --operation-policy docker-restart" : " --operation-policy disabled";
  const signingArgs = needsSigningKey && operation?.keyId && operation.publicKey
    ? ` --operation-key-id ${shellQuote(operation.keyId)} --operation-public-key ${shellQuote(operation.publicKey)}`
    : "";
  const deployRootArg = deployPolicy === "docker-compose-deploy" && deployAllowedRoot
    ? ` --deploy-allowed-root ${shellQuote(deployAllowedRoot)}`
    : "";
  return `curl -fsSL --proto '=https' --tlsv1.2 ${downloadBaseURL}/latest/install-agent.sh | bash -s -- --url ${baseURL} --download-base-url ${downloadBaseURL} --name ${shellQuote(agentName)} --evidence-policy ${evidencePolicy}${operationArgs}${signingArgs} --deploy-policy ${deployPolicy}${deployRootArg}`;
}
