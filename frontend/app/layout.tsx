import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Agent Echo",
  description: "Agent 应用工程师模拟面试训练平台"
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="zh-CN">
      <body>{children}</body>
    </html>
  );
}
