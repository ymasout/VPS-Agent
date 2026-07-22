import { describe, expect, it } from "vitest";
import { buildInstallCommand, isSameOrigin, shellQuote, validAgentName } from "./registration";

describe("registration token request protection", () => {
  it("accepts only the expected origin", () => {
    expect(isSameOrigin("https://ops.example.com", "ops.example.com", "https")).toBe(true);
    expect(isSameOrigin("https://evil.example", "ops.example.com", "https")).toBe(false);
    expect(isSameOrigin(null, "ops.example.com", "https")).toBe(false);
  });

  it("validates the Fleet display name", () => {
    expect(validAgentName("dmit-vps")).toBe(true);
    expect(validAgentName(" ")).toBe(false);
    expect(validAgentName("bad\nname")).toBe(false);
  });

  it("builds a shell-safe install command without embedding the registration token", () => {
    expect(shellQuote("owner's vps")).toBe(`'owner'"'"'s vps'`);
    const command = buildInstallCommand("https://ops.example.com/", "owner's vps", "docker-logs");

    expect(command).toContain("https://ops.example.com/agent-downloads/latest/install-agent.sh");
    expect(command).toContain(`--name 'owner'"'"'s vps'`);
    expect(command).toContain("--evidence-policy docker-logs");
    expect(command).toContain("--deploy-policy disabled");
    expect(command).not.toContain("reg_");
  });

  it("requires an explicit plan-only deployment discovery flag", () => {
    const command = buildInstallCommand(
      "https://ops.example.com",
      "canary",
      "disabled",
      { policy: "disabled" },
      "plan-only",
    );
    expect(command).toContain("--deploy-policy plan-only");
    expect(command).toContain("--operation-policy disabled");
  });

  it("requires explicit signing material and an allowed root for Compose execution", () => {
    const command = buildInstallCommand(
      "https://ops.example.com",
      "deploy-canary",
      "disabled",
      { policy: "disabled", keyId: "key-1", publicKey: "public-key" },
      "docker-compose-deploy",
      "/opt/vps-agent-deploy",
    );
    expect(command).toContain("--operation-policy disabled");
    expect(command).toContain("--operation-key-id 'key-1'");
    expect(command).toContain("--operation-public-key 'public-key'");
    expect(command).toContain("--deploy-policy docker-compose-deploy");
    expect(command).toContain("--deploy-allowed-root '/opt/vps-agent-deploy'");
  });
});
