"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";
import { useParams, useRouter } from "next/navigation";

import { ApiError, getSession, SessionView, submitAnswer } from "@/lib/api";

function newSubmissionId() {
  return globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

const categoryLabels = { project: "项目深挖", agent: "Agent 基础", reliability: "工程可靠性" };

export default function InterviewPage() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const sessionId = params.id;
  const [session, setSession] = useState<SessionView | null>(null);
  const [answerText, setAnswerText] = useState("");
  const [submissionId, setSubmissionId] = useState(newSubmissionId);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

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
  const progressRatio = useMemo(() => session ? Math.round((session.progress.completed / session.progress.total) * 100) : 0, [session]);

  async function handleAnswer(status: "submitted" | "explicit_unknown" | "skipped") {
    if (!question || busy) return;
    if (status === "submitted" && !answerText.trim()) {
      setError("请先写下回答，或选择“我不知道”。");
      return;
    }
    setBusy(true);
    setError("");
    try {
      await submitAnswer(sessionId, { question_id: question.id, client_submission_id: submissionId, status, answer_text: status === "explicit_unknown" ? "不知道" : answerText });
      setAnswerText("");
      setSubmissionId(newSubmissionId());
      const next = await getSession(sessionId);
      if (next.status === "completed") router.push(`/report/${sessionId}`);
      else setSession(next);
    } catch (caught) {
      if (caught instanceof ApiError && caught.status === 409) setError("这次提交编号已经使用过，但内容不同。请刷新当前面试状态后再继续。");
      else setError(caught instanceof Error ? caught.message : "提交失败，请保持当前回答并重试。");
    } finally {
      setBusy(false);
    }
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void handleAnswer("submitted");
  }

  if (!session && !error) return <main className="grid min-h-screen place-items-center bg-ink text-paper">正在恢复面试状态…</main>;

  return (
    <main className="min-h-screen bg-paper text-ink">
      <div className="mx-auto max-w-6xl px-5 py-7 sm:px-10">
        <header className="flex items-center justify-between border-b border-ink/10 pb-6"><button onClick={() => router.push("/")} className="font-display text-xl">Agent Echo</button><div className="text-right text-xs text-ink/50"><span className="block uppercase tracking-[0.2em]">Unprompted interview</span><span>本地 · 不使用模型 API</span></div></header>
        {error && <div className="mt-6 rounded-2xl border border-red-700/20 bg-red-50 px-5 py-4 text-sm text-red-800">{error}</div>}
        {session && question ? (
          <section className="grid gap-10 pb-20 pt-10 lg:grid-cols-[0.35fr_0.65fr] lg:gap-20 lg:pt-16">
            <aside><p className="text-xs font-semibold uppercase tracking-[0.22em] text-signal">Session / {session.session_id.slice(0, 8)}</p><p className="mt-7 font-display text-6xl font-semibold">{String(question.order).padStart(2, "0")}</p><p className="mt-2 text-ink/50">共 {session.progress.total} 道问题</p><div className="mt-8 h-2 overflow-hidden rounded-full bg-ink/10"><div className="h-full rounded-full bg-signal transition-all" style={{ width: `${Math.max(progressRatio, 4)}%` }} /></div><div className="mt-3 flex justify-between text-xs text-ink/50"><span>已完成 {session.progress.completed}</span><span>剩余 {session.progress.total - session.progress.completed}</span></div><div className="mt-12 rounded-2xl border border-ink/10 bg-white/50 p-5 text-sm leading-7 text-ink/60"><p className="font-semibold text-ink">作答提示</p><p className="mt-2">先说结论，再解释机制、边界和工程取舍。训练阶段的辅助回答不会覆盖这次首答记录。</p></div></aside>
            <form onSubmit={handleSubmit}><div className="flex flex-wrap items-center gap-3 text-sm text-ink/55"><span className="rounded-full bg-signal/10 px-3 py-1.5 font-semibold text-signal">{categoryLabels[question.category]}</span>{question.is_anchor && <span className="rounded-full border border-ember/40 px-3 py-1.5 text-ember">锚题 · 无提示</span>}</div><h1 className="mt-7 max-w-3xl font-display text-4xl font-semibold leading-tight sm:text-6xl">{question.prompt}</h1><p className="mt-5 text-sm text-ink/45">这是你的无提示首答。回答会原样保存，并在报告中保留可回溯证据。</p><textarea value={answerText} onChange={(event) => setAnswerText(event.target.value)} placeholder="从你的实际项目出发，写下你会如何回答……" className="mt-9 min-h-64 w-full resize-y rounded-3xl border border-ink/15 bg-white/65 p-6 text-base leading-8 text-ink outline-none transition placeholder:text-ink/25 focus:border-signal" /><div className="mt-5 flex flex-col-reverse gap-3 sm:flex-row sm:items-center sm:justify-between"><div className="flex gap-3"><button type="button" disabled={busy} onClick={() => void handleAnswer("explicit_unknown")} className="rounded-xl border border-ink/15 px-4 py-3 text-sm text-ink/65 transition hover:border-ink/40 disabled:opacity-50">我不知道</button><button type="button" disabled={busy} onClick={() => void handleAnswer("skipped")} className="rounded-xl border border-ink/15 px-4 py-3 text-sm text-ink/65 transition hover:border-ink/40 disabled:opacity-50">跳过</button></div><button type="submit" disabled={busy} className="rounded-xl bg-ink px-6 py-3.5 font-semibold text-paper transition hover:bg-signal disabled:cursor-wait disabled:opacity-50">{busy ? "保存中…" : "提交首答  ↗"}</button></div></form>
          </section>
        ) : session ? (
          <section className="mx-auto max-w-xl py-24 text-center"><p className="text-sm uppercase tracking-[0.2em] text-signal">Interview complete</p><h1 className="mt-4 font-display text-4xl">这场面试已经完成。</h1><button onClick={() => router.push(`/report/${sessionId}`)} className="mt-8 rounded-xl bg-ink px-6 py-3 font-semibold text-paper">查看报告</button></section>
        ) : null}
      </div>
    </main>
  );
}
