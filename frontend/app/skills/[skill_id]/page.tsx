"use client";

import { useCallback, useEffect, useState } from "react";
import { useParams } from "next/navigation";

import {
  ApiError,
  generateSkillWiki,
  getSkillDetail,
  markSkillStudied,
  SkillDetail,
  startOpenDrill,
} from "@/lib/api";

export default function SkillDetailPage() {
  const params = useParams<{ skill_id: string }>();
  const skillId = params.skill_id;
  const [detail, setDetail] = useState<SkillDetail | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [generating, setGenerating] = useState(false);

  const load = useCallback(async () => {
    try {
      setDetail(await getSkillDetail(skillId));
      setError("");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "无法读取这个知识点。");
    }
  }, [skillId]);

  useEffect(() => {
    void load();
  }, [load]);

  async function handleStudy() {
    setBusy(true);
    setNotice("");
    try {
      await markSkillStudied(skillId);
      setNotice("已标记为学过。学过不等于会了，用一次专项练习检验吧。");
      setDetail((current) => (current ? { ...current, studied: true } : current));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "标记失败，请稍后再试。");
    } finally {
      setBusy(false);
    }
  }

  async function handleGenerate() {
    setGenerating(true);
    setNotice("");
    try {
      await generateSkillWiki(skillId);
      await load();
      setNotice("深度讲解已生成并缓存，下次打开直接可看。");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "生成失败，请稍后再试。");
    } finally {
      setGenerating(false);
    }
  }

  async function handlePractice() {
    setBusy(true);
    setNotice("");
    try {
      const result = await startOpenDrill(skillId);
      window.location.href = `/interview/${result.session_id}`;
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "无法开始练习。");
      setBusy(false);
    }
  }

  if (error && !detail) {
    return (
      <main className="mint-page mint-loading">
        <div className="mint-shell">
          <p className="mint-alert" role="alert">{error}</p>
          <a className="mint-button mint-button--outline" href="/skills">返回知识库</a>
        </div>
      </main>
    );
  }
  if (!detail) return <main className="mint-page mint-loading"><p className="mint-note">正在打开这个知识点…</p></main>;

  const sections = detail.sections;

  return (
    <main className="mint-page mint-page--skill-detail">
      <div className="mint-shell">
        <header className="mint-header">
          <a className="mint-brand" href="/" aria-label="Agent Echo 首页">
            <span className="mint-brand-mark" aria-hidden="true">✦</span>
            <span className="mint-brand-name">Agent Echo</span>
          </a>
          <nav className="mint-nav" aria-label="页面导航">
            <a className="mint-nav-link" href="/skills">知识库</a>
            <a className="mint-nav-link" href="/questions">题库</a>
            <a className="mint-nav-link" href="/profile">能力概况</a>
            <span className="mint-nav-current">{detail.name}</span>
          </nav>
        </header>

        {error && <p className="mint-alert" role="alert">{error}</p>}
        {notice && !error && <p className="mint-console-success" role="status">{notice}</p>}

        <section className="mint-profile-intro" aria-labelledby="skill-title">
          <div>
            <p className="mint-overline">{detail.category} · 知识点</p>
            <h1 id="skill-title" className="mint-profile-title">{detail.name}</h1>
          </div>
          <div className="mint-profile-counter" aria-label="当前掌握度">
            <span>我的等级</span>
            <strong>{detail.mastery.level ?? "—"}</strong>
            <span>/ 4 · {detail.mastery.sample_count} 次回答</span>
          </div>
          {detail.mastery.last_assessed_at && (
            <p className="mint-note" style={{ margin: 0, textAlign: "right" }}>
              最近评估：{new Date(detail.mastery.last_assessed_at).toLocaleDateString("zh-CN")}
              {detail.mastery.session_ordinal ? ` · 第 ${detail.mastery.session_ordinal} 场面试` : ""}
            </p>
          )}
        </section>

        <div className="mint-actions" style={{ marginBottom: 22 }}>
          <div className="mint-answer-secondary">
            <button type="button" className="mint-button mint-button--primary" onClick={() => void handlePractice()} disabled={busy}>
              用这个知识点练一次
            </button>
            <button type="button" className="mint-button mint-button--outline" onClick={() => void handleStudy()} disabled={busy || detail.studied}>
              {detail.studied ? "已标记学过" : "标记为学过"}
            </button>
          </div>
        </div>

        {detail.community_questions.length > 0 && (
          <section className="mint-card mint-report-card" style={{ marginBottom: 16 }} aria-labelledby="wiki-real-questions">
            <h2 id="wiki-real-questions" className="mint-report-section-title">真实考题</h2>
            <p className="mint-note" style={{ marginBottom: 10 }}>来自公开面经的原话，被考的次数越多排得越靠前。</p>
            <div className="mint-question-list">
              {detail.community_questions.map((question) => (
                <article className="mint-question-card" key={question.id}>
                  <p className="mint-question-text">{question.text}</p>
                  <div className="mint-question-meta">
                    <span className="mint-chip">真题</span>
                    {question.dup_count > 1 && (
                      <span className="mint-chip is-verify">高频 ×{question.dup_count}</span>
                    )}
                    <a className="mint-nav-link" href="/questions">去题库刷 →</a>
                  </div>
                </article>
              ))}
            </div>
          </section>
        )}

        {sections.definition && (
          <section className="mint-card mint-report-card" style={{ marginBottom: 16 }} aria-labelledby="wiki-definition">
            <h2 id="wiki-definition" className="mint-report-section-title">是什么</h2>
            <p className="mint-report-reason">{sections.definition}</p>
            {sections.why && <p className="mint-note" style={{ marginTop: 8 }}>面试为什么考它：{sections.why}</p>}
          </section>
        )}

        {!!sections.key_points?.length && (
          <section className="mint-card mint-report-card" style={{ marginBottom: 16 }} aria-labelledby="wiki-points">
            <h2 id="wiki-points" className="mint-report-section-title">核心答题要点</h2>
            <ul className="mint-feedback-hints">
              {sections.key_points.map((point) => <li key={point}>{point}</li>)}
            </ul>
          </section>
        )}

        {!!sections.pitfalls?.length && (
          <section className="mint-card mint-report-card" style={{ marginBottom: 16 }} aria-labelledby="wiki-pitfalls">
            <h2 id="wiki-pitfalls" className="mint-report-section-title">常见误区</h2>
            <ul className="mint-feedback-hints">
              {sections.pitfalls.map((pitfall) => <li key={pitfall}>{pitfall}</li>)}
            </ul>
          </section>
        )}

        <section className="mint-card mint-report-card" style={{ marginBottom: 16 }} aria-labelledby="wiki-deep">
          <h2 id="wiki-deep" className="mint-report-section-title">深度讲解</h2>
          {sections.deep_dive ? (
            <>
              <p className="mint-report-reason">{sections.deep_dive.mechanism}</p>
              {sections.deep_dive.personal_focus && (
                <p className="mint-report-reason" style={{ marginTop: 10 }}><strong>针对你的提示：</strong>{sections.deep_dive.personal_focus}</p>
              )}
              {!!sections.deep_dive.pitfalls_extra.length && (
                <ul className="mint-feedback-hints" style={{ marginTop: 10 }}>
                  {sections.deep_dive.pitfalls_extra.map((pitfall) => <li key={pitfall}>{pitfall}</li>)}
                </ul>
              )}
              <button type="button" className="mint-button mint-button--quiet" style={{ marginTop: 12 }} onClick={() => void handleGenerate()} disabled={generating}>
                {generating ? "正在重新生成…" : "重新生成"}
              </button>
            </>
          ) : (
            <>
              <p className="mint-note">还没有生成深度讲解。生成一次会调用模型（约几分钱），结果会缓存，之后随时可看。</p>
              <button type="button" className="mint-button mint-button--outline" style={{ marginTop: 12 }} onClick={() => void handleGenerate()} disabled={generating}>
                {generating ? "正在生成…" : "生成深度讲解"}
              </button>
            </>
          )}
        </section>

        {!!sections.examples?.length && (
          <section className="mint-card mint-report-card" style={{ marginBottom: 16 }} aria-labelledby="wiki-examples">
            <h2 id="wiki-examples" className="mint-report-section-title">示例回答（人工标注）</h2>
            {sections.examples.map((example) => (
              <div className="mint-report-block" key={example.level}>
                <p className="mint-report-label">{example.level} 级回答示例</p>
                <p className="mint-report-reason">{example.answer}</p>
              </div>
            ))}
          </section>
        )}

        {!!detail.related_questions.length && (
          <section className="mint-card mint-report-card" style={{ marginBottom: 16 }} aria-labelledby="wiki-questions">
            <h2 id="wiki-questions" className="mint-report-section-title">这个知识点的考法</h2>
            <ul className="mint-feedback-hints">
              {detail.related_questions.map((question) => <li key={question.template_id}>{question.prompt}</li>)}
            </ul>
          </section>
        )}

        {detail.recent_answer && (
          <section className="mint-card mint-report-card" aria-labelledby="wiki-recent">
            <h2 id="wiki-recent" className="mint-report-section-title">我最近的回答</h2>
            <p className="mint-report-reason">{detail.recent_answer.answer_text}</p>
            {detail.recent_answer.commentary && (
              <p className="mint-note" style={{ marginTop: 8 }}>当时的点评：{detail.recent_answer.commentary}</p>
            )}
          </section>
        )}

        <footer className="mint-footer">掌握度以面试评分为准。学过之后，用专项练习检验，过几天再验证一次。</footer>
      </div>
    </main>
  );
}
