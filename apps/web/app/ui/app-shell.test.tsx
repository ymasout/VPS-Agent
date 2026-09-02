import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { desktopNavigation, getPageTitle, isNavigationItemCurrent, mobilePrimaryNavigation } from "./navigation";
import { IconButton, StateView, StatusBadge } from "./primitives";

describe("M7 AppShell navigation", () => {
  it("only exposes routes that currently exist", () => {
    const linkedRoutes = desktopNavigation.flatMap((group) => group.items.flatMap((item) => item.href ?? []));
    expect(linkedRoutes).toEqual(["/", "/fleet", "/services", "/events", "/assistant", "/repositories", "/settings/notifications"]);
    expect(linkedRoutes).not.toContain("/operations");
    expect(mobilePrimaryNavigation.map((item) => item.href).filter(Boolean)).toEqual([
      "/",
      "/fleet",
      "/events",
    ]);
  });

  it("links the primary Agent workspace, keeps the legacy title, and resolves detail contexts", () => {
    expect(desktopNavigation.flatMap((group) => group.items).find((item) => item.label === "助手")?.href).toBe("/assistant");
    expect(getPageTitle("/agent")).toBe("Agent 对话");
    expect(getPageTitle("/assistant")).toBe("Agent 对话");
    expect(getPageTitle("/events")).toBe("事件");
    expect(getPageTitle("/fleet")).toBe("Fleet");
    expect(getPageTitle("/services")).toBe("服务");
    expect(getPageTitle("/events/event-1")).toBe("事件详情");
    expect(getPageTitle("/operations/operation-1")).toBe("Operation 详情");
    expect(getPageTitle("/unknown")).toBe("控制台");
  });

  it("matches navigation roots without marking overview active on every page", () => {
    expect(isNavigationItemCurrent("/", "/")).toBe(true);
    expect(isNavigationItemCurrent("/agent", "/")).toBe(false);
    expect(isNavigationItemCurrent("/repositories/repo-1", "/repositories")).toBe(true);
    expect(isNavigationItemCurrent("/fleet", "/fleet")).toBe(true);
  });
});

describe("M7 UI semantics", () => {
  it("renders textual status and accessible generic states", () => {
    expect(renderToStaticMarkup(<StatusBadge tone="warning">数据过期</StatusBadge>)).toContain("数据过期");
    const error = renderToStaticMarkup(
      <StateView state="error" title="读取失败" description="控制平面暂时不可用" />,
    );
    expect(error).toContain('role="alert"');
    expect(error).toContain("读取失败");
    expect(error).toContain("控制平面暂时不可用");
  });

  it("requires an accessible name for icon buttons", () => {
    const button = renderToStaticMarkup(<IconButton label="关闭导航">×</IconButton>);
    expect(button).toContain('aria-label="关闭导航"');
    expect(button).toContain('type="button"');
  });

  it("provides skip navigation, drawer focus handling, touch targets, and reduced motion", () => {
    const shell = readFileSync(resolve(process.cwd(), "app/ui/app-shell.tsx"), "utf8");
    const styles = readFileSync(resolve(process.cwd(), "app/ui.css"), "utf8");
    const tokens = readFileSync(resolve(process.cwd(), "app/tokens.css"), "utf8");
    expect(shell).toContain('href="#main-content"');
    expect(shell).toContain('event.key === "Escape"');
    expect(shell).toContain('event.key === "Tab"');
    expect(shell).toContain('aria-modal="true"');
    expect(styles).toContain("min-height: var(--control-height)");
    expect(styles).toContain("overflow-x: hidden");
    expect(styles).toContain("@media (prefers-reduced-motion: reduce)");
    expect(tokens).toContain("--control-height: 44px");
    expect(tokens).toContain("--focus-ring:");
  });
});
