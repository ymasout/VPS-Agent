import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const appRoot = process.cwd();

describe("M6.4c3 named plan and confirmation browser paths", () => {
  it("uses only the six frozen direct API plan routes when enforcement is enabled", () => {
    const sources = [
      "events/[id]/operation-create.tsx",
      "events/[id]/event-conversation.tsx",
      "deployment-plan-panel.tsx",
      "operations/[id]/operation-panel.tsx",
    ].map((path) => readFileSync(join(appRoot, "app", path), "utf8")).join("\n");

    expect(sources).toContain('"/api/v1/operations"');
    expect(sources).toContain('"/api/v1/deployment-operations"');
    expect(sources).toContain('"/api/v1/deployment-plans"');
    expect(sources).toContain("/api/v1/deployment-operations/${operation.id}/rollback");
    expect(sources).toContain('${namedAuthorization ? "/api/v1" : "/console"}/events/');
    expect(sources).toContain("当前身份没有 operation:approve");
    expect(sources).toContain("计划创建人与审批人必须不同");
  });

  it("keeps all legacy write proxies disabled during named enforcement", () => {
    const routes = [
      "console/operations/route.ts",
      "console/deployment-plans/route.ts",
      "console/deployment-operations/route.ts",
      "console/deployment-operations/[id]/rollback/route.ts",
      "console/events/[id]/conversation/turns/[turnId]/restart-plan/route.ts",
      "console/events/[id]/conversation/turns/[turnId]/rollback-plan/route.ts",
      "console/operations/[id]/confirm/route.ts",
    ];
    for (const route of routes) {
      const source = readFileSync(join(appRoot, "app", route), "utf8");
      expect(source).toContain('PRINCIPAL_WRITE_AUTHORIZATION_ENABLED === "true"');
      expect(source.indexOf("PRINCIPAL_WRITE_AUTHORIZATION_ENABLED")).toBeLessThan(
        source.indexOf("ADMIN_API_TOKEN"),
      );
    }
  });

  it("posts named confirmation directly to the frozen API route with an empty body", () => {
    const source = readFileSync(
      join(appRoot, "app", "operations/[id]/operation-panel.tsx"),
      "utf8",
    );
    const confirmation = source.slice(
      source.indexOf("async function confirm()"),
      source.indexOf("async function createRollback()"),
    );
    expect(confirmation).toContain("/api/v1/operations/${operation.id}/confirm");
    expect(confirmation).toContain('method: "POST"');
    expect(confirmation).not.toContain("body:");
    expect(confirmation).not.toContain("confirmed_by");
  });
});
