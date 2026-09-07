"use client";

import { useEffect, useState } from "react";

import { getSkills, SkillSummary } from "@/lib/api";

const categoryOrder = ["项目", "Agent与RAG", "Agent运行时", "工程实践", "其他"];

const categoryCopy: Record<string, string> = {
  项目: "项目表达",
  Agent与RAG: "Agent 与 RAG",
  Agent运行时: "Agent 运行时",
  工程实践: "工程实践",
  其他: "实战与行为",
};

export default function SkillsPage() {
  const [skills, setSkills] = useState<SkillSummary[] | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;
    getSkills()
      .then((data) => {
        if (active) setSkills(data.skills);
      })
      .catch((caught) => {
        if (active) setError(caught instanceof Error ? caught.message : "无法读取知识库。");
      });
    return () => {
      active = false;
    };
  }, []);

  const grouped = categoryOrder
    .map((category) => ({
      category,
      items: (skills ?? []).filter((skill) => skill.category === category),
    }))
    .filter((group) => group.items.length);

  return (
    <main className="mint-page mint-page--skills">
      <div className="mint-shell">
        <header className="mint-header">
          <a className="mint-brand" href="/" aria-label="Agent Echo 首页">
            <span className="mint-brand-mark" aria-hidden="true">✦</span>
            <span className="mint-brand-name">Agent Echo</span>
          </a>
          <nav className="mint-nav" aria-label="页面导航">
            <a className="mint-nav-link" href="/">返回准备</a>
            <a className="mint-nav-link" href="/history">面试记录</a>
            <a className="mint-nav-link" href="/profile">能力概况</a>
            <span className="mint-nav-current">知识库</span>
            <a className="mint-nav-link" href="/questions">题库</a>
          </nav>
        </header>

        <section className="mint-profile-intro" aria-labelledby="skills-title">
          <div>
            <p className="mint-overline">边面边学</p>
            <h1 id="skills-title" className="mint-profile-title">知识点知识库</h1>
            <p className="mint-lead">每个考点都有讲解、要点和示例回答。答完题回来学，效果最好。</p>
          </div>
          {skills && (
            <div className="mint-profile-counter" aria-label="知识点数量">
              <span>已收录</span>
              <strong>{skills.length}</strong>
              <span>个</span>
            </div>
          )}
        </section>

        {error && <p className="mint-alert" role="alert">{error}</p>}
        {!skills && !error && <p className="mint-note">正在读取知识库…</p>}

        {skills && !grouped.length && (
          <div className="mint-card mint-profile-empty"><p className="mint-note">知识库还没有内容。</p></div>
        )}

        {grouped.map((group) => (
          <section key={group.category} className="mint-profile-section" aria-labelledby={`skills-${group.category}`}>
            <div className="mint-profile-section-heading">
              <div>
                <p className="mint-overline">{categoryCopy[group.category] ?? group.category}</p>
                <h2 id={`skills-${group.category}`} className="mint-profile-section-title">{group.category}</h2>
              </div>
            </div>
            <div className="mint-skill-grid">
              {group.items.map((skill) => (
                <a className="mint-card mint-skill-card" href={`/skills/${encodeURIComponent(skill.skill_id)}`} key={skill.skill_id}>
                  <div className="mint-skill-card-head">
                    <h3>{skill.name}</h3>
                    {!skill.studied && <span className="mint-chip">未学习</span>}
                    {skill.has_deep_dive && <span className="mint-chip">有深讲</span>}
                  </div>
                  <div className="mint-skill-bar">
                    <span className="mint-skill-bar-fill" style={{ width: `${((skill.level ?? 0) / 4) * 100}%` }} />
                  </div>
                  <p className="mint-note">
                    {skill.level != null ? `当前等级 ${skill.level} / 4` : "还没有回答记录"} · {skill.sample_count} 次回答
                  </p>
                </a>
              ))}
            </div>
          </section>
        ))}

        <footer className="mint-footer">讲解内容由预置要点与 AI 深讲组成，掌握度以你的面试评分为准。</footer>
      </div>
    </main>
  );
}
