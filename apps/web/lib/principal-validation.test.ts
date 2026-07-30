import { describe, expect, it } from "vitest";
import { validatePrincipalHeaders } from "./principal-validation";

const token = "test-only-" + "x".repeat(32);

function principalHeaders(overrides: Record<string, string> = {}) {
  return new Headers({
    "x-vps-agent-principal-id": "admin",
    "x-vps-agent-principal-source": "caddy_basic",
    "x-vps-agent-principal-proxy-token": token,
    ...overrides,
  });
}

describe("trusted principal forwarding", () => {
  it("forwards only validated server-side values", () => {
    expect(validatePrincipalHeaders(principalHeaders(), token)).toEqual({
      "X-VPS-Agent-Principal-Id": "admin",
      "X-VPS-Agent-Principal-Source": "caddy_basic",
      "X-VPS-Agent-Principal-Proxy-Token": token,
    });
  });

  it.each([
    ["missing token", principalHeaders(), undefined],
    ["short configured token", principalHeaders(), "short"],
    ["wrong supplied token", principalHeaders({ "x-vps-agent-principal-proxy-token": "wrong" }), token],
    ["wrong source", principalHeaders({ "x-vps-agent-principal-source": "browser" }), token],
    ["invalid id", principalHeaders({ "x-vps-agent-principal-id": "bad user" }), token],
  ])("fails closed for %s", (_name, incoming, configured) => {
    expect(() => validatePrincipalHeaders(incoming, configured)).toThrow(
      "Invalid trusted principal context",
    );
  });
});
