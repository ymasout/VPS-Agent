import { renderToStaticMarkup } from "react-dom/server";
import { beforeEach, describe, expect, it, vi } from "vitest";
import OperationsPage from "./page";
import OperationDetailPage from "./[id]/page";
import OperationNotFound from "./[id]/not-found";
import { ControlPlaneApiError, getOperations, getOperation } from "../../lib/api";

vi.mock("@/app/ui/primitives", () => import("../ui/primitives"));
vi.mock("@/lib/operation-presentation", () => import("../../lib/operation-presentation"));
vi.mock("@/lib/principal", () => ({ getPrincipalForwardHeaders: vi.fn().mockResolvedValue(null), getCurrentPrincipal: vi.fn().mockResolvedValue(null) }));
vi.mock("../../lib/api", async (importOriginal) => ({ ...await importOriginal<object>(), getOperations: vi.fn(), getOperation: vi.fn() }));
vi.mock("@/lib/api", () => import("../../lib/api"));
vi.mock("next/navigation", () => ({ useRouter: () => ({ refresh: vi.fn(), push: vi.fn() }), notFound: () => { throw new Error("NEXT_NOT_FOUND"); } }));
beforeEach(() => vi.clearAllMocks());

describe("Operation workspace states and URL filters", () => {
  it("preserves filters in pagination without fetching machine inventory", async () => {
    vi.mocked(getOperations).mockResolvedValue({ total: 2, next_cursor: "next-page", items: [{
      id: "op-1", agent_id: "agent-1", action_type: "docker_compose_deploy", rollback_of: "op-0",
      status: "verifying", risk_level: "high", requested_by: "operator", confirmed_by: "approver",
      requested_at: "2026-09-08T12:00:00Z", expires_at: "2026-09-08T12:05:00Z", completed_at: null,
      impact_summary: "one service", machine: "web-01", service: "api", environment: "production",
    }] });
    const html = renderToStaticMarkup(await OperationsPage({ searchParams: Promise.resolve({ status: "verifying", requested_by: "operator" }) }));
    expect(html).toContain("显式回滚");
    expect(html).toContain("健康验证中");
    expect(html).toContain("cursor=next-page");
    expect(html).toContain("requested_by=operator");
    expect(html).toContain('href="/operations/op-0"');
    expect(html).not.toContain("确认并签发");
    expect(getOperations).toHaveBeenCalledTimes(1);
  });
  it("renders a true empty list", async () => {
    vi.mocked(getOperations).mockResolvedValue({ total: 0, next_cursor: null, items: [] });
    const html = renderToStaticMarkup(await OperationsPage({ searchParams: Promise.resolve({}) }));
    expect(html).toContain("没有匹配的操作");
    expect(html).not.toContain("下一页");
  });
  it.each([[403, "无权读取操作"], [422, "筛选或分页条件无效"], [503, "操作列表暂时不可用"]])("distinguishes list failure %s", async (code, label) => {
    vi.mocked(getOperations).mockRejectedValue(new ControlPlaneApiError(Number(code)));
    const html = renderToStaticMarkup(await OperationsPage({ searchParams: Promise.resolve({}) }));
    expect(html).toContain(String(label));
    expect(html).not.toContain("没有匹配的操作");
  });
  it("preserves Next not-found semantics only for a real 404", async () => {
    vi.mocked(getOperation).mockRejectedValue(new ControlPlaneApiError(404));
    await expect(OperationDetailPage({ params: Promise.resolve({ id: "missing" }) })).rejects.toThrow("NEXT_NOT_FOUND");
    expect(renderToStaticMarkup(OperationNotFound())).toContain("操作不存在");
  });
  it.each([[401, "无权读取操作"], [403, "无权读取操作"], [503, "操作详情暂时不可用"]])("distinguishes detail failure %s", async (code, label) => {
    vi.mocked(getOperation).mockRejectedValue(new ControlPlaneApiError(Number(code)));
    const html = renderToStaticMarkup(await OperationDetailPage({ params: Promise.resolve({ id: "op-1" }) }));
    expect(html).toContain(String(label));
    expect(html).not.toContain('type="checkbox"');
  });
});
