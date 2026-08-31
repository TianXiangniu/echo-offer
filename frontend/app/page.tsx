"use client";

import type { ChangeEvent, FormEvent } from "react";
import { useState } from "react";
import { useRouter } from "next/navigation";

import {
  AgentProjectAnalysis,
  analyzeAgentProjectStream,
  createProfile,
  createSession,
  parseResume,
  ProjectInput,
  ProjectQuestionInput,
  ResumeParseResponse,
} from "@/lib/api";
import { brandCopy, homeCopy } from "@/lib/ui-copy";

const emptyProject: ProjectInput = {
  project_name: "",
  background_goal: "",
  tech_stack: "",
  responsibilities: "",
  core_solution: "",
  engineering_challenges: "",
  failure_improvements: "",
  quantified_results: "",
};

const fields: Array<{ key: keyof ProjectInput; hint: string }> = [
  { key: "project_name", hint: "例如：企业知识库问答 Agent" },
  { key: "background_goal", hint: "它解决了什么真实问题？" },
  { key: "tech_stack", hint: "语言、框架、模型、数据库" },
  { key: "responsibilities", hint: "你亲自设计、实现和负责什么？" },
  { key: "core_solution", hint: "链路、关键模块和技术选择" },
  { key: "engineering_challenges", hint: "遇到过哪些约束、故障或权衡？" },
  { key: "failure_improvements", hint: "一次失败、定位过程和改进动作" },
  { key: "quantified_results", hint: "指标、对照和可复现的结果" },
];

const preparationSteps = ["上传简历", "检查项目内容", "开始面试"];

export default function HomePage() {
  const router = useRouter();
  const [resumeText, setResumeText] = useState("");
  const [resumeId, setResumeId] = useState<string>();
  const [resumeSource, setResumeSource] = useState<ResumeParseResponse>();
  const [project, setProject] = useState<ProjectInput>(emptyProject);
  const [analysisId, setAnalysisId] = useState<string>();
  const [analysisResult, setAnalysisResult] = useState<AgentProjectAnalysis>();
  const [projectQuestions, setProjectQuestions] = useState<ProjectQuestionInput[]>([]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [analyzing, setAnalyzing] = useState(false);
  const [analysisStage, setAnalysisStage] = useState("等待开始");

  function clearAnalysis() {
    setAnalysisId(undefined);
    setAnalysisResult(undefined);
    setProjectQuestions([]);
    setAnalysisStage("等待开始");
  }

  async function handleResumeUpload(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    if (resumeText.trim() && !window.confirm("上传文件会替换当前简历文本，是否继续？")) return;

    setUploading(true);
    setError("");
    try {
      const parsed = await parseResume(file);
      setResumeId(parsed.resume_id);
      setResumeSource(parsed);
      setResumeText(parsed.extracted_text);
      setProject(emptyProject);
      clearAnalysis();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "简历解析失败，请改为手动粘贴文本。");
    } finally {
      setUploading(false);
    }
  }

  function switchToManualResume() {
    setResumeId(undefined);
    setResumeSource(undefined);
    clearAnalysis();
  }

  function handleResumeTextChange(value: string) {
    setResumeText(value);
    if (analysisResult) clearAnalysis();
  }

  async function handleAnalyze() {
    if (!resumeId || !resumeText.trim()) {
      setError("请先上传 PDF 或 DOCX 简历，再进行整理。");
      return;
    }
    if (!window.confirm("完整简历文本将发送给硅基流动用于项目分析，是否继续？")) return;

    setAnalyzing(true);
    setAnalysisStage("正在整理项目内容…");
    setError("");
    try {
      const result = await analyzeAgentProjectStream(resumeId, resumeText, (event) => {
        if (event.event !== "stage") return;
        const messages: Record<string, string> = {
          received: "已收到简历内容…",
          analyzing: "正在整理项目内容…",
          validating: "正在生成问题…",
          completed: "整理完成",
        };
        setAnalysisStage(messages[event.data.stage] ?? "正在整理项目内容…");
      });
      setAnalysisId(result.analysis_id);
      setAnalysisResult(result);
      setProject(result.project);
      setProjectQuestions(result.questions);
    } catch (caught) {
      setAnalysisStage("整理失败，可以重试");
      setError(caught instanceof Error ? caught.message : "项目整理失败，请稍后重试。");
    } finally {
      setAnalyzing(false);
    }
  }

  function updateProjectQuestion(index: number, patch: Partial<ProjectQuestionInput>) {
    setProjectQuestions((current) => current.map((question, questionIndex) => (
      questionIndex === index ? { ...question, ...patch } : question
    )));
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const profile = await createProfile({
        resume_text: resumeText,
        resume_id: resumeId,
        analysis_id: analysisId,
        project,
        project_questions: analysisResult ? projectQuestions : undefined,
      });
      const session = await createSession(profile.profile_id);
      router.push(`/interview/${session.session_id}`);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "创建面试失败，请稍后重试。");
    } finally {
      setBusy(false);
    }
  }

  const activeStep = analysisResult ? 2 : resumeText.trim() ? 1 : 0;

  return (
    <main className="signal-page">
      <div className="signal-container">
        <header className="signal-header">
          <a className="signal-brand" href="/" aria-label={`${brandCopy.name} 首页`}>
            <span className="signal-brand-mark" aria-hidden="true">E/</span>
            <span className="signal-brand-name">{brandCopy.name}</span>
          </a>
          <div className="signal-header-meta">
            <span>准备工作区</span>
            <strong>Agent 应用工程师</strong>
          </div>
        </header>

        <div className="signal-layout">
          <aside className="signal-rail" aria-label="准备进度">
            <p className="signal-rail-heading">准备进度</p>
            <ol className="signal-rail-list">
              {preparationSteps.map((step, index) => (
                <li
                  key={step}
                  className={`signal-rail-step ${index === activeStep ? "is-active" : ""} ${index < activeStep ? "is-done" : ""}`}
                  data-step={`0${index + 1}`}
                >
                  {step}
                </li>
              ))}
            </ol>
          </aside>

          <section className="signal-workspace" aria-label="项目准备工作区">
            <div className="signal-intro">
              <p className="signal-eyebrow">{homeCopy.eyebrow}</p>
              <h1 className="signal-title">{homeCopy.projectTitle}</h1>
              <p className="signal-copy">{homeCopy.projectDescription}</p>
            </div>

            <form onSubmit={handleSubmit}>
              <section className="signal-section" aria-labelledby="resume-heading">
                <h2 id="resume-heading" className="signal-section-label">{homeCopy.uploadTitle}</h2>
                <div className="signal-panel signal-upload">
                  <div className="signal-upload-copy">
                    <p className="signal-upload-title">把简历放进来</p>
                    <p className="signal-upload-hint">{homeCopy.uploadHint} 扫描件暂不支持。</p>
                  </div>
                  <label className="signal-button signal-button--secondary">
                    <span>{uploading ? "正在解析…" : "选择文件"}</span>
                    <input
                      type="file"
                      accept=".pdf,.docx,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                      onChange={handleResumeUpload}
                      disabled={uploading || busy || analyzing}
                      className="signal-input-hidden"
                    />
                  </label>
                  {resumeSource && !uploading && (
                    <div className="signal-note">
                      {resumeSource.original_filename} · {resumeSource.unit_count}{resumeSource.source_type === "pdf" ? " 页" : " 个文本块"} · {resumeSource.character_count} 字符
                      <button type="button" onClick={switchToManualResume} disabled={analyzing || busy} className="signal-button signal-button--quiet">改为手动编辑</button>
                    </div>
                  )}
                </div>
                {uploading && <p className="signal-note">正在读取文本，请稍候…</p>}
                {resumeSource?.warnings.map((warning) => <p key={warning} className="signal-note">提示：{warning}</p>)}
              </section>

              <section className="signal-section" aria-labelledby="resume-text-heading">
                <h2 id="resume-text-heading" className="signal-section-label">简历文本</h2>
                <textarea
                  required
                  value={resumeText}
                  onChange={(event) => handleResumeTextChange(event.target.value)}
                  disabled={analyzing || uploading || busy}
                  placeholder="粘贴你的简历文本。它只作为项目上下文草稿，最终以你确认的项目事实为准。"
                  className="signal-panel signal-textarea"
                  aria-label="简历文本"
                />
              </section>

              <section className="signal-section" aria-labelledby="analysis-heading">
                <h2 id="analysis-heading" className="signal-section-label">先检查项目内容</h2>
                <div className="signal-panel signal-upload">
                  <div className="signal-upload-copy">
                    <p className="signal-upload-title">{homeCopy.analyze}</p>
                    <p className="signal-upload-hint">有简历文件时可以自动整理；整理结果仍然需要你确认。</p>
                  </div>
                  <button type="button" onClick={handleAnalyze} disabled={!resumeId || !resumeText.trim() || analyzing || busy || uploading} className="signal-button signal-button--primary">
                    {analyzing ? "正在整理…" : analysisResult ? homeCopy.analyzeAgain : "开始整理"}
                  </button>
                </div>
                {analyzing && (
                  <div className="signal-progress" aria-live="polite">
                    <div className="signal-progress-line" />
                    <span className="signal-progress-label">{analysisStage}</span>
                  </div>
                )}
                {!resumeId && <p className="signal-note">上传 PDF 或 DOCX 后，可以自动整理项目内容；也可以直接手动填写。</p>}
              </section>

              {analysisResult && (
                <section className="signal-section" aria-labelledby="analysis-result-heading">
                  <h2 id="analysis-result-heading" className="signal-section-label">整理结果</h2>
                  <div className="signal-panel signal-analysis">
                    <div className="signal-analysis-summary">
                      <div>
                        <p className="signal-analysis-title">已找到：{project.project_name || "未命名项目"}</p>
                        <p className="signal-note">{analysisResult.selection_reason}</p>
                      </div>
                      <span className="signal-tag">参考程度 {Math.round(analysisResult.confidence * 100)}%</span>
                    </div>
                    {analysisResult.missing_information.length > 0 && (
                      <p className="signal-note">还需要补充：{analysisResult.missing_information.join("；")}</p>
                    )}
                    <div className="signal-analysis-list">
                      {projectQuestions.map((question, index) => (
                        <div key={index} className="signal-field">
                          <label className="signal-field-label" htmlFor={`project-question-${index}`}>项目问题 {index + 1}</label>
                          <textarea
                            id={`project-question-${index}`}
                            required
                            value={question.prompt}
                            onChange={(event) => updateProjectQuestion(index, { prompt: event.target.value })}
                            className="signal-textarea"
                          />
                          <div className="signal-field-grid">
                            <input
                              value={question.knowledge_point_id}
                              onChange={(event) => updateProjectQuestion(index, { knowledge_point_id: event.target.value })}
                              placeholder="考察点"
                              className="signal-textarea"
                              aria-label={`项目问题 ${index + 1} 考察点`}
                            />
                            <input
                              value={question.signals.join("、")}
                              onChange={(event) => updateProjectQuestion(index, { signals: event.target.value.split(/[、,，]/).map((signal) => signal.trim()).filter(Boolean) })}
                              placeholder="回答时可以提到的内容"
                              className="signal-textarea"
                              aria-label={`项目问题 ${index + 1} 回答提示`}
                            />
                          </div>
                        </div>
                      ))}
                    </div>
                    {analysisResult.evidence.length > 0 && (
                      <details className="signal-details">
                        <summary>查看简历中的依据</summary>
                        {analysisResult.evidence.map((item, index) => <p key={index}><strong>{homeCopy.projectFields[item.field]}</strong>：{item.quote}</p>)}
                      </details>
                    )}
                  </div>
                </section>
              )}

              <section className="signal-section" aria-labelledby="project-heading">
                <h2 id="project-heading" className="signal-section-label">{homeCopy.projectSection}</h2>
                <div className="signal-field-grid">
                  {fields.map((field) => (
                    <label key={field.key} className={`signal-field ${field.key === "project_name" ? "signal-field--wide" : ""}`}>
                      <span className="signal-field-label">{homeCopy.projectFields[field.key]}</span>
                      <textarea
                        required={field.key !== "quantified_results"}
                        rows={field.key === "project_name" ? 1 : 3}
                        value={project[field.key]}
                        onChange={(event) => setProject((current) => ({ ...current, [field.key]: event.target.value }))}
                        disabled={analyzing || busy}
                        placeholder={field.hint}
                        className="signal-textarea"
                      />
                    </label>
                  ))}
                </div>
              </section>

              {error && <p className="signal-alert" role="alert">{error}</p>}
              <div className="signal-actions signal-actions--between">
                <p className="signal-note">确认后的项目内容会进入本场面试。</p>
                <button type="submit" aria-label="确认项目，开始面试" disabled={busy || uploading || analyzing} className="signal-button signal-button--primary">
                  {busy ? "正在保存…" : homeCopy.confirm}
                </button>
              </div>
              <p className="signal-footer">回答会先保存，全部答完后再生成本场报告。自动整理时，完整简历文本会发送给硅基流动。</p>
            </form>
          </section>
        </div>
      </div>
    </main>
  );
}
