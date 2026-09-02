import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

describe("M7.2b event and Agent conversation workspaces", () => {
  it("opens bounded event and assistant routes without adding direct execution", () => {
    const events = readFileSync(resolve(process.cwd(), "app/events/page.tsx"), "utf8");
    const assistant = readFileSync(resolve(process.cwd(), "app/assistant/page.tsx"), "utf8");
    expect(events).toContain('action="/events"');
    expect(events).toContain("getEvents(eventParams(query), headers)");
    expect(events).not.toMatch(/method="post"/i);
    expect(assistant).toContain('action="/assistant"');
    expect(assistant).toContain("getAgentConversation");
    expect(assistant).toContain("getServiceConversation");
    expect(assistant).toContain("getEventConversation");
    expect(assistant).toContain("getRepositoryConversation");
    expect(assistant).not.toContain("confirm");
  });

  it("keeps the legacy Agent entry as an explicit compatibility redirect", () => {
    const legacy = readFileSync(resolve(process.cwd(), "app/agent/page.tsx"), "utf8");
    expect(legacy).toContain('redirect("/assistant")');
  });
});
