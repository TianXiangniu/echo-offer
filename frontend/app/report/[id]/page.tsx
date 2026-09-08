"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";

import { ApiError, assessSession, getReport, Report } from "@/lib/api";
import { isAssessmentRetryable } from "@/lib/assessment-flow";
import { assessmentFailureMessage, hasUsableAssessmentResult } from "@/lib/assessment-copy";
import { brandCopy, reportCopy, statusCopy } from "@/lib/ui-copy";
import { rubricGrade } from "@/lib/format";
import { interviewEntryPath, interviewTypeLabel } from "@/lib/interview-type";

const levelLabels: Record<string, string> = {
  "0": "没有答到关键点",
  "1": "提到过，但没展开",
  "2": "方向对了，还不完整",
  "3": "讲得清楚，也联系了实际",
  "4": "讲得深入，考虑了取舍",
};

const rubricLabels: Record<string, string> = {
  correctness: "概念对不对",
  mechanism: "怎么工作",
  scenario: "场景里怎么用",
  engineering: "边界与故障",
  boundary: "什么情况下不适合",
  tradeoff: "为什么这样选",
  failure_mode: "出问题怎么办",
};

const knowledgePointLabels: Record<string, string> = {
  "project.ownership_and_context": "项目职责",
  "project.architecture_tradeoffs": "方案取舍",
  "project.evaluation_and_reproducibility": "结果验证",
  "rag.retrieval_diagnosis": "检索排查",
  "rag.query_rewrite_and_hybrid_retrieval": "检索优化",
  "agent_runtime.tool_calling": "工具调用",
  "engineering.latency_diagnosis": "延迟排查",
  "engineering.output_safety": "输出安全",
  "mcp.tool_ecosystem": "MCP 工具生态",
  "multi_agent.orchestration": "多智能体编排",
  "evals.observability": "评估与可观测",
  "memory.design": "记忆设计",
  "coding.debug_tool_call": "实战找问题",
  "coding.write_tool_loop": "手写工具循环",
  "design.agent_platform": "Agent 平台设计",
  "design.rag_system": "RAG 系统设计",
  "behavioral.project_conflict": "项目分歧处理",
  "behavioral.failure_story": "事故复盘",
  agent_architecture: "Agent 设计",
  tool_calling: "工具调用",
  retrieval: "资料检索",
  memory: "记忆设计",
  evaluation: "效果评估",
  reliability: "稳定性",
  architecture_tradeoffs: "方案取舍",
};

function labelKnowledgePoint(value: string) {
  if (knowledgePointLabels[value]) return knowledgePointLabels[value];
  const lastPart = value.split(".").at(-1) ?? value;
  return lastPart.replace(/[_-]+/g, " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function percent(value: number) {
  return `${Math.round(value * 100)}%`;
}

function levelLabel(value: number | string) {
  return levelLabels[String(value)] ?? "暂时无法判断";
}

function reasonForLevel(level: number, answer: string) {
  if (!answer.trim()) return "这题没有留下可以判断的回答。";
  if (level >= 4) return "回答有具体做法，也交代了为什么这样选和可能出错的地方。";
  if (level === 3) return "回答有具体做法，也能联系实际场景说明。";
  if (level === 2) return "回答方向基本清楚，可以再补充怎么工作或什么情况下不适用。";
  if (level === 1) return "回答提到了相关概念，但还没有展开具体做法。";
  return "回答中还没有足够的具体内容来判断这一点。";
}

function KnowledgeList({ items, emptyText }: { items: Report["strengths"]; emptyText: string }) {
  if (!items.length) return <p className="mint-note">{emptyText}</p>;
  return (
    <div className="mint-report-list">
      {items.map((item) => (
        <article key={item.knowledge_point_id} className="mint-report-item">
          <div className="mint-report-item-heading"><h3 className="mint-report-item-title">{labelKnowledgePoint(item.knowledge_point_id)}</h3><span className="mint-level">{rubricGrade(item.level)} 级 · {levelLabel(item.level)}</span></div>
          <div className="mint-report-block"><p className="mint-report-label">你的回答</p><p className="mint-quote">“{item.evidence || "没有留下可展示的回答。"}”</p></div>
        </article>
      ))}
    </div>
  );
}

function statusLabel(status: string) {
  const labels: Record<string, string> = { pending: "等待处理", valid: "已完成", invalid: "评分无效，可重评", rejected: "暂不展示" };
  return labels[status] ?? "处理中";
}

export default function ReportPage() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const [report, setReport] = useState<Report | null>(null);
  const [error, setError] = useState("");
  const [retrying, setRetrying] = useState(false);
  const [loading, setLoading] = useState(true);

  async function loadReport() {
    setLoading(true);
    setError("");
    try {
      setReport(await getReport(params.id));
    } catch {
      setError("暂时无法读取本场结果，请稍后重试。" );
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { void loadReport(); }, [params.id]);

  async function retryAssessment() {
    setRetrying(true);
    setError("");
    try {
      const result = await assessSession(params.id);
      if (!hasUsableAssessmentResult(result)) {
        setError(assessmentFailureMessage(result));
        return;
      }
      setReport(await getReport(params.id));
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "整理结果时遇到了本地错误，可以再试一次。" );
    } finally {
      setRetrying(false);
    }
  }

  if (error) return <main className="mint-page mint-loading"><div className="mint-shell"><p className="mint-alert" role="alert">{error}</p><div className="mint-report-actions"><button type="button" onClick={() => void loadReport()} disabled={loading} className="mint-button mint-button--primary">{loading ? "正在读取…" : "再试一次"}</button><button type="button" onClick={() => router.push("/")} className="mint-button mint-button--outline">{statusCopy.backHome}</button></div></div></main>;
  if (!report) return <main className="mint-page mint-loading"><p className="mint-note">正在整理你的结果…</p></main>;

  const retryNeeded = report.assessment_status_counts && Object.entries(report.assessment_status_counts).some(([status, count]) => count > 0 && isAssessmentRetryable(status));
  const anchoredQuestionIds = new Set<string>();
  const followupShownQuestions = new Set<string>();

  return (
    <main className="mint-page mint-page--report">
      <div className="mint-shell">
        <header className="mint-header">
          <button type="button" onClick={() => router.push("/")} className="mint-brand" aria-label={`${brandCopy.name} 首页`}><span className="mint-brand-mark" aria-hidden="true">✦</span><span className="mint-brand-name">{brandCopy.name}</span></button>
          <nav className="mint-nav" aria-label="结果导航"><a className="mint-nav-link" href="/skills">知识库</a><a className="mint-nav-link" href="/questions">题库</a><span className="mint-nav-current">{brandCopy.report}</span><span className="mint-nav-note">完成后回看</span></nav>
        </header>

        <section className="mint-report-intro" aria-label="本场结果介绍">
          <p className="mint-overline">{reportCopy.content}</p>
          <p className="mint-report-mode">{interviewTypeLabel(report.interview_type)}</p>
          <h1 className="mint-title">先看看答得好的地方，<br /><em>再补上缺的部分。</em></h1>
          <p className="mint-lead">这份结果只根据本场已经保存的回答整理。先看具体回答，再决定下一次怎么练。</p>
          <div className="mint-report-actions"><button type="button" onClick={() => router.push(interviewEntryPath(report.interview_type))} className="mint-button mint-button--primary">再做一场</button></div>
        </section>

        <section className="mint-summary" aria-label="整体情况">
          <div className="mint-summary-main"><span className="mint-summary-label">本场得分</span><strong className="mint-summary-number">{report.score_100 == null ? "—" : report.score_100}<small>{report.score_100 == null ? "" : " / 100"}</small></strong><p className="mint-summary-copy">{report.score_100 == null ? "完成全部题目并拿到有效评估后，这里会显示总分。" : "四个方面的回答结果汇总，满分 100。"}</p></div>
          <div className="mint-summary-stats"><div className="mint-stat"><span className="mint-stat-label">完成题目</span><strong className="mint-stat-value">{report.completion.completed}<small> / {report.completion.total}</small></strong></div><div className="mint-stat"><span className="mint-stat-label">答得扎实</span><strong className="mint-stat-value">{report.strengths.length}</strong></div><div className="mint-stat"><span className="mint-stat-label">需要补充</span><strong className="mint-stat-value">{report.gaps.length}</strong></div><div className="mint-stat"><span className="mint-stat-label">回答完整度</span><strong className="mint-stat-value">{percent(report.coverage)}</strong></div><div className="mint-stat"><span className="mint-stat-label">重点问题完成</span><strong className="mint-stat-value">{report.anchor_coverage.answered}<small> / {report.anchor_coverage.total}</small></strong></div></div>
        </section>

        {report.rubric_items && <section className="mint-report-section" aria-labelledby="answers-heading"><h2 id="answers-heading" className="mint-report-section-title">每道题的反馈</h2><div className="mint-card mint-report-card">{!report.rubric_items.length && <p className="mint-note">当前没有可以展示的回答。</p>}<div className="mint-report-list">{(() => { const groups = new Map<string, { id: string; kp: string; dims: typeof report.rubric_items }>(); for (const item of report.rubric_items) { const key = item.question_id ?? item.rubric_id; if (!groups.has(key)) groups.set(key, { id: key, kp: item.knowledge_point_id, dims: [] }); groups.get(key)!.dims.push(item); } return [...groups.values()].map((group) => { const primary = group.dims[0]; const shouldAnchor = Boolean(group.id) && group.dims.some(() => !anchoredQuestionIds.has(group.id)); if (group.dims.every(() => true) && group.id) anchoredQuestionIds.add(group.id); const followupItem = group.dims.find((d) => d.followup_question); const showFollowup = Boolean(followupItem?.followup_question) && group.id && !followupShownQuestions.has(group.id); if (showFollowup && group.id) followupShownQuestions.add(group.id); return <article key={group.id} id={shouldAnchor ? `question-${group.id}` : undefined} className="mint-report-item"><div className="mint-report-item-heading"><h3 className="mint-report-item-title"><a href={`/skills/${encodeURIComponent(group.kp)}`} className="mint-kp-link">{labelKnowledgePoint(group.kp)}</a></h3><span className="mint-question-dims">{group.dims.map((d) => <span key={d.rubric_id} className="mint-chip">{rubricLabels[d.rubric_id] ?? "回答表现"} {rubricGrade(d.level)}</span>)}</span></div><div className="mint-report-block"><p className="mint-report-label">你的回答</p><p className="mint-quote">“{primary.evidence || "没有留下可展示的回答。"}”</p></div>{showFollowup && followupItem && <div className="mint-report-block"><p className="mint-report-label">追问 · {followupItem.followup_question}</p><p className="mint-quote">“{followupItem.followup_answer || "没有留下追问回答。"}”</p></div>}<div className="mint-report-block"><p className="mint-report-label">{reportCopy.scoreReason}</p><p className="mint-report-reason">{primary.commentary || reasonForLevel(primary.level, primary.evidence)}</p></div></article>; }); })()}</div></div></section>}

        {report.transcript && !!report.transcript.length && <section className="mint-report-section" aria-labelledby="transcript-heading"><h2 id="transcript-heading" className="mint-report-section-title">完整问答回看</h2><p className="mint-note">当时的题目和你的完整回答，含追问。供回看复盘。</p><div className="mint-card mint-report-card"><div className="mint-report-list">{report.transcript.map((item) => <article key={`transcript-${item.order}`} className="mint-report-item"><div className="mint-report-item-heading"><h3 className="mint-report-item-title">{item.order === 0 ? "项目深挖" : `题 ${item.order}`} · <a href={`/skills/${encodeURIComponent(item.knowledge_point_id)}`} className="mint-kp-link">{labelKnowledgePoint(item.knowledge_point_id)}</a></h3><span className="mint-level">{item.status === "skipped" ? "已跳过" : item.status === "explicit_unknown" ? "回答了不知道" : item.level != null ? `${rubricGrade(item.level)} 级` : "未评估"}</span></div><p className="mint-report-reason" style={{ marginBottom: 8 }}>{item.prompt}</p><div className="mint-report-block"><p className="mint-report-label">你的完整回答</p><p className="mint-report-reason">{item.answer_text || "（本题没有作答。）"}</p></div>{item.followups.map((followup, index) => <div className="mint-report-block" key={`fu-${index}`}><p className="mint-report-label">追问 {index + 1} · {followup.question_text}</p><p className="mint-report-reason">{followup.answer_text || "（追问没有作答。）"}</p></div>)}</article>)}</div></div></section>}

        <section className="mint-report-section" aria-labelledby="strengths-heading"><h2 id="strengths-heading" className="mint-report-section-title">答得好的地方</h2><div className="mint-card mint-report-card"><KnowledgeList items={report.strengths} emptyText="当前还没有足够具体的回答可以归到这里。" /></div></section>
        <section className="mint-report-section" aria-labelledby="gaps-heading"><h2 id="gaps-heading" className="mint-report-section-title">可以补充的地方</h2><div className="mint-card mint-report-card"><KnowledgeList items={report.gaps} emptyText="当前没有可展示的补充方向。" /></div></section>

        <section className="mint-report-section" aria-labelledby="next-step-heading"><h2 id="next-step-heading" className="mint-report-section-title">下一步练习</h2><div className="mint-card mint-report-card"><p className="mint-report-reason">下一次回答时，可以优先把“怎么做、为什么这样选、出问题怎么办”说具体一些。先补一处最薄弱的地方，就会比背更多概念更有帮助。</p></div></section>

        {report.assessment_status_counts && <section className="mint-report-section" aria-labelledby="status-heading"><h2 id="status-heading" className="mint-report-section-title">这次结果怎么来的</h2><div className="mint-card mint-report-card"><p className="mint-report-reason">等级来自本场回答里的具体内容。没有完成或没有拿到结果的题目，不会被当成答错。总分只汇总已经拿到有效评估的回答。</p><div className="mint-distribution" aria-label="回答表现分布">{Object.entries(report.level_distribution).map(([level, count]) => <div key={level} className="mint-distribution-row"><span>{level} · {levelLabel(level)}</span><div className="mint-distribution-bar"><span style={{ width: `${report.valid_evidence_count ? (count / report.valid_evidence_count) * 100 : 0}%` }} /></div><strong>{count}</strong></div>)}</div><div className="mint-actions"> <div className="mint-question-label">{Object.entries(report.assessment_status_counts).map(([status, count]) => <span key={status} className="mint-chip">{statusLabel(status)}：{count}</span>)}</div>{retryNeeded && <button type="button" onClick={() => void retryAssessment()} disabled={retrying} className="mint-button mint-button--outline">{retrying ? "正在生成…" : statusCopy.timeoutAction}</button>}</div><p className="mint-report-footer">总分是本场有效回答的汇总，具体下一步还是看每道题的回答和等级。</p></div></section>}
      </div>
    </main>
  );
}
