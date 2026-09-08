"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";

import { createFoundationSession } from "@/lib/api";
import { interviewEntry, type InterviewType } from "@/lib/interview-type";
import { brandCopy, homeCopy } from "@/lib/ui-copy";

export default function HomePage() {
  const router = useRouter();
  const [starting, setStarting] = useState<InterviewType | null>(null);
  const [error, setError] = useState("");

  async function startFoundationInterview() {
    setStarting("foundation");
    setError("");
    try {
      const session = await createFoundationSession();
      router.push(`/interview/${session.session_id}`);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "创建基础面试失败，请稍后重试。");
      setStarting(null);
    }
  }

  const foundation = interviewEntry("foundation");
  const project = interviewEntry("project");

  return (
    <main className="mint-page mint-page--home">
      <div className="mint-shell">
        <header className="mint-header">
          <a className="mint-brand" href="/" aria-label={`${brandCopy.name} 首页`}>
            <span className="mint-brand-mark" aria-hidden="true">✦</span>
            <span className="mint-brand-name">{brandCopy.name}</span>
          </a>
          <nav className="mint-nav" aria-label="页面导航">
            <span className="mint-nav-current">{brandCopy.preparation}</span>
            <a className="mint-nav-link" href="/history">面试记录</a>
            <a className="mint-nav-link" href="/profile">能力概况</a>
            <a className="mint-nav-link" href="/console">模型设置</a>
          </nav>
        </header>

        <section className="mint-hero mint-home-hero" aria-label="选择面试方式">
          <div>
            <p className="mint-overline">{homeCopy.eyebrow}</p>
            <h1 className="mint-title">先选一种练习方式，<em>再开始。</em></h1>
            <p className="mint-lead">基础题练通用能力，项目题练真实经历。两种模式共用答题、追问和结果复盘。</p>
          </div>
          <aside className="mint-hero-card" aria-label="面试流程说明">
            <p className="mint-card-kicker">两种练习</p>
            <strong className="mint-hero-card-title">从会回答到讲清项目</strong>
            <p className="mint-hero-card-copy">可以先做基础题熟悉节奏，再用简历项目进行完整面试。</p>
            <span className="mint-card-spark" aria-hidden="true">↗</span>
          </aside>
        </section>

        <section className="mint-mode-section" aria-labelledby="mode-heading">
          <div className="mint-section-heading">
            <div className="mint-section-heading-main">
              <span className="mint-section-index">01</span>
              <h2 id="mode-heading" className="mint-section-title">你想练哪一类？</h2>
            </div>
            <span className="mint-section-aside">随时可以切换</span>
          </div>
          <div className="mint-mode-grid">
            <article className="mint-card mint-mode-card">
              <div className="mint-mode-card-top"><span className="mint-mode-number">A</span><span className="mint-chip">不需要简历</span></div>
              <h3 className="mint-mode-title">{foundation.title}</h3>
              <p className="mint-mode-copy">{foundation.description}</p>
              <ul className="mint-mode-list"><li>5 道技术题，覆盖常见基础</li><li>回答后可继续追问</li><li>结束后统一查看等级结果</li></ul>
              <button type="button" className="mint-button mint-button--primary mint-mode-action" onClick={() => void startFoundationInterview()} disabled={starting !== null}>
                {starting === "foundation" ? "正在准备…" : foundation.action}
              </button>
            </article>
            <article className="mint-card mint-mode-card mint-mode-card--accent">
              <div className="mint-mode-card-top"><span className="mint-mode-number">B</span><span className="mint-chip">需要简历</span></div>
              <h3 className="mint-mode-title">{project.title}</h3>
              <p className="mint-mode-copy">{project.description}</p>
              <ul className="mint-mode-list"><li>上传简历，AI 识别并整理项目</li><li>选择一个项目进入面试</li><li>围绕项目上下文连续追问</li></ul>
              <button type="button" className="mint-button mint-button--outline mint-mode-action" onClick={() => router.push(project.path)} disabled={starting !== null}>{project.action}</button>
            </article>
          </div>
        </section>

        {error && <p className="mint-alert" role="alert">{error}</p>}
        <p className="mint-footer">回答会自动保存，完成后可以在面试记录中回看结果。</p>
      </div>
    </main>
  );
}
