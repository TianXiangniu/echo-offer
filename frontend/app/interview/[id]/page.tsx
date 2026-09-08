"use client";

import type { FormEvent } from "react";
import { useEffect, useRef, useState } from "react";
import { useParams, useRouter } from "next/navigation";

import { ApiError, API_BASE_URL, assessSession, AssessmentBatchResponse, decideFollowup, fetchQuestionFeedback, finishDialog, getGraphSessionState, getSession, resumeGraphSession, SessionView, skipWrapUp, startGraphSession, submitAnswer, submitDialogAnswer, submitFollowupAnswer } from "@/lib/api";
import type { AssessmentStage } from "@/lib/assessment-flow";
import { assessmentFailureMessage, hasUsableAssessmentResult } from "@/lib/assessment-copy";
import { GraphSessionView, normalizeGraphState } from "@/lib/interview-graph";
import { brandCopy, interviewCopy, statusCopy } from "@/lib/ui-copy";

function newSubmissionId() {
  return crypto.randomUUID();
}

type InputMode = "dialog" | "answer" | "followup" | "none";

const graphStatusCopy: Record<string, string> = {
  not_started: "未开始",
  active: "进行中",
  covered: "已覆盖",
  needs_confirmation: "需要确认",
};

function isGraphView(view: SessionView | GraphSessionView | null): view is GraphSessionView {
  return view?.mode === "graph" && "canAnswer" in view;
}

export default function InterviewPage() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const sessionId = params.id;
  const [session, setSession] = useState<SessionView | GraphSessionView | null>(null);
  const [answerText, setAnswerText] = useState("");
  const [submissionId, setSubmissionId] = useState(newSubmissionId);
  const [followupText, setFollowupText] = useState("");
  const [followupSubmissionId, setFollowupSubmissionId] = useState(newSubmissionId);
  const [dialogText, setDialogText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [assessment, setAssessment] = useState<AssessmentBatchResponse | null>(null);
  const [assessmentStage, setAssessmentStage] = useState<AssessmentStage | null>(null);
  const [canRetryAssessment, setCanRetryAssessment] = useState(false);
  const chatRef = useRef<HTMLDivElement | null>(null);

  async function loadSession() {
    try {
      const current = await getSession(sessionId);
      setSession(current.mode === "graph"
        ? normalizeGraphState(await startGraphSession(sessionId))
        : current);
      setError("");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "无法读取这场练习。" );
    }
  }

  useEffect(() => { void loadSession(); }, [sessionId]);

  const question = session?.current_question;
  const isDialog = session?.mode === "dialog";
  const isGraph = isGraphView(session);
  const graphSession = isGraph ? session : null;
  const stage = session?.stage ?? "knowledge";
  const timeline = session?.timeline ?? [];
  const pendingFollowup = question?.followup?.status === "pending" ? question.followup : null;
  const isFoundation = session?.interview_type === "foundation";

  // 输入坞的分派：追问回答 > 阶段对话 > 知识题作答
  const inputMode: InputMode =
    !session || session.status === "completed"
      ? "none"
      : isGraph
        ? graphSession?.canAnswer ? "answer" : "none"
      : pendingFollowup
        ? "followup"
        : isDialog && (stage === "intro" || stage === "project_dialog" || stage === "wrap_up")
          ? "dialog"
          : question
            ? "answer"
        : "none";

  useEffect(() => {
    if (!isGraph) return;
    let cancelled = false;
    const refresh = () => getGraphSessionState(sessionId)
      .then((state) => {
        if (!cancelled) setSession(normalizeGraphState(state));
      })
      .catch(() => undefined);
    const timer = window.setInterval(refresh, 5000);
    const source = new EventSource(`${API_BASE_URL}/api/sessions/${sessionId}/graph/events`);
    const onEvent = () => refresh();
    for (const eventName of ["question_ready", "candidate_answer", "completed", "state_updated"]) {
      source.addEventListener(eventName, onEvent);
    }
    source.onerror = () => source.close();
    return () => {
      cancelled = true;
      window.clearInterval(timer);
      source.close();
    };
  }, [isGraph, sessionId]);

  // 新消息自动滚到底部
  useEffect(() => {
    if (chatRef.current) {
      window.scrollTo({ top: document.documentElement.scrollHeight, behavior: "smooth" });
    }
  }, [timeline.length, session?.status, assessmentStage]);

  function hasPendingFollowup(view: SessionView | null) {
    return Boolean(view?.questions.some((item) => item.followup?.status === "pending"));
  }

  async function generateAssessment() {
    setBusy(true);
    setError("");
    setCanRetryAssessment(false);
    setAssessmentStage("保存回答");
    try {
      setAssessmentStage("整理回答");
      const result = await assessSession(sessionId);
      setAssessment(result);
      if (!hasUsableAssessmentResult(result)) {
        setCanRetryAssessment(true);
        setError(assessmentFailureMessage(result));
        setAssessmentStage(null);
        return;
      }
      if (result.status !== "valid") {
        router.push(`/report/${sessionId}`);
        return;
      }
      setAssessmentStage("生成报告");
      router.push(`/report/${sessionId}`);
    } catch (caught) {
      setCanRetryAssessment(true);
      setAssessmentStage(null);
      setError(caught instanceof ApiError ? caught.message : "整理结果时遇到了本地错误，可以再试一次。" );
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
      if (isGraph) {
        const next = normalizeGraphState(await resumeGraphSession(sessionId, {
          answer_text: status === "explicit_unknown" ? "不知道" : answerText,
          client_submission_id: submissionId,
        }));
        setAnswerText("");
        setSubmissionId(newSubmissionId());
        setSession(next);
        if (next.status === "completed") {
          if (!next.assessment) {
            await generateAssessment();
          } else {
            setAssessment(next.assessment);
            if (!hasUsableAssessmentResult(next.assessment)) {
              setCanRetryAssessment(true);
              setError(assessmentFailureMessage(next.assessment));
              return;
            }
            if (next.assessment.status !== "valid") {
              router.push(`/report/${sessionId}`);
              return;
            }
            setAssessmentStage("生成报告");
            router.push(`/report/${sessionId}`);
          }
        }
        return;
      }
      await submitAnswer(sessionId, { question_id: question.id, client_submission_id: submissionId, status, answer_text: status === "explicit_unknown" ? "不知道" : answerText });
      setAnswerText("");
      setSubmissionId(newSubmissionId());
      if (status === "submitted") {
        // 追问决策与练习反馈并行发起；任一失败都不阻塞面试流程
        const [decision] = await Promise.all([
          decideFollowup(sessionId, question.id).catch(() => null),
          fetchQuestionFeedback(sessionId, question.id).catch(() => null),
        ]);
        if (decision?.followup?.status === "pending") {
          setSession(await getSession(sessionId));
          return;
        }
      }
      const next = await getSession(sessionId);
      setSession(next);
      if (next.status === "completed" && !hasPendingFollowup(next)) await generateAssessment();
    } catch (caught) {
      if (caught instanceof ApiError && caught.status === 409) setError("这次提交编号已经使用过，请刷新当前页面后再继续。");
      else setError(caught instanceof Error ? caught.message : "提交失败，请保持当前回答并重试。" );
    } finally {
      setBusy(false);
    }
  }

  async function handleFollowupSubmit() {
    if (!question?.followup || busy) return;
    if (!followupText.trim()) {
      setError("请先写下追问的回答。");
      return;
    }
    setBusy(true);
    setError("");
    try {
      await submitFollowupAnswer(sessionId, question.id, {
        client_submission_id: followupSubmissionId,
        answer_text: followupText,
      });
      setFollowupText("");
      setFollowupSubmissionId(newSubmissionId());
      // 追问链：答完一轮后询问是否还有下一层追问
      try {
        const decision = await decideFollowup(sessionId, question.id);
        if (decision.followup?.status === "pending") {
          setSession(await getSession(sessionId));
          return;
        }
      } catch {
        // 追问收束失败不阻塞面试流程
      }
      const next = await getSession(sessionId);
      setSession(next);
      if (next.status === "completed" && !hasPendingFollowup(next)) await generateAssessment();
    } catch (caught) {
      if (caught instanceof ApiError && caught.status === 409) setError("这条追问回答已经提交过，请刷新当前页面后再继续。");
      else setError(caught instanceof Error ? caught.message : "追问提交失败，请保留内容后重试。");
    } finally {
      setBusy(false);
    }
  }

  async function handleDialogSubmit() {
    if (busy) return;
    if (!dialogText.trim()) {
      setError("请先写下你的回答。");
      return;
    }
    setBusy(true);
    setError("");
    try {
      await submitDialogAnswer(sessionId, dialogText);
      setDialogText("");
      const next = await getSession(sessionId);
      setSession(next);
      if (next.stage === "completed" && next.status === "completed") {
        await generateAssessment();
      }
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "提交失败，请保留内容后重试。");
    } finally {
      setBusy(false);
    }
  }

  async function handleSkipWrapUp() {
    setBusy(true);
    try {
      await skipWrapUp(sessionId);
      const next = await getSession(sessionId);
      setSession(next);
      if (next.status === "completed") await generateAssessment();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "操作失败，请稍后再试。");
    } finally {
      setBusy(false);
    }
  }

  async function handleFinishDialog() {
    setBusy(true);
    try {
      await finishDialog(sessionId);
      const next = await getSession(sessionId);
      setSession(next);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "操作失败，请稍后再试。");
    } finally {
      setBusy(false);
    }
  }

  function submitCurrent(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (inputMode === "followup") void handleFollowupSubmit();
    else if (inputMode === "dialog") void handleDialogSubmit();
    else void handleAnswer("submitted");
  }

  if (!session && !error) return <main className="mint-page mint-loading"><p className="mint-note">正在恢复这场练习…</p></main>;

  const totalCount = session?.progress.total ?? 0;
  const completedCount = session?.progress.completed ?? 0;
  const stageLabel =
    isDialog
      ? ({ intro: "自我介绍", project_dialog: "项目深挖", knowledge: "知识环节", wrap_up: "反问环节", completed: "面试完成" }[stage] ?? "")
      : isGraph
        ? `上下文面试 · 已答 ${completedCount}/${totalCount}`
      : isFoundation
        ? `基础题 · 已答 ${completedCount}/${totalCount}`
        : `知识环节 · 已答 ${completedCount}/${totalCount}`;
  const showTyping = busy && (inputMode === "dialog" || stage === "project_dialog");

  return (
    <main className="mint-page mint-page--interview">
      <header className="mint-header">
        <button type="button" onClick={() => router.push("/")} className="mint-brand" aria-label={`${brandCopy.name} 首页`}>
          <span className="mint-brand-mark" aria-hidden="true">✦</span><span className="mint-brand-name">{brandCopy.name}</span>
        </button>
        <nav className="mint-nav" aria-label="面试导航"><button type="button" className="mint-nav-gear" onClick={() => router.push("/console")}>⚙ 模型设置</button><span className="mint-nav-current">{brandCopy.interview}</span><span className="mint-nav-note">{stageLabel}</span></nav>
      </header>

      <div className="mint-stage-progress" aria-label="面试进度"><span style={{ width: `${totalCount ? Math.round((completedCount / totalCount) * 100) : 0}%` }} /></div>

      {isGraph && graphSession && (
        <section className="mint-graph-map" aria-label="上下文面试地图">
          <div className="mint-graph-map-head">
            <div>
              <p className="mint-graph-kicker">上下文面试地图</p>
              <h2>沿着一个项目，把答案讲完整</h2>
            </div>
            <span>{graphSession.progress.completed}/{graphSession.progress.total} 节点</span>
          </div>
          <div className="mint-graph-nodes">
            {graphSession.nodes.map((node, index) => (
              <div className={`mint-graph-node is-${node.status}`} key={node.id}>
                <span className="mint-graph-node-index">0{index + 1}</span>
                <strong>{node.label}</strong>
                <small>{graphStatusCopy[node.status] || node.status}</small>
              </div>
            ))}
          </div>
        </section>
      )}

      {isGraph && graphSession?.degraded && (
        <div className="mint-graph-degraded" role="status">
          模型暂不可用，已切换保底问题；回答仍会保存。
        </div>
      )}

      {error && <div className="mint-alert" role="alert">{error}</div>}

      <div className="mint-chat-scroll" ref={chatRef}>
        <div className="mint-chat">
          {timeline.map((message, index) => {
            if (message.role === "coach") {
              return (
                <div className="mint-coach" key={`coach-${index}`}>
                  <span className="mint-coach-ico">✎</span>
                  <span><i>悄悄说 · 不计入本场结果</i>：{message.content}</span>
                </div>
              );
            }
            const isSelf = message.role === "candidate";
            return (
              <div className={`mint-msg ${isSelf ? "self" : ""}`} key={`${message.kind}-${index}`}>
                <div className="mint-ava">{isSelf ? "我" : "✦"}</div>
                <div className="mint-msg-body">
                  <div className="mint-who">
                    {isSelf ? "我" : message.kind === "followup" ? "面试官 · 追问" : "面试官"}
                  </div>
                  <div className={`mint-bubble ${isSelf ? "is-self" : ""}`}>{message.content}</div>
                </div>
              </div>
            );
          })}

          {isFoundation && question && (
            <div className="mint-msg" key={`foundation-question-${question.id}`}>
              <div className="mint-ava">✦</div>
              <div className="mint-msg-body">
                <div className="mint-who">面试官 · 第 {question.order ?? 1} 题</div>
                <div className="mint-bubble">{question.prompt}</div>
              </div>
            </div>
          )}

          {pendingFollowup && (
            <div className="mint-msg">
              <div className="mint-ava">✦</div>
              <div className="mint-msg-body">
                <div className="mint-who">面试官 · 追问</div>
                <div className="mint-bubble">{pendingFollowup.question_text}</div>
              </div>
            </div>
          )}

          {showTyping && (
            <div className="mint-msg">
              <div className="mint-ava">✦</div>
              <div className="mint-msg-body">
                <div className="mint-bubble mint-typing" role="status" aria-label="面试官正在思考"><span /><span /><span /></div>
              </div>
            </div>
          )}

          {session?.status === "completed" && (
            <section className="mint-complete" aria-label="面试完成状态">
              <span className="mint-complete-mark" aria-hidden="true">✓</span>
              <h1 className="mint-complete-title">{interviewCopy.completedTitle}</h1>
              <p className="mint-lead" style={{ marginInline: "auto" }}>{statusCopy.saved}</p>
              {assessmentStage && <div className="mint-complete-progress" aria-live="polite"><p>{interviewCopy.generatingTitle}</p><p className="mint-note">{statusCopy.generating}</p><div className="mint-progress"><div className="mint-progress-line" /><span className="mint-progress-label">{assessmentStage}</span></div></div>}
              {canRetryAssessment && !assessmentStage && <div className="mint-retry-box" aria-live="polite"><strong>{statusCopy.timeoutTitle}</strong><p className="mint-note">{statusCopy.timeoutDescription}</p><button type="button" onClick={() => void generateAssessment()} disabled={busy} className="mint-button mint-button--primary" style={{ marginTop: 12 }}>{busy ? "正在生成…" : statusCopy.timeoutAction}</button></div>}
              {assessment && assessmentStage === null && <button type="button" onClick={() => router.push(`/report/${sessionId}`)} className="mint-button mint-button--primary" style={{ marginTop: 18 }}>查看本场结果</button>}
              {!assessment && !assessmentStage && !canRetryAssessment && <button type="button" onClick={() => void generateAssessment()} disabled={busy} className="mint-button mint-button--primary" style={{ marginTop: 18 }}>{busy ? "正在生成…" : "生成本场结果"}</button>}
            </section>
          )}
        </div>
      </div>

      {inputMode !== "none" && (
        <form className="mint-dock" onSubmit={submitCurrent} aria-label="回答输入区">
          <div className="mint-dock-inner">
            <textarea
              value={inputMode === "followup" ? followupText : inputMode === "dialog" ? dialogText : answerText}
              onChange={(event) => {
                const value = event.target.value;
                if (inputMode === "followup") setFollowupText(value);
                else if (inputMode === "dialog") setDialogText(value);
                else setAnswerText(value);
              }}
              placeholder={inputMode === "followup" ? "回答面试官的追问……" : inputMode === "dialog" ? "接着面试官的话往下说……" : "写下你的回答……"}
              className="mint-dock-textarea"
              aria-label="你的回答"
              disabled={busy}
            />
            <div className="mint-dock-row">
              <div className="mint-dock-hints">
                {inputMode === "answer" && (
                  <>
                    <button type="button" disabled={busy} onClick={() => void handleAnswer("explicit_unknown")}>我不知道</button>
                    <button type="button" disabled={busy} onClick={() => void handleAnswer("skipped")}>跳过这题</button>
                  </>
                )}
                {inputMode === "dialog" && stage === "project_dialog" && (
                  <button type="button" disabled={busy} onClick={() => void handleFinishDialog()}>提前结束深挖</button>
                )}
                {inputMode === "dialog" && stage === "wrap_up" && (
                  <button type="button" disabled={busy} onClick={() => void handleSkipWrapUp()}>跳过反问</button>
                )}
                {inputMode === "followup" && <span className="mint-dock-note">回答面试官的追问</span>}
              </div>
              <button type="submit" className="mint-send" disabled={busy} aria-label="发送回答">↑</button>
            </div>
            <div className="mint-dock-meta">回答自动保存 · 全部结束后统一评分</div>
          </div>
        </form>
      )}
    </main>
  );
}
