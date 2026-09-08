"use client";

import type { ChangeEvent, FormEvent } from "react";
import { useState } from "react";
import { useRouter } from "next/navigation";

import {
  AgentProjectAnalysis,
  analyzeProjectCandidates,
  analyzeAgentProjectStream,
  createProfile,
  createSession,
  parseResume,
  ProjectInput,
  ProjectCandidate,
  ProjectQuestionInput,
  ResumeParseResponse,
} from "@/lib/api";
import { canStartInterview, getHomeStep } from "@/lib/home-flow";
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

const preparationSteps = ["上传简历", "AI 整理项目", "确认并开始面试"];

export default function HomePage() {
  const router = useRouter();
  const [resumeText, setResumeText] = useState("");
  const [resumeId, setResumeId] = useState<string>();
  const [resumeSource, setResumeSource] = useState<ResumeParseResponse>();
  const [project, setProject] = useState<ProjectInput>(emptyProject);
  const [analysisId, setAnalysisId] = useState<string>();
  const [analysisResult, setAnalysisResult] = useState<AgentProjectAnalysis>();
  const [candidates, setCandidates] = useState<ProjectCandidate[]>([]);
  const [selectedCandidate, setSelectedCandidate] = useState<ProjectCandidate>();
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
    setCandidates([]);
    setSelectedCandidate(undefined);
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

  async function handleAnalyze() {
    if (!resumeId || !resumeText.trim()) {
      setError("请先上传 PDF 或 DOCX 简历，再进行整理。");
      return;
    }
    if (!window.confirm("完整简历内容将发送给硅基流动，用来整理项目，是否继续？")) return;

    setAnalyzing(true);
    setError("");
    try {
      if (!candidates.length) {
        setAnalysisStage("正在识别简历项目…");
        const result = await analyzeProjectCandidates(resumeId, resumeText);
        setCandidates(result.candidates);
        setAnalysisStage("请选择本场面试项目");
        return;
      }
      if (!selectedCandidate) {
        setError("请选择一个项目，再生成面试内容。");
        return;
      }
      setAnalysisStage("正在整理选中项目…");
      const result = await analyzeAgentProjectStream(resumeId, resumeText, selectedCandidate.project_name, (event) => {
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
    if (!canStartInterview({ hasResume: Boolean(resumeId && resumeText.trim()), hasAnalysis: Boolean(analysisResult) })) {
      setError("请先完成 AI 项目整理，再开始面试。");
      return;
    }
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
      const session = await createSession(profile.profile_id, "graph");
      router.push(`/interview/${session.session_id}`);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "创建面试失败，请稍后重试。");
    } finally {
      setBusy(false);
    }
  }

  const step = getHomeStep({ hasResume: Boolean(resumeId && resumeText.trim()), hasAnalysis: Boolean(analysisResult) });
  const activeStep = step - 1;
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
            {resumeSource && (
              <details className="mint-card mint-edit-card">
                <summary className="mint-report-label">查看或修改解析出的简历文字</summary>
                <textarea value={resumeText} onChange={(event) => { setResumeText(event.target.value); if (analysisResult) clearAnalysis(); }} disabled={analyzing || uploading || busy} className="mint-textarea" aria-label="简历内容" />
              </details>
            )}
          </section>

          {step === 2 && <section className="mint-section" aria-labelledby="analysis-heading">
            <div className="mint-section-heading">
              <h2 id="analysis-heading" className="mint-section-title">第二步：让 AI 整理项目</h2>
            </div>
            <div className="mint-card mint-upload-card">
              <div className="mint-upload-main"><p className="mint-upload-title">{candidates.length ? "选择本场面试项目" : homeCopy.analyze}</p><p className="mint-upload-hint">{candidates.length ? "选中后，AI 只为这个项目生成面试内容。" : "AI 会先识别简历中的候选项目，再由你选择一个。"}</p></div>
              <button type="button" onClick={handleAnalyze} disabled={!resumeId || !resumeText.trim() || analyzing || busy || uploading || (candidates.length > 0 && !selectedCandidate)} className="mint-button mint-button--primary">{analyzing ? "正在整理…" : candidates.length ? "生成面试内容" : "识别项目"}</button>
            </div>
            {analyzing && <div className="mint-progress" aria-live="polite"><div className="mint-progress-line" /><span className="mint-progress-label">{analysisStage}</span></div>}
            {candidates.length > 0 && <div className="mint-analysis-list">
              {candidates.map((candidate) => <button type="button" key={candidate.project_name} onClick={() => setSelectedCandidate(candidate)} className={`mint-card mint-analysis-card ${selectedCandidate?.project_name === candidate.project_name ? "is-selected" : ""}`}>
                <p className="mint-analysis-title">{candidate.project_name}</p><p className="mint-note">{candidate.summary}</p><p className="mint-note">{candidate.tech_stack}</p><p className="mint-note">{candidate.selection_reason}</p>
              </button>)}
            </div>}
          </section>}

          {analysisResult && (
            <section className="mint-section" aria-labelledby="project-heading">
              <div className="mint-section-heading"><h2 id="project-heading" className="mint-section-title">第三步：确认项目，开始面试</h2></div>
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
                {analysisResult.evidence.length > 0 && <details><summary className="mint-report-label">看看简历里对应的内容</summary>{analysisResult.evidence.map((item, index) => <p key={index} className="mint-note"><strong>{homeCopy.projectFields[item.field as keyof typeof homeCopy.projectFields] || item.field}</strong>：{item.quote}</p>)}</details>}
              </div>
              <div className="mint-card mint-edit-card">
                <p className="mint-edit-intro">确认这份 AI 整理结果。这里的内容会决定本场面试的追问方向。</p>
                <div className="mint-field-grid">
                  {fields.map((field) => (
                    <label key={field.key} className={`mint-field ${field.key === "project_name" ? "mint-field--wide" : ""}`}>
                      <span className="mint-field-label">{homeCopy.projectFields[field.key]}</span>
                      <textarea required={field.key !== "quantified_results"} rows={field.key === "project_name" ? 1 : 3} value={project[field.key]} onChange={(event) => setProject((current) => ({ ...current, [field.key]: event.target.value }))} disabled={busy} placeholder={field.hint} className="mint-textarea" />
                    </label>
                  ))}
                </div>
              </div>
              <div className="mint-actions"><p className="mint-note">确认后的项目内容会进入这场练习。</p><button type="submit" aria-label="确认内容，开始面试" disabled={busy} className="mint-button mint-button--primary">{busy ? "正在保存…" : "确认项目并开始面试"}</button></div>
            </section>
          )}

          {error && <p className="mint-alert" role="alert">{error}</p>}
          <p className="mint-footer">回答会先保存，全部答完后再一起生成结果。自动整理时，完整简历内容会发送给硅基流动。</p>
        </form>
      </div>
    </main>
  );
}
