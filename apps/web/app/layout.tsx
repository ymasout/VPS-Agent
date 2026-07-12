import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "VPS Agent Console",
  description: "可信、受控、可审计的智能运维控制台",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="zh-CN"><body>{children}</body></html>;
}

