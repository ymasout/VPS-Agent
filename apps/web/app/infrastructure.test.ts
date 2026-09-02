import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

describe("M7.2a infrastructure workspaces", () => {
  it("exposes real Fleet and service routes while preserving old deep links", () => {
    const fleet = readFileSync(resolve(process.cwd(), "app/fleet/page.tsx"), "utf8");
    const services = readFileSync(resolve(process.cwd(), "app/services/page.tsx"), "utf8");
    const machine = readFileSync(resolve(process.cwd(), "app/servers/[id]/page.tsx"), "utf8");
    expect(fleet).toContain('action="/fleet"');
    expect(services).toContain('action="/services"');
    expect(services).toContain("inventory.items.map((item) => item.environment)");
    expect(machine).toContain('href="/fleet"');
    expect(machine).toContain('id="overview"');
    expect(machine).toContain('id="services"');
    expect(machine).toContain('id="events"');
    expect(machine).toContain('id="assistant"');
    expect(machine).toContain('id="deployment-policy"');
  });

  it("keeps bulk mapping bounded, reviewable, and non-executable", () => {
    const panel = readFileSync(resolve(process.cwd(), "app/service-mapping-batch-panel.tsx"), "utf8");
    expect(panel).toContain("slice(0, 20)");
    expect(panel).toContain('criticality: "critical"');
    expect(panel).toContain('restart_enabled: false');
    expect(panel).toContain('namedAuthorization ? "/api/v1/service-mappings/batch"');
    expect(panel).not.toContain("deploy_enabled");
    expect(panel).toContain("成功项不会因其他项目失败而回退");
  });
});
