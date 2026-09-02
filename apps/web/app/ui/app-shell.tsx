"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import type { Principal } from "@/lib/api";
import {
  desktopNavigation,
  getPageTitle,
  isNavigationItemCurrent,
  mobilePrimaryNavigation,
} from "./navigation";
import { IconButton, StatusBadge } from "./primitives";

export type ShellPrincipalState = "verified" | "disabled" | "unavailable";

function PrincipalSummary({
  principal,
  state,
}: {
  principal: Principal | null;
  state: ShellPrincipalState;
}) {
  if (!principal) {
    return state === "unavailable"
      ? <StatusBadge tone="danger">身份不可用</StatusBadge>
      : <StatusBadge tone="neutral">Principal 未启用</StatusBadge>;
  }
  const roles = principal.roles.length ? principal.roles.join(" / ") : "无角色";
  return (
    <div className="app-principal" title={`${principal.id} · ${principal.authorization_mode}`}>
      <span className="app-principal__identity">{principal.display_name}</span>
      <span className="app-principal__role">{roles}</span>
    </div>
  );
}

export function AppShell({
  children,
  principal,
  principalState,
}: {
  children: React.ReactNode;
  principal: Principal | null;
  principalState: ShellPrincipalState;
}) {
  const pathname = usePathname();
  const [drawerOpen, setDrawerOpen] = useState(false);
  const moreButtonRef = useRef<HTMLButtonElement>(null);
  const closeButtonRef = useRef<HTMLButtonElement>(null);
  const drawerRef = useRef<HTMLElement>(null);

  useEffect(() => {
    setDrawerOpen(false);
  }, [pathname]);

  useEffect(() => {
    if (!drawerOpen) return;
    closeButtonRef.current?.focus();
    const handleDrawerKeys = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setDrawerOpen(false);
        moreButtonRef.current?.focus();
        return;
      }
      if (event.key === "Tab" && drawerRef.current) {
        const focusable = Array.from(
          drawerRef.current.querySelectorAll<HTMLElement>('a[href], button:not([disabled]), [tabindex]:not([tabindex="-1"])'),
        );
        const first = focusable[0];
        const last = focusable.at(-1);
        if (event.shiftKey && document.activeElement === first) {
          event.preventDefault();
          last?.focus();
        } else if (!event.shiftKey && document.activeElement === last) {
          event.preventDefault();
          first?.focus();
        }
      }
    };
    document.addEventListener("keydown", handleDrawerKeys);
    return () => document.removeEventListener("keydown", handleDrawerKeys);
  }, [drawerOpen]);

  const closeDrawer = () => {
    setDrawerOpen(false);
    moreButtonRef.current?.focus();
  };

  return (
    <div className="app-shell">
      <a className="skip-link" href="#main-content">跳到主要内容</a>
      <aside className="app-sidebar" aria-label="桌面端主导航">
        <Link className="app-brand" href="/" aria-label="VPS Agent 控制台总览">
          <span className="app-brand__mark" aria-hidden="true">VA</span>
          <span><strong>VPS Agent</strong><small>Operations Console</small></span>
        </Link>
        <nav className="app-sidebar__nav">
          {desktopNavigation.map((group) => (
            <div className="app-nav-group" key={group.label}>
              <p>{group.label}</p>
              {group.items.map((item) => item.href ? (
                <Link
                  aria-current={isNavigationItemCurrent(pathname, item.href) ? "page" : undefined}
                  href={item.href}
                  key={item.label}
                  title={item.description}
                >
                  <span aria-hidden="true" />{item.label}
                </Link>
              ) : (
                <span className="app-nav-item--disabled" key={item.label} title={item.description}>
                  <span aria-hidden="true" />{item.label}<small>后续</small>
                </span>
              ))}
            </div>
          ))}
        </nav>
        <div className="app-sidebar__footer">
          <span>SELF-HOSTED</span>
          <small>写操作仍以服务端授权为准</small>
        </div>
      </aside>

      <div className="app-shell__stage">
        <header className="app-topbar">
          <div><span>VPS Agent</span><strong>{getPageTitle(pathname)}</strong></div>
          <PrincipalSummary principal={principal} state={principalState} />
        </header>
        <div className="app-shell__content" id="main-content" tabIndex={-1}>{children}</div>
      </div>

      <nav className="app-mobile-nav" aria-label="移动端主导航">
        {mobilePrimaryNavigation.map((item) => item.href ? (
          <Link
            aria-current={isNavigationItemCurrent(pathname, item.href) ? "page" : undefined}
            href={item.href}
            key={item.label}
          >{item.label}</Link>
        ) : (
          <span aria-disabled="true" key={item.label} title={item.description}>{item.label}</span>
        ))}
        <button
          aria-controls="mobile-more-drawer"
          aria-expanded={drawerOpen}
          onClick={() => setDrawerOpen(true)}
          ref={moreButtonRef}
          type="button"
        >更多</button>
      </nav>

      {drawerOpen && (
        <div className="app-drawer-layer">
          <button className="app-drawer-backdrop" aria-label="关闭更多导航" onClick={closeDrawer} type="button" />
          <aside className="app-drawer" id="mobile-more-drawer" aria-label="更多导航" aria-modal="true" ref={drawerRef} role="dialog">
            <header><strong>更多</strong><IconButton label="关闭更多导航" onClick={closeDrawer} ref={closeButtonRef}>×</IconButton></header>
            <nav>
              <Link href="/services">服务<span>跨机器服务清单</span></Link>
              <Link href="/agent">助手<span>Fleet 只读对话</span></Link>
              <Link href="/repositories">仓库<span>已授权仓库</span></Link>
              <Link href="/settings/notifications">通知<span>通道与固定测试消息</span></Link>
            </nav>
            <PrincipalSummary principal={principal} state={principalState} />
          </aside>
        </div>
      )}
    </div>
  );
}
