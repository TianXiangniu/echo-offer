import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Echo Offer · Agent 面试准备",
  description: "从简历开始，把你做过的 Agent 项目讲清楚。"
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="zh-CN">
      <body>{children}</body>
    </html>
  );
}
