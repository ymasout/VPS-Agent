import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const page = readFileSync(join(process.cwd(), "app/settings/notifications/page.tsx"), "utf8");

describe("notification settings safety", () => {
  it("documents secret-free configuration without rendering credential inputs", () => {
    expect(page).toContain("不回显 Webhook、签名密钥或其他凭据");
    expect(page).toContain("DINGTALK_WEBHOOK_URL");
    expect(page).toContain("DINGTALK_SECRET");
    expect(page).not.toContain("<input");
    expect(page).not.toContain("type=\"password\"");
  });

  it("does not add test-send or operation controls in the first slice", () => {
    expect(page).toContain("不提供页面录入秘密、测试发送或运行时改配置");
    expect(page).not.toContain("method: \"POST\"");
    expect(page).not.toContain("/console/operations");
  });

  it("fails closed without rendering stale notification status", () => {
    expect(page).toContain("未展示任何缓存值或凭据");
    expect(page).toContain("控制平面暂时不可用");
  });
});
