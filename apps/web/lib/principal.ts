import "server-only";

import { headers } from "next/headers";
import { cache } from "react";

import { getPrincipal, type Principal } from "./api";
import { type PrincipalForwardHeaders, validatePrincipalHeaders } from "./principal-validation";

export const getPrincipalForwardHeaders = cache(async (): Promise<PrincipalForwardHeaders | null> => {
  if (process.env.PRINCIPAL_CONTEXT_ENABLED !== "true") return null;
  const incoming = await headers();
  return validatePrincipalHeaders(incoming, process.env.PRINCIPAL_PROXY_TOKEN);
});

export const getCurrentPrincipal = cache(async (): Promise<Principal | null> => {
  const principalHeaders = await getPrincipalForwardHeaders();
  return principalHeaders ? getPrincipal(principalHeaders) : null;
});
