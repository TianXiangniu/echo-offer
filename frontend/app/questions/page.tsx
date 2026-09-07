"use client";

import { useEffect, useState } from "react";

import {
  CommunityQuestionList,
  createCommunityQuestion,
  deleteCommunityQuestion,
  getCommunityQuestions,
} from "@/lib/api";

const PAGE_SIZE = 50;
const PHASES = ["项目", "八股", "手撕", "HR"];

export default function QuestionsPage() {
  const [data, setData] = useState<CommunityQuestionList | null>(null);
  const [error, setError] = useState("");
  const initial = new URLSearchParams(
    typeof window === "undefined" ? "" : window.location.search,
  );
  const [phase, setPhase] = useState(initial.get("phase") ?? "");
  const [knowledgePoint, setKnowledgePoint] = useState(initial.get("kp") ?? "");
  const [offset, setOffset] = useState(Number(initial.get("offset") ?? 0) || 0);
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    const params = new URLSearchParams();
    if (phase) params.set("phase", phase);
    if (knowledgePoint) params.set("kp", knowledgePoint);
    if (offset) params.set("offset", String(offset));
    const query = params.toString();
    window.history.replaceState(null, "", query ? `?${query}` : window.location.pathname);
  }, [phase, knowledgePoint, offset]);

  const [confirmingId, setConfirmingId] = useState<string | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [draftText, setDraftText] = useState("");
  const [draftPhase, setDraftPhase] = useState("八股");
  const [draftKnowledgePoint, setDraftKnowledgePoint] = useState("");
  const [formError, setFormError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    let active = true;
    setError("");
    getCommunityQuestions({ phase, knowledgePoint, limit: PAGE_SIZE, offset })
      .then((result) => {
        if (!active) return;
        setData((previous) => {
          if (previous && offset > 0) {
            return { ...result, questions: [...previous.questions, ...result.questions] };
          }
          return result;
        });
      })
      .catch((caught) => {
        if (active) setError(caught instanceof Error ? caught.message : "无法读取题库。");
      });
    return () => {
      active = false;
    };
  }, [phase, knowledgePoint, offset, reloadKey]);

  const pickPhase = (value: string) => {
    setPhase(value);
    setOffset(0);
  };

  const pickKnowledgePoint = (value: string) => {
    setKnowledgePoint(value);
    setOffset(0);
  };

  const handleDelete = async (id: string) => {
    if (confirmingId !== id) {
      setConfirmingId(id);
      window.setTimeout(() => {
        setConfirmingId((current) => (current === id ? null : current));
      }, 3000);
      return;
    }
    setConfirmingId(null);
    try {
      await deleteCommunityQuestion(id);
      setData((previous) =>
        previous
          ? {
              ...previous,
              total: Math.max(0, previous.total - 1),
              questions: previous.questions.filter((question) => question.id !== id),
            }
          : previous,
      );
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "删除失败。");
    }
  };

  const submitNew = async (event: React.FormEvent) => {
    event.preventDefault();
    if (draftText.trim().length < 4) {
      setFormError("题目太短了，至少 4 个字。");
      return;
    }
    setSubmitting(true);
    setFormError("");
    try {
      const created = await createCommunityQuestion({
        text: draftText,
        phase: draftPhase,
        knowledgePoint: draftKnowledgePoint,
      });
      setDraftText("");
      setDraftKnowledgePoint("");
      setShowForm(false);
      if (phase === "" && knowledgePoint === "" && offset === 0) {
        setData((previous) =>
          previous
            ? { ...previous, total: previous.total + 1, questions: [created, ...previous.questions] }
            : previous,
        );
      } else {
        setFormError("已添加。当前处于筛选视图，清除筛选后即可看到新题。");
        setReloadKey((key) => key + 1);
      }
    } catch (caught) {
      setFormError(caught instanceof Error ? caught.message : "添加失败。");
    } finally {
      setSubmitting(false);
    }
  };

  const questions = data?.questions ?? [];
  const hasMore = data != null && questions.length < data.total;

  return (
    <main className="mint-page mint-page--questions">
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
            <a className="mint-nav-link" href="/skills">知识库</a>
            <span className="mint-nav-current">题库</span>
          </nav>
        </header>

        <section className="mint-profile-intro" aria-labelledby="questions-title">
          <div>
            <p className="mint-overline">真实战场</p>
            <h1 id="questions-title" className="mint-profile-title">面经题库</h1>
            <p className="mint-lead">
              全部题目来自近期公开面经帖的原话，追问链合并进母题。可以手动补充题目，没必要的题删两下即可移除。
            </p>
          </div>
          {data && (
            <div className="mint-profile-counter" aria-label="题目数量">
              <span>共收录</span>
              <strong>{data.total}</strong>
              <span>题</span>
            </div>
          )}
        </section>

        <div className="mint-filter-row" role="group" aria-label="题型筛选">
          <button
            type="button"
            className={`mint-chip mint-filter${phase === "" ? " is-active" : ""}`}
            onClick={() => pickPhase("")}
          >
            全部
          </button>
          {(data?.phases ?? []).map((item) => (
            <button
              type="button"
              key={item.value}
              className={`mint-chip mint-filter${phase === item.value ? " is-active" : ""}`}
              onClick={() => pickPhase(item.value)}
            >
              {item.value} {item.count}
            </button>
          ))}
          <button
            type="button"
            className="mint-chip mint-filter"
            style={{ marginLeft: "auto" }}
            onClick={() => setShowForm((open) => !open)}
          >
            {showForm ? "收起" : "＋ 添加题目"}
          </button>
        </div>

        {showForm && (
          <form className="mint-question-form" onSubmit={submitNew}>
            <textarea
              placeholder="输入题目，追问可以换行写在后面（追问1：…）"
              value={draftText}
              onChange={(event) => setDraftText(event.target.value)}
              required
            />
            <div className="mint-question-form-row">
              <select
                className="mint-filter-select"
                aria-label="题型"
                value={draftPhase}
                onChange={(event) => setDraftPhase(event.target.value)}
              >
                {PHASES.map((item) => (
                  <option key={item} value={item}>{item}</option>
                ))}
              </select>
              <input
                placeholder="知识点（可留空）"
                value={draftKnowledgePoint}
                onChange={(event) => setDraftKnowledgePoint(event.target.value)}
              />
              <button type="submit" className="mint-button" disabled={submitting}>
                {submitting ? "添加中…" : "添加"}
              </button>
            </div>
            {formError && <p className="mint-alert" role="alert">{formError}</p>}
          </form>
        )}

        <div className="mint-filter-row" role="group" aria-label="知识点筛选">
          <select
            className="mint-filter-select"
            aria-label="按知识点筛选"
            value={knowledgePoint}
            onChange={(event) => pickKnowledgePoint(event.target.value)}
          >
            <option value="">全部知识点</option>
            {(data?.knowledge_points ?? []).map((item) => (
              <option key={item.value} value={item.value}>
                {item.value}（{item.count}）
              </option>
            ))}
          </select>
        </div>

        {error && <p className="mint-alert" role="alert">{error}</p>}
        {!data && !error && <p className="mint-note">正在读取题库…</p>}

        {data && !questions.length && (
          <div className="mint-card mint-profile-empty">
            <p className="mint-note">这个筛选条件下还没有题目。</p>
          </div>
        )}

        {questions.length > 0 && (
          <div className="mint-question-list">
            {questions.map((question) => (
              <article className="mint-question-card" key={question.id}>
                <p className="mint-question-text">{question.text}</p>
                <div className="mint-question-meta">
                  <span className="mint-phase-tag" data-phase={question.phase}>
                    {question.phase}
                  </span>
                  {question.dup_count > 1 && (
                    <span className="mint-chip is-verify">高频 ×{question.dup_count}</span>
                  )}
                  {!question.note_url && <span className="mint-chip">手动添加</span>}
                  {question.linked_skill_id ? (
                    <a
                      className="mint-question-kp"
                      href={`/skills/${encodeURIComponent(question.linked_skill_id)}`}
                    >
                      {question.knowledge_point_label} · 看讲解 →
                    </a>
                  ) : (
                    <span className="mint-question-kp">{question.knowledge_point_label}</span>
                  )}
                  <span className="mint-question-actions">
                    <button
                      type="button"
                      className={`mint-question-delete${confirmingId === question.id ? " is-confirming" : ""}`}
                      onClick={() => handleDelete(question.id)}
                    >
                      {confirmingId === question.id ? "再点一次确认删除" : "删除"}
                    </button>
                  </span>
                </div>
              </article>
            ))}
          </div>
        )}

        {hasMore && (
          <p className="mint-note" style={{ marginTop: 18 }}>
            <button
              type="button"
              className="mint-chip mint-filter"
              onClick={() => setOffset(offset + PAGE_SIZE)}
            >
              加载更多（已显示 {questions.length} / {data?.total}）
            </button>
          </p>
        )}

        <footer className="mint-footer">题目均保留原始问法，仅供个人备考学习使用。</footer>
      </div>
    </main>
  );
}
