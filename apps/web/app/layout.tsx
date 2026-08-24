import type { Metadata, Viewport } from "next";
import "./tokens.css";
import "./globals.css";
import "./ui.css";
import type { Principal } from "@/lib/api";
import { getCurrentPrincipal, getPrincipalForwardHeaders } from "@/lib/principal";
import { PwaRegistration } from "./pwa-registration";
import { AppShell } from "./ui/app-shell";

export const metadata: Metadata = {
  title: "VPS Agent Console",
  description: "可信、受控、可审计的智能运维控制台",
  manifest: "/manifest.webmanifest",
  icons: { icon: "/pwa-icon.svg", apple: "/pwa-icon.svg" },
  appleWebApp: { capable: true, statusBarStyle: "black-translucent", title: "VPS Agent" },
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover",
  themeColor: "#090b0f",
};

export default async function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  let principal: Principal | null = null;
  let principalState: "verified" | "disabled" | "unavailable" = "disabled";
  try {
    const principalHeaders = await getPrincipalForwardHeaders();
    if (principalHeaders) {
      principal = await getCurrentPrincipal();
      principalState = "verified";
    }
  } catch {
    principal = null;
    principalState = "unavailable";
  }
  return <html lang="zh-CN"><body><AppShell principal={principal} principalState={principalState}>{children}</AppShell><PwaRegistration /></body></html>;
}
