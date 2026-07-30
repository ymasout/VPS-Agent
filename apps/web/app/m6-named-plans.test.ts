import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const appRoot = process.cwd();

describe("M6.4c2 named plan browser paths", () => {
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
    expect(sources).toContain("具名确认将在 c3 启用，当前不可执行");
  });

  it("disables all legacy plan proxies and confirmation before c3", () => {
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
});
