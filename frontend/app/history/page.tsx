"use client";

import { useEffect, useState } from "react";

import {
  deleteInterview,
  getInterviewHistory,
  InterviewHistoryItem,
} from "@/lib/api";
import { formatDateTime } from "@/lib/format";

type HistoryState = {
  label: string;
  tone: "ready" | "pending" | "error" | "open";
  actionLabel: string;
  href: string;
};

function displayCount(value: number | null) {
  return value == null ? "—" : String(value);
}

function getHistoryState(item: InterviewHistoryItem): HistoryState {
  const href = `/report/${item.session_id}`;
  if (item.status !== "completed") {
    return {
      label: "进行中",
      tone: "open",
      actionLabel: "继续面试",
      href: `/interview/${item.session_id}`,
    };
  }

  const hasReport = item.report_status === "ready" || item.report_status === "partial";
  if (hasReport) {
    return { label: "已完成", tone: "ready", actionLabel: "查看结果", href };
  }

  const failed = item.analysis_status === "failed" || item.report_status === "invalid" || item.report_status === "rejected";
  if (failed) {
    return { label: "生成失败，可重试", tone: "error", actionLabel: "重新生成", href };
  }
  return { label: "报告待生成", tone: "pending", actionLabel: "重新生成", href };
}

export default function InterviewHistoryPage() {
  const [items, setItems] = useState<InterviewHistoryItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [feedback, setFeedback] = useState("");
  const [deletingId, setDeletingId] = useState<string>();

  async function loadHistory() {
    setLoading(true);
    setError("");
    try {
      setItems(await getInterviewHistory());
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "读取面试记录失败，请稍后重试。 ");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void loadHistory();
  }, []);

  async function handleDelete(item: InterviewHistoryItem) {
    if (!window.confirm("确定删除这条面试记录吗？")) return;
    setDeletingId(item.session_id);
    setError("");
    setFeedback("");
    try {
      await deleteInterview(item.session_id);
      setItems((current) => current.filter((entry) => entry.session_id !== item.session_id));
      setFeedback("记录已删除。");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "删除失败，请稍后重试。 ");
    } finally {
      setDeletingId(undefined);
    }
  }

  return (
    <main className="mint-page mint-page--history">
      <div className="mint-shell">
        <header className="mint-header">
          <a className="mint-brand" href="/" aria-label="Agent Echo 首页">
            <span className="mint-brand-mark" aria-hidden="true">✦</span>
            <span className="mint-brand-name">Agent Echo</span>
          </a>
          <nav className="mint-nav" aria-label="页面导航">
            <a className="mint-nav-link" href="/">返回准备</a>
            <span className="mint-nav-current">面试记录</span>
            <a className="mint-nav-link" href="/profile">能力概况</a>
            <a className="mint-nav-link" href="/console">模型设置</a>
          </nav>
        </header>

        <section className="mint-history-intro" aria-labelledby="history-title">
          <div>
            <p className="mint-overline">面试记录</p>
            <h1 id="history-title" className="mint-history-title">以前做过的面试，都在这里。</h1>
            <p className="mint-lead">每场面试都会单独保存。你可以接着完成，也可以回头看看之前的回答。</p>
          </div>
          <div className="mint-history-total" aria-label={`已保存 ${items.length} 场面试`}>
            <span>已保存</span>
            <strong>{items.length}</strong>
            <span>场面试</span>
          </div>
        </section>

        {error && (
          <div className="mint-history-feedback">
            <p className="mint-alert" role="alert">{error}</p>
            <button type="button" className="mint-button mint-button--outline" onClick={() => void loadHistory()} disabled={loading}>再试一次</button>
          </div>
        )}
        {feedback && !error && <p className="mint-console-success" role="status">{feedback}</p>}

        {loading ? (
          <div className="mint-card mint-history-empty"><p className="mint-note">正在读取面试记录…</p></div>
        ) : !items.length && !error ? (
          <section className="mint-card mint-history-empty" aria-label="空的面试记录">
            <span className="mint-history-empty-mark" aria-hidden="true">○</span>
            <h2>还没有面试记录</h2>
            <p>完成第一场面试后，记录会自动保存在这里。</p>
            <a className="mint-button mint-button--primary" href="/">开始第一场</a>
          </section>
        ) : (
          <section aria-labelledby="history-list-title">
            <div className="mint-history-list-heading">
              <h2 id="history-list-title" className="mint-history-section-title">全部记录</h2>
              <span className="mint-note">按最近开始的时间排列</span>
            </div>
            <div className="mint-history-list">
              {items.map((item) => {
                const state = getHistoryState(item);
                const deleting = deletingId === item.session_id;
                return (
                  <article className="mint-card mint-history-card" key={item.session_id}>
                    <div className="mint-history-card-top">
                      <div>
                        <p className="mint-history-date">{formatDateTime(item.created_at)}</p>
                        <p className="mint-history-mode">{item.interview_type === "foundation" ? "大模型基础面试" : "项目经历面试"}</p>
                        <h2 className="mint-history-card-title">{item.interview_type === "foundation" ? "大模型基础面试" : item.project_name || "未命名项目"}</h2>
                        <p className="mint-history-target">{item.target_title || "Agent 应用工程师"}</p>
                      </div>
                      <span className={`mint-status-pill mint-status-pill--${state.tone}`}>{state.label}</span>
                    </div>
                    <div className="mint-history-card-meta">
                      <div><span>答完题目</span><strong>{item.completed} / {item.total}</strong></div>
                      <div><span>本场得分</span><strong>{item.score_100 == null ? "—" : <>{item.score_100}<small> / 100</small></>}</strong></div>
                      <div><span>答得好的地方</span><strong>{displayCount(item.strength_count)}</strong></div>
                      <div><span>待补充的地方</span><strong>{displayCount(item.gap_count)}</strong></div>
                    </div>
                    <div className="mint-history-actions">
                      <a className="mint-button mint-button--primary" href={state.href}>{state.actionLabel}</a>
                      {item.profile_id && <a className="mint-button mint-button--outline" href={`/profile?profile_id=${encodeURIComponent(item.profile_id)}`}>看能力</a>}
                      <button type="button" className="mint-button mint-button--quiet" onClick={() => void handleDelete(item)} disabled={deleting}>{deleting ? "正在删除…" : "删除记录"}</button>
                    </div>
                  </article>
                );
              })}
            </div>
          </section>
        )}

        <footer className="mint-footer">本地单用户模式 · 之前的面试不会被新的记录覆盖</footer>
      </div>
    </main>
  );
}
