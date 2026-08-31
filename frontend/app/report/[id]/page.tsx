"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";

import { assessSession, getReport, Report } from "@/lib/api";
import { isAssessmentRetryable } from "@/lib/assessment-flow";
import { brandCopy, reportCopy, statusCopy } from "@/lib/ui-copy";

const levelLabels: Record<string, string> = {
  "0": "没有答到要点",
  "1": "知道相关概念",
  "2": "基本理解",
  "3": "能结合场景",
  "4": "讲清取舍和风险",
};

const rubricLabels: Record<string, string> = {
  mechanism: "机制",
  boundary: "边界",
  tradeoff: "取舍",
  failure_mode: "故障处理",
};

const knowledgePointLabels: Record<string, string> = {
  agent_architecture: "Agent 架构",
  tool_calling: "工具调用",
  retrieval: "检索与引用",
  memory: "记忆设计",
  evaluation: "效果评估",
  reliability: "工程可靠性",
  architecture_tradeoffs: "架构取舍",
};

function percent(value: number) {
  return `${Math.round(value * 100)}%`;
}

function labelKnowledgePoint(value: string) {
  if (knowledgePointLabels[value]) return knowledgePointLabels[value];
  const lastPart = value.split(".").at(-1) ?? value;
  return lastPart.replace(/[_-]+/g, " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function assessmentFailureMessage(result: Awaited<ReturnType<typeof assessSession>>) {
  const code = result.assessments.find((item) => item.assessment.error_code)?.assessment.error_code;
  const messages: Record<string, string> = {
    provider_auth_failed: "评分服务配置有问题，请稍后再试。",
    provider_rate_limited: "评分服务现在比较忙，请稍后再试。",
    provider_unavailable: "评分服务暂时不可用，请稍后再试。",
    invalid_batch_case: "回答已经保存，但这次报告没有生成。可以直接重试。",
    invalid_evidence: "回答已经保存，但这次报告没有生成。可以直接重试。",
    system_error: "回答已经保存，但这次报告没有生成。可以直接重试。",
  };
  return messages[code ?? ""] ?? "这次没有拿到评分结果。";
}

function reasonForLevel(level: number, evidence: string) {
  if (!evidence.trim()) return "这项没有找到可用的回答摘录。";
  if (level >= 4) return "回答有具体做法，也交代了取舍和可能出错的地方。";
  if (level === 3) return "回答有具体做法，能联系实际场景说明。";
  if (level === 2) return "回答方向基本清楚，还可以补充机制或边界。";
  if (level === 1) return "回答提到了相关概念，但还没有讲清楚怎么做。";
  return "回答中还没有足够的具体内容来判断这项表现。";
}

function KnowledgeList({ items, emptyText }: { items: Report["strengths"]; emptyText: string }) {
  if (!items.length) return <p className="signal-note">{emptyText}</p>;
  return (
    <div className="signal-report-list">
      {items.map((item) => (
        <article key={item.knowledge_point_id} className="signal-report-item">
          <div className="signal-report-item-heading">
            <h3 className="signal-report-item-title">{labelKnowledgePoint(item.knowledge_point_id)}</h3>
            <span className="signal-level">等级 {item.level} · {levelLabels[String(item.level)]}</span>
          </div>
          <div className="signal-report-block">
            <p className="signal-report-label">回答摘录</p>
            <p className="signal-quote">“{item.evidence}”</p>
          </div>
          <p className="signal-note">参考程度 {percent(item.confidence)}</p>
        </article>
      ))}
    </div>
  );
}

function statusLabel(status: string) {
  const labels: Record<string, string> = {
    pending: "等待处理",
    valid: "已完成",
    invalid: "需要检查",
    rejected: "未通过",
  };
  return labels[status] ?? status;
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
      setError("暂时无法读取本场报告，请稍后重试。");
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
      if (result.status !== "valid") {
        setError(assessmentFailureMessage(result));
        return;
      }
      setReport(await getReport(params.id));
    } catch (caught) {
      setError(caught instanceof Error ? "回答已经保存，但这次报告没有生成。可以直接重试。" : "这次没有拿到评分结果。");
    } finally {
      setRetrying(false);
    }
  }

  if (error) {
    return (
      <main className="signal-page grid min-h-screen place-items-center px-6">
        <div className="signal-workspace">
          <p className="signal-alert" role="alert">{error}</p>
          <div className="signal-actions" style={{ justifyContent: "flex-start" }}>
            <button type="button" onClick={() => void loadReport()} disabled={loading} className="signal-button signal-button--primary">{loading ? "正在读取…" : "再试一次"}</button>
            <button type="button" onClick={() => router.push("/")} className="signal-button signal-button--secondary">{statusCopy.backHome}</button>
          </div>
        </div>
      </main>
    );
  }

  if (!report) return <main className="signal-page grid min-h-screen place-items-center"><p className="signal-note">正在整理你的报告…</p></main>;

  const retryNeeded = report.assessment_status_counts
    && Object.entries(report.assessment_status_counts).some(([status, count]) => count > 0 && isAssessmentRetryable(status));

  return (
    <main className="signal-page">
      <div className="signal-container">
        <header className="signal-header">
          <button type="button" onClick={() => router.push("/")} className="signal-brand" aria-label={`${brandCopy.name} 首页`}>
            <span className="signal-brand-mark" aria-hidden="true">E/</span>
            <span className="signal-brand-name">{brandCopy.name}</span>
          </button>
          <div className="signal-header-meta" aria-label="本场报告">
            <span>{brandCopy.report}</span>
            <strong>完成后回看</strong>
          </div>
        </header>

        <div className="signal-layout">
          <aside className="signal-rail" aria-label="报告内容">
            <p className="signal-rail-heading">报告内容</p>
            <ol className="signal-rail-list">
              <li className="signal-rail-step is-active" data-step="01">整体情况</li>
              <li className="signal-rail-step" data-step="02">回答较好的地方</li>
              <li className="signal-rail-step" data-step="03">可以改进的地方</li>
              <li className="signal-rail-step" data-step="04">评分说明</li>
            </ol>
          </aside>

          <section className="signal-workspace" aria-label="本场报告工作区">
            <div className="signal-intro">
              <p className="signal-eyebrow">{brandCopy.report}</p>
              <h1 className="signal-title">{reportCopy.feedbackTitle}</h1>
              <p className="signal-copy">这份报告只根据本场已经保存的回答整理，先看具体回答，再决定下一步怎么补。</p>
              <button type="button" onClick={() => router.push("/")} className="signal-button signal-button--secondary" style={{ marginTop: 24 }}>再做一场</button>
            </div>

            <section className="signal-section" aria-labelledby="summary-heading">
              <h2 id="summary-heading" className="signal-section-label">整体情况</h2>
              <div className="signal-metrics">
                <div className="signal-metric"><span className="signal-metric-label">{reportCopy.completed}</span><strong className="signal-metric-value">{report.completion.completed}<small> / {report.completion.total}</small></strong></div>
                <div className="signal-metric"><span className="signal-metric-label">{reportCopy.goodCount}</span><strong className="signal-metric-value">{report.strengths.length}</strong></div>
                <div className="signal-metric"><span className="signal-metric-label">{reportCopy.improveCount}</span><strong className="signal-metric-value">{report.gaps.length}</strong></div>
              </div>
              <div className="signal-panel" style={{ padding: 20 }}>
                <div className="signal-detail-grid">
                  <div className="signal-detail"><span className="signal-detail-label">回答覆盖</span><strong className="signal-detail-value">{percent(report.coverage)}</strong></div>
                  <div className="signal-detail"><span className="signal-detail-label">锚题完成</span><strong className="signal-detail-value">{report.anchor_coverage.answered} / {report.anchor_coverage.total}</strong></div>
                  <div className="signal-detail"><span className="signal-detail-label">可用摘录</span><strong className="signal-detail-value">{report.valid_evidence_count}</strong></div>
                  <div className="signal-detail"><span className="signal-detail-label">平均参考程度</span><strong className="signal-detail-value">{percent(report.confidence)}</strong></div>
                </div>
              </div>
            </section>

            {report.rubric_items && (
              <section className="signal-section" aria-labelledby="answers-heading">
                <h2 id="answers-heading" className="signal-section-label">回答摘录与评分</h2>
                <div className="signal-panel" style={{ padding: 24 }}>
                  {!report.rubric_items.length && <p className="signal-note">当前没有可以展示的回答摘录。</p>}
                  {report.rubric_items.map((item) => (
                    <article key={`${item.question_id}-${item.rubric_id}`} className="signal-report-item">
                      <div className="signal-report-item-heading">
                        <h3 className="signal-report-item-title">{labelKnowledgePoint(item.knowledge_point_id)} · {rubricLabels[item.rubric_id] ?? "回答表现"}</h3>
                        <span className="signal-level">等级 {item.level} / 4</span>
                      </div>
                      <div className="signal-report-block">
                        <p className="signal-report-label">回答摘录</p>
                        <p className="signal-quote">“{item.evidence || "没有留下可展示的回答摘录。"}”</p>
                      </div>
                      <div className="signal-report-block">
                        <p className="signal-report-label">评分理由</p>
                        <p className="signal-report-reason">{reasonForLevel(item.level, item.evidence)}</p>
                      </div>
                      <p className="signal-note">参考程度 {percent(item.confidence)}</p>
                    </article>
                  ))}
                </div>
              </section>
            )}

            <section className="signal-section" aria-labelledby="strengths-heading">
              <h2 id="strengths-heading" className="signal-section-label">{reportCopy.goodAnswers}</h2>
              <div className="signal-panel" style={{ padding: 24 }}><KnowledgeList items={report.strengths} emptyText="当前还没有足够具体的回答可以归到这里。" /></div>
            </section>

            <section className="signal-section" aria-labelledby="gaps-heading">
              <h2 id="gaps-heading" className="signal-section-label">{reportCopy.improvements}</h2>
              <div className="signal-panel" style={{ padding: 24 }}><KnowledgeList items={report.gaps} emptyText="当前没有可展示的补充方向。" /></div>
            </section>

            {report.assessment_status_counts && (
              <section className="signal-section" aria-labelledby="status-heading">
                <h2 id="status-heading" className="signal-section-label">{reportCopy.scoreExplanation}</h2>
                <div className="signal-panel" style={{ padding: 24 }}>
                  <p className="signal-copy" style={{ marginTop: 0 }}>等级来自本场回答中的具体内容。没有完成或没有拿到结果的题目，不会被当成答错。</p>
                  <div className="signal-distribution" aria-label="回答等级分布">
                    {Object.entries(report.level_distribution).map(([level, count]) => (
                      <div key={level} className="signal-distribution-row">
                        <span>{level} · {levelLabels[level]}</span>
                        <div className="signal-distribution-bar"><span style={{ width: `${report.valid_evidence_count ? (count / report.valid_evidence_count) * 100 : 0}%` }} /></div>
                        <strong>{count}</strong>
                      </div>
                    ))}
                  </div>
                  <div className="signal-actions signal-actions--between">
                    <div className="signal-question-meta">
                      {Object.entries(report.assessment_status_counts).map(([status, count]) => <span key={status} className="signal-tag">{statusLabel(status)}：{count}</span>)}
                    </div>
                    {retryNeeded && <button type="button" onClick={() => void retryAssessment()} disabled={retrying} className="signal-button signal-button--secondary">{retrying ? "正在生成…" : statusCopy.timeoutAction}</button>}
                  </div>
                  <p className="signal-footer">本场没有综合分数。先看回答摘录和评分理由，更容易知道下一次该补哪一段。</p>
                </div>
              </section>
            )}
          </section>
        </div>
      </div>
    </main>
  );
}
