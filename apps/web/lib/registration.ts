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
