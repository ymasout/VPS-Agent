import { describe, expect, it } from "vitest";
import { isSameOrigin, validAgentName } from "./registration";

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
});
