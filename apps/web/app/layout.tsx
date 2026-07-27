import type { Metadata, Viewport } from "next";
import "./globals.css";
import { MobileNav } from "./mobile-nav";
import { PwaRegistration } from "./pwa-registration";

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

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="zh-CN"><body>{children}<MobileNav /><PwaRegistration /></body></html>;
}
