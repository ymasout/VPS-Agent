import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const page = readFileSync(join(process.cwd(), "app/settings/notifications/page.tsx"), "utf8");
const testPanel = readFileSync(join(process.cwd(), "app/settings/notifications/test-panel.tsx"), "utf8");

describe("notification settings safety", () => {
  it("documents secret-free configuration without rendering credential inputs", () => {
    expect(page).toContain("不回显 Webhook、签名密钥或其他凭据");
    expect(page).toContain("DINGTALK_WEBHOOK_URL");
    expect(page).toContain("DINGTALK_SECRET");
    expect(`${page}${testPanel}`).not.toContain("type=\"password\"");
    expect(testPanel).not.toContain("<textarea");
    expect(testPanel).toContain("type=\"checkbox\"");
  });

  it("keeps test messages separate from secrets and operations", () => {
    expect(page).toContain("只发送服务端固定消息");
    expect(`${page}${testPanel}`).not.toContain("/console/operations");
    expect(testPanel).toContain("/console/notification-tests/dingtalk");
  });

  it("fails closed without rendering stale notification status", () => {
    expect(page).toContain("未展示任何缓存值或凭据");
    expect(page).toContain("控制平面暂时不可用");
  });
});
