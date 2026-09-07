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
import { brandCopy, getMissingInformationPrompts, homeCopy } from "@/lib/ui-copy";

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
  { key: "background_goal", hint: "它为什么要做？解决了什么问题？" },
  { key: "tech_stack", hint: "语言、框架、模型、数据库" },
  { key: "responsibilities", hint: "你亲自设计、实现和负责了什么？" },
  { key: "core_solution", hint: "从输入到输出，主要流程是什么？" },
  { key: "engineering_challenges", hint: "哪里最难？为什么？" },
  { key: "failure_improvements", hint: "出过什么问题？你怎么定位和修改？" },
  { key: "quantified_results", hint: "速度、效果、规模等结果，能量化就写出来" },
];

const preparationSteps = ["上传简历", "确认项目", "开始练习"];

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
    if (resumeText.trim() && !window.confirm("上传文件会替换当前简历内容，是否继续？")) return;

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
    if (!window.confirm("完整简历内容将发送给硅基流动，用来整理项目，是否继续？")) return;

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
      const session = await createSession(profile.profile_id, "dialog");
      router.push(`/interview/${session.session_id}`);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "创建面试失败，请稍后重试。");
    } finally {
      setBusy(false);
    }
  }

  const activeStep = analysisResult ? 1 : resumeText.trim() ? 0 : 0;
  const supplementPrompts = analysisResult ? getMissingInformationPrompts(analysisResult.missing_information) : [];

  return (
    <main className="mint-page mint-page--home">
      <div className="mint-shell">
        <header className="mint-header">
          <a className="mint-brand" href="/" aria-label={`${brandCopy.name} 首页`}>
            <span className="mint-brand-mark" aria-hidden="true">✦</span>
            <span className="mint-brand-name">{brandCopy.name}</span>
          </a>
          <nav className="mint-nav" aria-label="页面导航">
            <span className="mint-nav-current">{brandCopy.preparation}</span>
            <span className="mint-nav-note">Agent 应用工程师</span>
            <a className="mint-nav-link" href="/history">面试记录</a>
            <a className="mint-nav-link" href="/profile">能力概况</a>
            <a className="mint-nav-link" href="/skills">知识库</a>
            <a className="mint-nav-link" href="/questions">题库</a>
            <a className="mint-nav-link" href="/console">模型设置</a>
          </nav>
        </header>

        <section className="mint-hero" aria-label="面试准备介绍">
          <div>
            <p className="mint-overline">{homeCopy.eyebrow}</p>
            <h1 className="mint-title">{homeCopy.projectTitle}</h1>
            <p className="mint-lead">{homeCopy.projectDescription}</p>
            <div className="mint-process" aria-label="准备流程">
              {preparationSteps.map((step, index) => (
                <span className={`mint-process-step ${index <= activeStep ? "is-done" : ""}`} key={step}>
                  <span className="mint-process-number">0{index + 1}</span>{step}
                </span>
              ))}
            </div>
          </div>
          <aside className="mint-hero-card" aria-label="本次准备内容">
            <p className="mint-card-kicker">这次准备</p>
            <strong className="mint-hero-card-title">Agent 应用工程师</strong>
            <p className="mint-hero-card-copy">题目会围绕下面确认的项目内容展开，先核对再开始。</p>
            <span className="mint-card-spark" aria-hidden="true">↗</span>
          </aside>
        </section>

        <form onSubmit={handleSubmit}>
          <section className="mint-section" aria-labelledby="resume-heading">
            <div className="mint-section-heading">
              <div className="mint-section-heading-main">
                <h2 id="resume-heading" className="mint-section-title">第一步：上传简历</h2>
              </div>
              <span className="mint-section-aside">PDF / DOCX</span>
            </div>
            <div className="mint-card mint-upload-card">
              <span className="mint-upload-icon" aria-hidden="true">↗</span>
              <div className="mint-upload-main">
                <p className="mint-upload-title">选择简历文件</p>
                <p className="mint-upload-hint">{homeCopy.uploadHint} 扫描件暂不支持。</p>
                {resumeSource && !uploading && (
                  <p className="mint-file-status">
                    {resumeSource.original_filename} · {resumeSource.unit_count}{resumeSource.source_type === "pdf" ? " 页" : " 个文本块"} · {resumeSource.character_count} 字符
                    <button type="button" onClick={switchToManualResume} disabled={analyzing || busy} className="mint-button mint-button--quiet">改为手动编辑</button>
                  </p>
                )}
              </div>
              <label className="mint-button mint-button--outline">
                <span>{uploading ? "正在解析…" : "选择文件"}</span>
                <input type="file" accept=".pdf,.docx,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document" onChange={handleResumeUpload} disabled={uploading || busy || analyzing} className="mint-input-hidden" />
              </label>
            </div>
            {uploading && <p className="mint-note">正在读取文本，请稍候…</p>}
            {resumeSource?.warnings.map((warning) => <p key={warning} className="mint-note">提示：{warning}</p>)}
          </section>

          <section className="mint-section" aria-labelledby="resume-text-heading">
            <div className="mint-section-heading">
              <h2 id="resume-text-heading" className="mint-section-title">第二步：检查文字</h2>
            </div>
            <div className="mint-card mint-edit-card">
              <p className="mint-edit-intro">这里显示从文件中读出的文字，你可以直接修改，也可以重新粘贴。</p>
              <textarea value={resumeText} onChange={(event) => handleResumeTextChange(event.target.value)} disabled={analyzing || uploading || busy} placeholder="上传后这里显示简历文字，可手动修改；直接粘贴仅用于检查，自动整理需上传文件……" className="mint-textarea" aria-label="简历内容" />
            </div>
          </section>

          <section className="mint-section" aria-labelledby="analysis-heading">
            <div className="mint-section-heading">
              <h2 id="analysis-heading" className="mint-section-title">第三步（可选）：让 AI 整理项目</h2>
            </div>
            <div className="mint-card mint-upload-card">
              <div className="mint-upload-main"><p className="mint-upload-title">{homeCopy.analyze}</p><p className="mint-upload-hint">整理后你可以逐项修改，再决定要不要开始练习。</p></div>
              <button type="button" onClick={handleAnalyze} disabled={!resumeId || !resumeText.trim() || analyzing || busy || uploading} className="mint-button mint-button--primary">{analyzing ? "正在整理…" : analysisResult ? homeCopy.analyzeAgain : "开始整理"}</button>
            </div>
            {analyzing && <div className="mint-progress" aria-live="polite"><div className="mint-progress-line" /><span className="mint-progress-label">{analysisStage}</span></div>}
            {!resumeId && <p className="mint-note">上传 PDF 或 DOCX 后可以自动整理；直接粘贴文字暂不支持自动整理，请到下方手动填写项目内容。</p>}
          </section>

          {analysisResult && (
            <section className="mint-section" aria-labelledby="analysis-result-heading">
              <h2 id="analysis-result-heading" className="mint-section-title">AI 整理出的项目</h2>
              <div className="mint-card mint-analysis-card">
                <div className="mint-analysis-summary"><div><p className="mint-analysis-title">{project.project_name || "未命名项目"}</p><p className="mint-note">{analysisResult.selection_reason}</p></div><span className="mint-chip">可以继续修改</span></div>
                {supplementPrompts.length > 0 && (
                  <div className="mint-report-block" aria-label="建议补充的信息">
                    <p className="mint-report-label">补充这些会更完整</p>
                    <div className="mint-question-label">
                      {supplementPrompts.map((prompt) => <span key={prompt} className="mint-chip">{prompt}</span>)}
                    </div>
                  </div>
                )}
                <div className="mint-analysis-list">
                  {projectQuestions.map((question, index) => (
                    <div key={index} className="mint-question-edit">
                      <label className="mint-field-label" htmlFor={`project-question-${index}`}>练习问题 {index + 1}</label>
                      <textarea id={`project-question-${index}`} required value={question.prompt} onChange={(event) => updateProjectQuestion(index, { prompt: event.target.value })} className="mint-textarea" />
                      <div className="mint-question-edit-grid">
                        <input value={question.knowledge_point_id} onChange={(event) => updateProjectQuestion(index, { knowledge_point_id: event.target.value })} placeholder="这题想了解什么" className="mint-input" aria-label={`练习问题 ${index + 1} 考察点`} />
                        <input value={question.signals.join("、")} onChange={(event) => updateProjectQuestion(index, { signals: event.target.value.split(/[、,，]/).map((signal) => signal.trim()).filter(Boolean) })} placeholder="回答时可以提到的内容" className="mint-input" aria-label={`练习问题 ${index + 1} 回答提示`} />
                      </div>
                    </div>
                  ))}
                </div>
                {analysisResult.evidence.length > 0 && <details><summary className="mint-report-label">看看简历里对应的内容</summary>{analysisResult.evidence.map((item, index) => <p key={index} className="mint-note"><strong>{homeCopy.projectFields[item.field]}</strong>：{item.quote}</p>)}</details>}
              </div>
            </section>
          )}

          <section className="mint-section" aria-labelledby="project-heading">
            <div className="mint-section-heading"><h2 id="project-heading" className="mint-section-title">第四步：确认项目，开始面试</h2></div>
            <div className="mint-card mint-edit-card">
              <p className="mint-edit-intro">不确定的地方可以先留空再回来补，面试题会围绕这里的内容展开。</p>
              <div className="mint-field-grid">
                {fields.map((field) => (
                  <label key={field.key} className={`mint-field ${field.key === "project_name" ? "mint-field--wide" : ""}`}>
                    <span className="mint-field-label">{homeCopy.projectFields[field.key]}</span>
                    <textarea required={field.key !== "quantified_results"} rows={field.key === "project_name" ? 1 : 3} value={project[field.key]} onChange={(event) => setProject((current) => ({ ...current, [field.key]: event.target.value }))} disabled={analyzing || busy} placeholder={field.hint} className="mint-textarea" />
                  </label>
                ))}
              </div>
            </div>
          </section>

          {error && <p className="mint-alert" role="alert">{error}</p>}
          <div className="mint-actions"><p className="mint-note">确认后的项目内容会进入这场练习。</p><button type="submit" aria-label="确认内容，开始面试" disabled={busy || uploading || analyzing} className="mint-button mint-button--primary">{busy ? "正在保存…" : homeCopy.confirm}</button></div>
          <p className="mint-footer">回答会先保存，全部答完后再一起生成结果。自动整理时，完整简历内容会发送给硅基流动。</p>
        </form>
      </div>
    </main>
  );
}
