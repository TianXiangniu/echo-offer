"use client";

import { ChangeEvent, FormEvent, useState } from "react";
import { useRouter } from "next/navigation";

import {
  AgentProjectAnalysis,
  analyzeAgentProject,
  createProfile,
  createSession,
  parseResume,
  ProjectInput,
  ProjectQuestionInput,
  ResumeParseResponse,
} from "@/lib/api";

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

const fields: Array<{ key: keyof ProjectInput; label: string; hint: string }> = [
  { key: "project_name", label: "项目名称", hint: "例如：企业知识库问答 Agent" },
  { key: "background_goal", label: "背景与目标", hint: "它解决了什么真实问题？" },
  { key: "tech_stack", label: "技术栈", hint: "语言、框架、模型、数据库" },
  { key: "responsibilities", label: "个人职责", hint: "你亲自设计、实现和负责什么？" },
  { key: "core_solution", label: "核心方案", hint: "链路、关键模块和技术选择" },
  { key: "engineering_challenges", label: "工程难点", hint: "遇到过哪些约束、故障或权衡？" },
  { key: "failure_improvements", label: "故障与改进", hint: "一次失败、定位过程和改进动作" },
  { key: "quantified_results", label: "量化结果", hint: "指标、对照和可复现的结果" },
];

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

  function clearAnalysis() {
    setAnalysisId(undefined);
    setAnalysisResult(undefined);
    setProjectQuestions([]);
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
      setError("请先上传 PDF 或 DOCX 简历，再进行 AI 分析。");
      return;
    }
    if (!window.confirm("完整简历文本将发送给硅基流动用于项目分析，是否继续？")) return;

    setAnalyzing(true);
    setError("");
    try {
      const result = await analyzeAgentProject(resumeId, resumeText);
      setAnalysisId(result.analysis_id);
      setAnalysisResult(result);
      setProject(result.project);
      setProjectQuestions(result.questions);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "AI 分析失败，请稍后重试。");
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

  return (
    <main className="min-h-screen bg-ink px-5 py-8 text-paper sm:px-10 lg:px-16">
      <div className="mx-auto max-w-7xl">
        <header className="flex items-center justify-between border-b border-white/10 pb-6">
          <div className="flex items-center gap-3">
            <div className="grid h-10 w-10 place-items-center rounded-full bg-signal font-display text-xl text-white">E</div>
            <div>
              <p className="font-display text-lg">Agent Echo</p>
              <p className="text-xs tracking-[0.18em] text-white/45">INTERVIEW PREP / ALPHA</p>
            </div>
          </div>
          <p className="hidden text-sm text-white/45 md:block">中文 · Agent 应用工程师 · 1—3 年</p>
        </header>

        <section className="grid gap-12 pb-20 pt-16 lg:grid-cols-[0.8fr_1.2fr] lg:gap-20 lg:pt-24">
          <div>
            <p className="mb-5 text-sm font-semibold uppercase tracking-[0.25em] text-signal">01 / 先把事实说清楚</p>
            <h1 className="max-w-xl font-display text-5xl font-semibold leading-[1.05] tracking-tight sm:text-7xl">让面试从你的真实项目开始。</h1>
            <p className="mt-7 max-w-lg text-lg leading-8 text-white/60">Agent Echo 不用模板化简历猜测你做过什么。先确认项目事实，再用 8 道问题看你如何解释方案、边界与工程结果。</p>
            <div className="mt-10 grid max-w-md grid-cols-3 gap-3 text-center text-xs text-white/50">
              <div className="border-l border-signal/70 pl-3 text-left"><strong className="block text-2xl text-paper">08</strong>道固定问题</div>
              <div className="border-l border-ember/70 pl-3 text-left"><strong className="block text-2xl text-paper">03</strong>道锚题</div>
              <div className="border-l border-white/30 pl-3 text-left"><strong className="block text-2xl text-paper">0—4</strong>级评估</div>
            </div>
          </div>

          <form onSubmit={handleSubmit} className="rounded-[2rem] border border-white/10 bg-white/[0.06] p-6 shadow-2xl shadow-black/20 sm:p-8">
            <div className="mb-8 flex items-start justify-between gap-4">
              <div>
                <p className="text-xs uppercase tracking-[0.2em] text-white/40">Profile / Project</p>
                <h2 className="mt-2 font-display text-2xl">确认你的项目事实</h2>
              </div>
              <span className="rounded-full border border-signal/40 px-3 py-1 text-xs text-signal">本地保存</span>
            </div>

            <div className="mb-5 rounded-2xl border border-signal/20 bg-signal/[0.04] p-4">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div>
                  <p className="text-sm font-medium text-paper">上传简历文件</p>
                  <p className="mt-1 text-xs leading-5 text-white/45">支持 PDF / DOCX，提取后仍可编辑，扫描件暂不支持。</p>
                </div>
                <label className="cursor-pointer rounded-xl border border-signal/40 px-3 py-2 text-xs font-semibold text-signal transition hover:bg-signal/10 focus-within:ring-2 focus-within:ring-signal/60">
                  <span>{uploading ? "正在解析…" : "选择文件"}</span>
                  <input
                    type="file"
                    accept=".pdf,.docx,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                    onChange={handleResumeUpload}
                    disabled={uploading || busy}
                    className="sr-only"
                  />
                </label>
              </div>
              {uploading && <p className="mt-3 text-xs text-signal">正在读取文本，请稍候…</p>}
              {resumeSource && !uploading && (
                <div className="mt-3 flex flex-wrap items-center justify-between gap-2 border-t border-white/10 pt-3 text-xs">
                  <p className="text-white/65">
                    <span className="mr-2 rounded-full bg-signal/15 px-2 py-1 font-semibold text-signal">{resumeSource.source_type.toUpperCase()}</span>
                    {resumeSource.original_filename} · {resumeSource.unit_count}{resumeSource.source_type === "pdf" ? " 页" : " 个文本块"} · {resumeSource.character_count} 字符
                  </p>
                  <button type="button" onClick={switchToManualResume} className="text-white/45 underline decoration-white/20 underline-offset-4 transition hover:text-paper">
                    改为手动编辑
                  </button>
                </div>
              )}
              {resumeSource?.warnings.map((warning) => <p key={warning} className="mt-2 text-xs text-amber-200">{warning}</p>)}
            </div>

            <label className="block">
              <span className="mb-2 block text-sm text-white/70">简历文本</span>
              <textarea required value={resumeText} onChange={(event) => handleResumeTextChange(event.target.value)} placeholder="粘贴你的简历文本。它只作为项目上下文草稿，最终以你确认的项目事实为准。" className="min-h-32 w-full resize-y rounded-2xl border border-white/10 bg-black/20 px-4 py-3 text-sm leading-6 text-paper outline-none transition placeholder:text-white/25 focus:border-signal/70" />
            </label>

            <div className="mt-5 rounded-2xl border border-ember/25 bg-ember/[0.05] p-4">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div>
                  <p className="text-sm font-medium text-paper">让 AI 识别 Agent 项目</p>
                  <p className="mt-1 text-xs leading-5 text-white/45">点击分析后，完整简历文本将发送给硅基流动。</p>
                </div>
                <button
                  type="button"
                  onClick={handleAnalyze}
                  disabled={!resumeId || !resumeText.trim() || analyzing || busy || uploading}
                  className="rounded-xl bg-ember px-3 py-2 text-xs font-semibold text-white transition hover:bg-ember/90 disabled:cursor-not-allowed disabled:opacity-40"
                >
                  {analyzing ? "分析中…" : analysisResult ? "重新分析" : "使用 AI 分析"}
                </button>
              </div>
              {!resumeId && <p className="mt-3 text-xs text-amber-200/75">请先上传 PDF 或 DOCX，解析完成后才能分析。</p>}
            </div>

            {analysisResult && (
              <section className="mt-5 rounded-2xl border border-signal/25 bg-signal/[0.04] p-4">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div>
                    <p className="text-xs uppercase tracking-[0.18em] text-signal">AI Analysis Draft</p>
                    <h3 className="mt-1 text-lg font-semibold text-paper">已识别：{project.project_name || "未命名项目"}</h3>
                  </div>
                  <span className="rounded-full border border-signal/35 px-2.5 py-1 text-xs text-signal">置信度 {Math.round(analysisResult.confidence * 100)}%</span>
                </div>
                <p className="mt-3 text-sm leading-6 text-white/65">{analysisResult.selection_reason}</p>
                {analysisResult.missing_information.length > 0 && (
                  <div className="mt-3 rounded-xl border border-amber-200/20 bg-amber-200/[0.05] p-3 text-xs leading-5 text-amber-100">
                    <span className="font-semibold">待补充：</span>{analysisResult.missing_information.join("；")}
                  </div>
                )}
                <div className="mt-4 space-y-3">
                  <p className="text-xs font-semibold uppercase tracking-[0.16em] text-white/40">个性化项目题</p>
                  {projectQuestions.map((question, index) => (
                    <div key={index} className="rounded-xl border border-white/10 bg-black/15 p-3">
                      <label className="block">
                        <span className="mb-1.5 block text-xs text-white/50">项目题 {index + 1}</span>
                        <textarea
                          required
                          value={question.prompt}
                          onChange={(event) => updateProjectQuestion(index, { prompt: event.target.value })}
                          className="min-h-20 w-full resize-y rounded-lg border border-white/10 bg-black/20 px-3 py-2 text-sm leading-6 text-paper outline-none focus:border-signal/70"
                        />
                      </label>
                      <div className="mt-2 grid gap-2 sm:grid-cols-2">
                        <input
                          value={question.knowledge_point_id}
                          onChange={(event) => updateProjectQuestion(index, { knowledge_point_id: event.target.value })}
                          placeholder="知识点 ID"
                          className="rounded-lg border border-white/10 bg-black/20 px-3 py-2 text-xs text-paper outline-none focus:border-signal/70"
                        />
                        <input
                          value={question.signals.join("、")}
                          onChange={(event) => updateProjectQuestion(index, { signals: event.target.value.split(/[、,，]/).map((signal) => signal.trim()).filter(Boolean) })}
                          placeholder="答题信号，用顿号分隔"
                          className="rounded-lg border border-white/10 bg-black/20 px-3 py-2 text-xs text-paper outline-none focus:border-signal/70"
                        />
                      </div>
                    </div>
                  ))}
                </div>
                {analysisResult.evidence.length > 0 && (
                  <details className="mt-4 text-xs text-white/45">
                    <summary className="cursor-pointer text-white/60">查看模型引用证据</summary>
                    <ul className="mt-2 space-y-1.5 pl-4">
                      {analysisResult.evidence.map((item, index) => <li key={index}><span className="text-signal">{item.field}</span>：{item.quote}</li>)}
                    </ul>
                  </details>
                )}
              </section>
            )}

            <div className="mt-7 grid gap-4 sm:grid-cols-2">
              {fields.map((field) => (
                <label key={field.key} className={field.key === "project_name" ? "sm:col-span-2" : ""}>
                  <span className="mb-2 block text-sm text-white/70">{field.label}</span>
                  <textarea required={field.key !== "quantified_results"} rows={field.key === "project_name" ? 1 : 2} value={project[field.key]} onChange={(event) => setProject((current) => ({ ...current, [field.key]: event.target.value }))} placeholder={field.hint} className="w-full resize-y rounded-xl border border-white/10 bg-black/20 px-3 py-2.5 text-sm leading-6 text-paper outline-none transition placeholder:text-white/25 focus:border-signal/70" />
                </label>
              ))}
            </div>

            {error && <p className="mt-5 rounded-xl border border-red-400/30 bg-red-400/10 px-4 py-3 text-sm text-red-200">{error}</p>}
            <button type="submit" disabled={busy || uploading || analyzing} className="mt-7 flex w-full items-center justify-between rounded-xl bg-paper px-5 py-4 text-left font-semibold text-ink transition hover:bg-white disabled:cursor-wait disabled:opacity-60"><span>{busy ? "正在保存项目并生成问题…" : "确认项目，开始面试"}</span><span className="text-xl">↗</span></button>
            <p className="mt-4 text-center text-xs leading-5 text-white/35">回答会先保存到本地数据库，再生成本题评估。</p>
          </form>
        </section>
      </div>
    </main>
  );
}
