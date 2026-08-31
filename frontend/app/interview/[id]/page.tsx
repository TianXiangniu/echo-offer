"use client";

import type { FormEvent } from "react";
import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";

import {
  ApiError,
  assessSession,
  AssessmentBatchResponse,
  getSession,
  SessionView,
  submitAnswer,
} from "@/lib/api";
import { assessmentStages, type AssessmentStage } from "@/lib/assessment-flow";
import { brandCopy, interviewCopy, statusCopy } from "@/lib/ui-copy";

function newSubmissionId() {
  return globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

const categoryLabels = { project: "项目题", agent: "基础题", reliability: "工程题" } as const;

function batchErrorMessage(result: AssessmentBatchResponse) {
  const failedAssessment = result.assessments.find((item) => item.assessment.error_code);
  const messages: Record<string, string> = {
    provider_auth_failed: "评分服务配置有问题，请稍后再试。",
    provider_rate_limited: "评分服务现在比较忙，请稍后再试。",
    provider_unavailable: "评分服务暂时不可用，请稍后再试。",
    invalid_batch_case: "回答已经保存，但这次报告没有生成。可以直接重试。",
    invalid_evidence: "回答已经保存，但这次报告没有生成。可以直接重试。",
    system_error: "回答已经保存，但这次报告没有生成。可以直接重试。",
  };
  return messages[failedAssessment?.assessment.error_code ?? ""] ?? "这次没有拿到评分结果。";
}

export default function InterviewPage() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const sessionId = params.id;
  const [session, setSession] = useState<SessionView | null>(null);
  const [answerText, setAnswerText] = useState("");
  const [submissionId, setSubmissionId] = useState(newSubmissionId);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [assessment, setAssessment] = useState<AssessmentBatchResponse | null>(null);
  const [assessmentStage, setAssessmentStage] = useState<AssessmentStage | null>(null);
  const [canRetryAssessment, setCanRetryAssessment] = useState(false);

  async function loadSession() {
    try {
      setSession(await getSession(sessionId));
      setError("");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "无法读取面试状态。");
    }
  }

  useEffect(() => { void loadSession(); }, [sessionId]);

  const question = session?.current_question;

  async function generateAssessment() {
    setBusy(true);
    setError("");
    setCanRetryAssessment(false);
    setAssessmentStage("保存回答");
    try {
      setAssessmentStage("整理回答");
      const result = await assessSession(sessionId);
      setAssessment(result);
      if (result.status !== "valid") {
        setCanRetryAssessment(true);
        setError(batchErrorMessage(result));
        setAssessmentStage(null);
        return;
      }
      setAssessmentStage("生成报告");
      router.push(`/report/${sessionId}`);
    } catch (caught) {
      setCanRetryAssessment(true);
      setAssessmentStage(null);
      setError(caught instanceof Error ? "回答已经保存，但这次报告没有生成。可以直接重试。" : "这次没有拿到评分结果。");
    } finally {
      setBusy(false);
    }
  }

  async function handleAnswer(status: "submitted" | "explicit_unknown" | "skipped") {
    if (!question || busy) return;
    if (status === "submitted" && !answerText.trim()) {
      setError("请先写下回答，或选择“我不知道”。");
      return;
    }
    setBusy(true);
    setError("");
    try {
      await submitAnswer(sessionId, {
        question_id: question.id,
        client_submission_id: submissionId,
        status,
        answer_text: status === "explicit_unknown" ? "不知道" : answerText,
      });
      setAnswerText("");
      setSubmissionId(newSubmissionId());
      const next = await getSession(sessionId);
      setSession(next);
      if (next.status === "completed") await generateAssessment();
    } catch (caught) {
      if (caught instanceof ApiError && caught.status === 409) {
        setError("这次提交编号已经使用过，但内容不同。请刷新当前面试状态后再继续。");
      } else {
        setError(caught instanceof Error ? caught.message : "提交失败，请保持当前回答并重试。");
      }
    } finally {
      setBusy(false);
    }
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void handleAnswer("submitted");
  }

  if (!session && !error) {
    return <main className="signal-page grid min-h-screen place-items-center"><p className="signal-note">正在恢复面试状态…</p></main>;
  }

  const completedCount = session?.progress.completed ?? 0;
  const totalCount = session?.progress.total ?? 0;
  const currentOrder = question?.order ?? totalCount;

  return (
    <main className="signal-page">
      <div className="signal-container">
        <header className="signal-header">
          <button type="button" onClick={() => router.push("/")} className="signal-brand" aria-label={`${brandCopy.name} 首页`}>
            <span className="signal-brand-mark" aria-hidden="true">E/</span>
            <span className="signal-brand-name">{brandCopy.name}</span>
          </button>
          <div className="signal-header-meta">
            <span>{brandCopy.interview}</span>
            <strong>{interviewCopy.questionOf(currentOrder, totalCount)}</strong>
          </div>
        </header>

        <div className="signal-layout">
          <aside className="signal-rail" aria-label="答题进度">
            <p className="signal-rail-heading">答题进度</p>
            <ol className="signal-rail-list">
              <li className={`signal-rail-step ${question ? "is-active" : "is-done"}`} data-step="01">回答问题</li>
              <li className={`signal-rail-step ${assessmentStage ? "is-active" : session?.status === "completed" ? "is-done" : ""}`} data-step="02">整理回答</li>
              <li className={`signal-rail-step ${assessment?.status === "valid" ? "is-done" : ""}`} data-step="03">查看报告</li>
            </ol>
            <div className="signal-status" style={{ marginTop: 28 }}>
              <p className="signal-status-title">{completedCount} / {totalCount}</p>
              <p className="signal-status-copy">已经保存的回答</p>
            </div>
          </aside>

          <section className="signal-workspace" aria-label="面试答题工作区">
            {error && <div className="signal-alert" role="alert">{error}</div>}

            {session && question ? (
              <form onSubmit={handleSubmit}>
                <div className="signal-intro">
                  <p className="signal-eyebrow">{interviewCopy.progress} · {interviewCopy.questionOf(question.order, totalCount)}</p>
                  <div className="signal-question-meta">
                    <span className="signal-tag">{categoryLabels[question.category]}</span>
                    {question.is_anchor && <span className="signal-tag" aria-label="本题不提供提示">{interviewCopy.noHint}</span>}
                  </div>
                  <h1 className="signal-question-text">{question.prompt}</h1>
                  <p className="signal-copy">{interviewCopy.answerHelp}</p>
                </div>

                <div className="signal-panel signal-question">
                  <label className="signal-field" htmlFor="answer-text">
                    <span className="signal-field-label">你的回答</span>
                    <textarea
                      id="answer-text"
                      value={answerText}
                      onChange={(event) => setAnswerText(event.target.value)}
                      placeholder="从你的实际项目出发，写下你会如何回答……"
                      className="signal-textarea signal-answer"
                      aria-label="你的面试回答"
                    />
                  </label>
                  <div className="signal-actions signal-actions--between">
                    <div className="signal-answer-actions">
                      <button type="button" disabled={busy} onClick={() => void handleAnswer("explicit_unknown")} className="signal-button signal-button--secondary">{interviewCopy.unknown}</button>
                      <button type="button" disabled={busy} onClick={() => void handleAnswer("skipped")} className="signal-button signal-button--quiet">{interviewCopy.skip}</button>
                    </div>
                    <button type="submit" aria-label="保存并继续" disabled={busy} className="signal-button signal-button--primary">
                      {busy ? "正在保存…" : interviewCopy.saveAndContinue}
                    </button>
                  </div>
                </div>
                <p className="signal-footer">每道回答都会保存。全部答完后，系统会一次生成本场报告。</p>
              </form>
            ) : session ? (
              <section className="signal-intro" aria-label="面试完成状态">
                <p className="signal-eyebrow">{brandCopy.interview}</p>
                <h1 className="signal-title">{interviewCopy.completedTitle}</h1>
                <p className="signal-copy">{statusCopy.saved}</p>
                {assessmentStage && (
                  <div className="signal-status" style={{ marginTop: 30 }} aria-live="polite">
                    <p className="signal-status-title">{interviewCopy.generatingTitle}</p>
                    <p className="signal-status-copy">{statusCopy.generating}</p>
                    <div className="signal-progress">
                      <div className="signal-progress-line" />
                      <span className="signal-progress-label">{assessmentStage}</span>
                    </div>
                  </div>
                )}
                {!assessment && !assessmentStage && (
                  <button type="button" onClick={() => void generateAssessment()} disabled={busy} className="signal-button signal-button--primary" style={{ marginTop: 28 }}>
                    {busy ? "正在生成…" : "生成本场报告"}
                  </button>
                )}
                {canRetryAssessment && !assessmentStage && (
                  <div className="signal-status signal-status--error" style={{ marginTop: 28 }} aria-live="polite">
                    <p className="signal-status-title">{statusCopy.timeoutTitle}</p>
                    <p className="signal-progress-label">{statusCopy.timeoutReason}</p>
                    <p className="signal-status-copy">{statusCopy.timeoutDescription}</p>
                    <button type="button" onClick={() => void generateAssessment()} disabled={busy} className="signal-button signal-button--primary" style={{ marginTop: 8, width: "fit-content" }}>
                      {busy ? "正在生成…" : statusCopy.timeoutAction}
                    </button>
                  </div>
                )}
                {assessment?.status === "valid" && <button type="button" onClick={() => router.push(`/report/${sessionId}`)} className="signal-button signal-button--primary" style={{ marginTop: 28 }}>查看本场报告</button>}
              </section>
            ) : null}
          </section>
        </div>
      </div>
    </main>
  );
}
