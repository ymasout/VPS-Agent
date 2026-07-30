import "server-only";

import { headers } from "next/headers";

import { type PrincipalForwardHeaders, validatePrincipalHeaders } from "./principal-validation";

export async function getPrincipalForwardHeaders(): Promise<PrincipalForwardHeaders | null> {
  if (process.env.PRINCIPAL_CONTEXT_ENABLED !== "true") return null;
  const incoming = await headers();
  return validatePrincipalHeaders(incoming, process.env.PRINCIPAL_PROXY_TOKEN);
}
