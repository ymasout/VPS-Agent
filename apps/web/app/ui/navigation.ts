export type NavigationItem = {
  label: string;
  href?: string;
  description: string;
};

export type NavigationGroup = {
  label: string;
  items: NavigationItem[];
};

export const desktopNavigation: NavigationGroup[] = [
  {
    label: "概览",
    items: [{ label: "总览", href: "/", description: "当前 Fleet 与事件摘要" }],
  },
  {
    label: "基础设施",
    items: [
      { label: "Fleet", href: "/fleet", description: "机器状态与资源" },
      { label: "服务", href: "/services", description: "跨机器服务清单" },
    ],
  },
  {
    label: "事件与处置",
    items: [
      { label: "事件", description: "列表工作区将在 M7.2b 开放" },
      { label: "操作", description: "列表工作区将在 M7.3 开放" },
    ],
  },
  {
    label: "知识",
    items: [
      { label: "助手", href: "/agent", description: "Fleet 只读对话" },
      { label: "仓库", href: "/repositories", description: "已授权仓库" },
      { label: "Runbook", description: "列表工作区将在 M7.4 开放" },
    ],
  },
  {
    label: "设置",
    items: [
      { label: "通知", href: "/settings/notifications", description: "通道与固定测试消息" },
    ],
  },
];

export const mobilePrimaryNavigation: NavigationItem[] = [
  { label: "总览", href: "/", description: "运维总览" },
  { label: "Fleet", href: "/fleet", description: "机器状态与资源" },
  { label: "事件", href: "/mobile#events", description: "移动事件状态" },
  { label: "操作", description: "操作列表将在 M7.3 开放" },
];

const pageTitles: Array<{ matches: (pathname: string) => boolean; title: string }> = [
  { matches: (pathname) => pathname === "/", title: "运维总览" },
  { matches: (pathname) => pathname === "/mobile", title: "移动状态" },
  { matches: (pathname) => pathname === "/fleet", title: "Fleet" },
  { matches: (pathname) => pathname === "/services", title: "服务" },
  { matches: (pathname) => pathname === "/agent", title: "Agent 对话" },
  { matches: (pathname) => pathname.startsWith("/servers/"), title: "机器详情" },
  { matches: (pathname) => pathname.startsWith("/events/"), title: "事件详情" },
  { matches: (pathname) => pathname.startsWith("/operations/"), title: "Operation 详情" },
  { matches: (pathname) => pathname === "/repositories", title: "仓库" },
  { matches: (pathname) => pathname.startsWith("/repositories/"), title: "仓库详情" },
  { matches: (pathname) => pathname.startsWith("/runbook-drafts/"), title: "Runbook 草稿" },
  { matches: (pathname) => pathname === "/settings/notifications", title: "通知" },
];

export function getPageTitle(pathname: string) {
  return pageTitles.find((entry) => entry.matches(pathname))?.title ?? "控制台";
}

export function isNavigationItemCurrent(pathname: string, href: string) {
  const hrefPath = href.split("#", 1)[0];
  if (hrefPath === "/") return pathname === "/";
  return pathname === hrefPath || pathname.startsWith(`${hrefPath}/`);
}
