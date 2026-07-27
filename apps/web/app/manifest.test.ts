import { describe, expect, it } from "vitest";
import manifest from "./manifest";

describe("PWA manifest", () => {
  it("is installable within the control-plane scope", () => {
    const value = manifest();
    expect(value.start_url).toBe("/");
    expect(value.scope).toBe("/");
    expect(value.display).toBe("standalone");
    expect(value.theme_color).toBe("#090b0f");
    expect(value.icons).toContainEqual(expect.objectContaining({ src: "/pwa-icon.svg", purpose: "any" }));
    expect(value.icons).toContainEqual(expect.objectContaining({ src: "/pwa-icon.svg", purpose: "maskable" }));
  });
});
