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
    expect(command).not.toContain("reg_");
  });
});
