const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
export const API_BASE_URL = API_BASE;

export type ProjectInput = {
  project_name: string;
  background_goal: string;
  tech_stack: string;
  responsibilities: string;
  core_solution: string;
  engineering_challenges: string;
  failure_improvements: string;
  quantified_results: string;
};

export type ProjectAnalysisDetails = {
  context?: Record<string, unknown>;
  ownership?: Record<string, unknown>;
  architecture?: Record<string, unknown>;
  agent_details?: Record<string, unknown>;
  tradeoffs?: Record<string, unknown>;
  engineering?: Record<string, unknown>;
  evaluation?: Record<string, unknown>;
  evolution?: Record<string, unknown>;
};

export type ProjectFactStatus =
  | "extracted"
  | "confirmed"
  | "inferred"
  | "missing"
  | "conflicting"
  | "rejected";

export type ProjectFactEvidenceStatus = "valid" | "invalid";

export type ProjectFactEvidence = {
  quote: string;
  status: ProjectFactEvidenceStatus;
  invalid_reason?: string | null;
  start_offset?: number | null;
  end_offset?: number | null;
  text_hash?: string | null;
};

export type ProjectFact = {
  fact_id: string;
  field: string;
  value: string;
  status: ProjectFactStatus;
  source_type: string;
  evidence: ProjectFactEvidence[];
  confidence: number;
  user_confirmed: boolean;
};

export type ProjectQuestionGroup = "project" | "fixed";

export type ProjectQuestionDetail = {
  order: number;
  question_group: ProjectQuestionGroup;
  chain_id: string;
  prompt: string;
  intent: string;
  depends_on: number | null;
  source_fields: string[];
  source_fact_ids: string[];
  expected_answer_points: string[];
  followup_if_incomplete: string;
  followup_if_conflicting: string;
  difficulty: "easy" | "medium" | "hard";
};

export type ProfileResponse = {
  profile_id: string;
  user_id: string;
  project_version: number;
  resume_text_hash: string;
  direction: string;
  level: string;
  language: string;
};

export type ProjectQuestionInput = {
  prompt: string;
  knowledge_point_id: string;
  signals: string[];
};

export type MissingInformationKey =
  | keyof ProjectInput
  | "context.stage"
  | "context.scale"
  | "context.users"
  | "context.timeline"
  | "ownership.owned_modules"
  | "ownership.collaborators"
  | "ownership.scope"
  | "architecture.pipeline"
  | "architecture.tools"
  | "architecture.retrieval"
  | "agent_details.loop"
  | "agent_details.tools"
  | "tradeoffs.chosen_approach"
  | "tradeoffs.rejected_options"
  | "engineering.latency_diagnosis"
  | "engineering.output_safety"
  | "evaluation.metrics"
  | "evaluation.baseline"
  | "evolution.iterations";

export type MissingInformationItem = MissingInformationKey | string;

export type AgentProjectAnalysis = {
  analysis_id: string;
  resume_id: string;
  resume_text_hash: string;
  status: "draft";
  project: ProjectInput & ProjectAnalysisDetails;
  selection_reason: string;
  confidence: number;
  evidence: Array<{ field: string; quote: string }>;
  questions: ProjectQuestionInput[];
  missing_information: MissingInformationItem[];
  facts: ProjectFact[];
  question_chain: ProjectQuestionDetail[];
};

export type ProjectCandidate = {
  project_name: string;
  summary: string;
  tech_stack: string;
  responsibilities: string;
  selection_reason: string;
  confidence: number;
  evidence: Array<{ field: keyof ProjectInput; quote: string }>;
};

export type ProjectCandidatesResponse = { candidates: ProjectCandidate[] };

export type AgentAnalysisStreamEvent =
  | { event: "stage"; data: { stage: "received" | "analyzing" | "validating" | "completed"; message: string } }
  | { event: "heartbeat"; data: { stage: "analyzing" } }
  | { event: "result"; data: AgentProjectAnalysis }
  | { event: "done"; data: { status: "completed" } }
  | { event: "error"; data: { code: string; message: string } };

export type Question = {
  id: string;
  order: number;
  category: "project" | "agent" | "reliability";
  is_anchor: boolean;
  prompt: string;
  knowledge_point_id: string;
  rubric_version: string;
};

export type SessionResponse = {
  session_id: string;
  status: string;
  questions: Question[];
};

export type FollowupView = {
  id: string;
  question_id: string;
  question_text: string;
  decision_reason: string;
  status: "pending" | "answered" | "waived" | string;
  answer_text: string | null;
};

export type PracticeFeedbackView = {
  content: string;
  focus_hints: string[];
};

export type DialogMessage = {
  role: "interviewer" | "candidate" | "coach";
  kind: string;
  content: string;
  tag?: string | null;
  question_id?: string;
};

export type SessionView = {
  session_id: string;
  status: string;
  mode: string;
  stage: string;
  current_question: (Question & {
    answered?: boolean;
    followup?: FollowupView | null;
    feedback?: PracticeFeedbackView | null;
  }) | null;
  questions: Array<
    Question & {
      answered: boolean;
      followup?: FollowupView | null;
      feedback?: PracticeFeedbackView | null;
    }
  >;
  progress: { completed: number; total: number };
  timeline: DialogMessage[];
};

export type GraphPlanNode = {
  id: string;
  kind: string;
  label: string;
  status: "not_started" | "active" | "covered" | "needs_confirmation" | string;
};

export type GraphSessionResponse = {
  session_id: string;
  status: string;
  mode: "graph";
  stage: string;
  current_question: (Question & { answered?: boolean }) | null;
  questions: Question[];
  nodes: GraphPlanNode[];
  progress: { completed: number; total: number };
  timeline: DialogMessage[];
  assessment?: AssessmentBatchResponse;
};

export type InterviewHistoryItem = {
  session_id: string;
  status: string;
  profile_id: string | null;
  project_name: string | null;
  direction: string | null;
  target_title: string | null;
  completed: number;
  total: number;
  score_100: number | null;
  report_status: string | null;
  analysis_status: string | null;
  strength_count: number | null;
  gap_count: number | null;
  created_at: string;
  updated_at: string;
};

export type ProfileSkill = {
  skill_id: string;
  skill_name: string;
  category: string;
  level: number;
  confidence: number;
  sample_count: number;
  trend: string;
  target_level: number | null;
  last_session_id: string | null;
  recent_levels: number[];
  studied: boolean;
  freshness: "fresh" | "cooling" | "stale" | "no_data";
  days_since: number | null;
  recent_answers: Array<{ prompt: string; level: number; commentary: string; session_id: string }>;
};

export type RecommendationStatus = "recommended" | "in_progress" | "completed" | "dismissed";

export type LearningRecommendation = {
  id: string;
  skill_id: string;
  skill_name: string;
  priority: string;
  reason: string;
  actions: string[];
  success_criteria: string[];
  status: RecommendationStatus;
  recommended_review_at: string | null;
  practice_completed_at?: string | null;
  verification_ready?: boolean;
  source_session_id: string | null;
  source_question_id: string | null;
  source_question: string | null;
  source_answer_excerpt: string | null;
  source_level: number | null;
  level: number | null;
  studied: boolean;
  is_unknown: boolean;
  last_assessed_at: string | null;
};

export type ProfileSummary = {
  profile_id: string;
  direction: string;
  level: string;
  target_title: string;
  summary: string;
  last_session_id: string | null;
  skills: ProfileSkill[];
  recommendations: LearningRecommendation[];
  recent_changes: Array<{ skill_id: string; skill_name: string; delta: number }>;
  readiness: number | null;
  avg_target: number | null;
  question_angles: Array<{ tag: string; count: number }>;
  practice_effectiveness: { pairs: number; effective: number };
  verifiable_count: number;
  target_date: string | null;
  today_plan: Array<{ type: string; skill_id: string | null; skill_name: string; reason: string; recommendation_id?: string }>;
  updated_at: string;
};

export type ProfileSnapshot = {
  id: string;
  profile_id: string;
  source_session_id: string;
  version: number;
  profile: Record<string, unknown>;
  created_at: string;
};

export type AnswerInput = {
  question_id: string;
  client_submission_id: string;
  status: "submitted" | "explicit_unknown" | "skipped";
  answer_text: string;
};

export type RubricObservation = {
  rubric_id: string;
  level: number;
  evidence_start: number;
  evidence_end: number;
  quoted_text: string;
  confidence: number;
  validity: "valid" | "invalid" | string;
  invalid_reason?: string | null;
};

export type AssessmentResult = {
  status: "pending" | "valid" | "invalid" | "rejected" | string;
  evaluator: string;
  level?: number | null;
  confidence?: number | null;
  error_code?: string | null;
  error_reason?: string | null;
  rubric_items: RubricObservation[];
};

export type AssessmentBatchItem = {
  answer_id: string;
  question_id: string;
  assessment: AssessmentResult;
};

export type AssessmentBatchResponse = {
  status: "pending" | "valid" | "invalid" | "rejected" | string;
  batch_id: string | null;
  job_id?: string | null;
  job_status?: string | null;
  job_error_code?: string | null;
  job_error_message?: string | null;
  evaluated_count: number;
  total_count: number;
  assessments: AssessmentBatchItem[];
};

export type ModelSettingsResponse = {
  base_url: string;
  model: string;
  assessment_model: string;
  temperature: number;
  max_tokens: number;
  timeout_seconds: number;
  assessment_batch_size: number;
  followup_enabled: boolean;
  practice_feedback_enabled: boolean;
  persona: string;
  pricing: ModelPrice[];
  api_key_configured: boolean;
  updated_at: string | null;
};

export type ModelPrice = {
  model_name: string;
  input_price_per_million_cny: string;
  output_price_per_million_cny: string;
};

export type ModelSettingsUpdate = {
  base_url: string;
  model: string;
  assessment_model: string;
  api_key?: string;
  clear_api_key: boolean;
  temperature: number;
  max_tokens: number;
  timeout_seconds: number;
  assessment_batch_size: number;
  followup_enabled: boolean;
  practice_feedback_enabled: boolean;
  persona: "gentle" | "standard" | "pressure";
  pricing: ModelPrice[];
};

export type ModelConnectionTestResponse = {
  ok: boolean;
  message: string;
  model: string;
  latency_ms: number;
  error_code?: string | null;
};

export type ObservabilitySummary = {
  call_count: number;
  known_cost_cny: string;
  unpriced_call_count: number;
  total_tokens: number;
  success_rate: number | null;
  average_latency_ms: number | null;
};

export class ApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.status = status;
    this.name = "ApiError";
  }
}

type ParsedSseBlock = { event: string; data: unknown };

export function parseSseBlock(block: string): ParsedSseBlock | null {
  let event = "message";
  const dataLines: string[] = [];

  for (const line of block.split(/\r?\n/)) {
    if (!line || line.startsWith(":")) continue;
    if (line.startsWith("event:")) {
      event = line.slice("event:".length).trim();
    } else if (line.startsWith("data:")) {
      dataLines.push(line.slice("data:".length).trimStart());
    }
  }

  if (!dataLines.length) return null;
  return { event, data: JSON.parse(dataLines.join("\n")) };
}

function formatErrorDetail(detail: unknown, status: number): string {
  if (typeof detail === "string" && detail.trim()) return detail;
  if (Array.isArray(detail)) {
    const first = detail[0] as { msg?: string; loc?: unknown[] } | undefined;
    if (first?.msg) {
      const where = Array.isArray(first.loc) ? first.loc.slice(1).join(".") : "";
      return where ? `${where}: ${first.msg}` : first.msg;
    }
  }
  return `请求失败（${status}）`;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    const headers = new Headers(init?.headers);
    if (typeof init?.body === "string") {
      headers.set("Content-Type", "application/json");
    }
    response = await fetch(`${API_BASE}${path}`, {
      ...init,
      headers,
    });
  } catch {
    throw new ApiError(0, "暂时无法连接面试服务，请确认后端运行在 http://localhost:8010。");
  }

  const body = (await response.json().catch(() => ({}))) as { detail?: unknown };
  if (!response.ok) {
    throw new ApiError(response.status, formatErrorDetail(body.detail, response.status));
  }
  return body as T;
}

export type ResumeParseResponse = {
  resume_id: string;
  source_type: "pdf" | "docx";
  original_filename: string;
  unit_count: number;
  character_count: number;
  extracted_text: string;
  warnings: string[];
};

export function parseResume(file: File) {
  const body = new FormData();
  body.append("file", file);
  return request<ResumeParseResponse>("/api/resumes/parse", {
    method: "POST",
    body,
  });
}

export function analyzeAgentProject(resumeId: string, resumeText: string) {
  return request<AgentProjectAnalysis>(
    "/api/resumes/" + resumeId + "/agent-project-analysis",
    { method: "POST", body: JSON.stringify({ resume_text: resumeText, selected_project_name: "" }) },
  );
}

export async function analyzeAgentProjectStream(
  resumeId: string,
  resumeText: string,
  selectedProjectName: string,
  onEvent: (event: AgentAnalysisStreamEvent) => void,
): Promise<AgentProjectAnalysis> {
  let response: Response;
  try {
    response = await fetch(
      API_BASE + "/api/resumes/" + resumeId + "/agent-project-analysis/stream",
      {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Accept: "text/event-stream",
        },
        body: JSON.stringify({ resume_text: resumeText, selected_project_name: selectedProjectName }),
      },
    );
  } catch {
    throw new ApiError(0, "暂时无法连接面试服务，请确认后端运行在 http://localhost:8010。");
  }

  if (!response.ok) {
    const body = (await response.json().catch(() => ({}))) as { detail?: string };
    throw new ApiError(response.status, body.detail ?? `请求失败（${response.status}）`);
  }
  if (!response.body) {
    throw new ApiError(0, "浏览器不支持流式响应，请刷新后重试。");
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let result: AgentProjectAnalysis | undefined;
  let receivedDone = false;

  const consumeBlock = (block: string) => {
    const parsed = parseSseBlock(block);
    if (!parsed) return;

    if (parsed.event === "error") {
      const errorData = parsed.data as { code?: string; message?: string };
      throw new ApiError(502, errorData.message ?? "AI 分析失败，请稍后重试。");
    }
    if (parsed.event === "result") {
      result = parsed.data as AgentProjectAnalysis;
    } else if (parsed.event === "done") {
      receivedDone = true;
    }
    onEvent(parsed as AgentAnalysisStreamEvent);
  };

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (value) buffer += decoder.decode(value, { stream: !done });
      const blocks = buffer.split(/\r?\n\r?\n/);
      buffer = blocks.pop() ?? "";
      for (const block of blocks) consumeBlock(block);
      if (done) break;
    }
    buffer += decoder.decode();
    if (buffer.trim()) consumeBlock(buffer);
  } finally {
    reader.releaseLock();
  }

  if (!result || !receivedDone) {
    throw new ApiError(0, "分析连接中断，请重试");
  }
  return result;
}

export function analyzeProjectCandidates(resumeId: string, resumeText: string) {
  return request<ProjectCandidatesResponse>(`/api/resumes/${resumeId}/agent-project-candidates`, {
    method: "POST", body: JSON.stringify({ resume_text: resumeText }),
  });
}

export function createProfile(input: {
  resume_text: string;
  resume_id?: string;
  analysis_id?: string;
  project: ProjectInput;
  project_questions?: ProjectQuestionInput[];
}) {
  return request<ProfileResponse>("/api/profile", { method: "POST", body: JSON.stringify(input) });
}

export function createSession(profileId: string, mode: "classic" | "dialog" | "graph" = "dialog") {
  return request<SessionResponse>("/api/sessions", {
    method: "POST",
    body: JSON.stringify({ profile_id: profileId, mode }),
  });
}

export function startGraphSession(sessionId: string) {
  return request<GraphSessionResponse>(`/api/sessions/${sessionId}/graph/start`, { method: "POST" });
}

export function resumeGraphSession(
  sessionId: string,
  input: { answer_text: string; client_submission_id: string },
) {
  return request<GraphSessionResponse>(`/api/sessions/${sessionId}/graph/resume`, {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export function getGraphSessionState(sessionId: string) {
  return request<GraphSessionResponse>(`/api/sessions/${sessionId}/graph/state`);
}

export function getSession(sessionId: string) {
  return request<SessionView>(`/api/sessions/${sessionId}`);
}

export function submitAnswer(sessionId: string, input: AnswerInput) {
  return request<{
    answer: Record<string, string>;
    assessment: AssessmentResult | null;
  }>(
    `/api/sessions/${sessionId}/answers`,
    { method: "POST", body: JSON.stringify(input) },
  );
}

export function decideFollowup(sessionId: string, questionId: string) {
  return request<{ followup: FollowupView | null }>(
    `/api/sessions/${sessionId}/questions/${questionId}/followup/decide`,
    { method: "POST", body: JSON.stringify({}) },
  );
}

export function submitFollowupAnswer(
  sessionId: string,
  questionId: string,
  input: { client_submission_id: string; answer_text: string },
) {
  return request<{ followup: FollowupView }>(
    `/api/sessions/${sessionId}/questions/${questionId}/followup/answer`,
    { method: "POST", body: JSON.stringify(input) },
  );
}

export function fetchQuestionFeedback(sessionId: string, questionId: string) {
  return request<{ feedback: { question_id: string; content: string; focus_hints: string[] } | null }>(
    `/api/sessions/${sessionId}/questions/${questionId}/feedback`,
    { method: "POST", body: JSON.stringify({}) },
  );
}

export function assessSession(sessionId: string) {
  return request<AssessmentBatchResponse>(
    "/api/sessions/" + sessionId + "/assessment",
    { method: "POST", body: JSON.stringify({}) },
  );
}

export type Report = {
  session_id: string;
  completion: { completed: number; total: number };
  score_100: number | null;
  coverage: number;
  anchor_coverage: { answered: number; total: number };
  strengths: Array<{ knowledge_point_id: string; level: number; confidence: number; evidence: string }>;
  gaps: Array<{ knowledge_point_id: string; level: number; confidence: number; evidence: string }>;
  level_distribution: Record<string, number>;
  valid_evidence_count: number;
  confidence: number;
  evaluator: string;
  assessment_status_counts?: Record<string, number>;
  rubric_items?: Array<{
    question_id: string;
    knowledge_point_id: string;
    rubric_id: string;
    level: number;
    confidence: number;
    evidence: string;
    commentary?: string;
    followup_question?: string;
    followup_answer?: string;
  }>;
  transcript?: Array<{
    order: number;
    category: string;
    prompt: string;
    knowledge_point_id: string;
    status: string;
    answer_text: string;
    followups: Array<{ question_text: string; answer_text: string }>;
    level: number | null;
    commentary: string;
  }>;
};

export function getReport(sessionId: string) {
  return request<Report>(`/api/sessions/${sessionId}/report`);
}

export function getInterviewHistory() {
  return request<InterviewHistoryItem[]>("/api/interviews/history");
}

export function deleteInterview(sessionId: string) {
  return request<void>(`/api/sessions/${sessionId}`, { method: "DELETE" });
}

export function getProfileSummary(profileId: string) {
  return request<ProfileSummary>(`/api/profiles/${profileId}/summary`);
}

export function getProfileHistory(profileId: string) {
  return request<ProfileSnapshot[]>(`/api/profiles/${profileId}/history`);
}

export function updateRecommendationStatus(
  recommendationId: string,
  status: RecommendationStatus,
) {
  return request<LearningRecommendation>(`/api/recommendations/${recommendationId}`, {
    method: "PATCH",
    body: JSON.stringify({ status }),
  });
}

export function startOpenDrill(skillId?: string) {
  return request<{ session_id: string; session_kind: string }>(
    "/api/practice/drill",
    { method: "POST", body: JSON.stringify({ skill_id: skillId || null }) },
  );
}

export function startDrill(recommendationId: string) {
  return request<{ session_id: string; session_kind: string }>(
    `/api/recommendations/${recommendationId}/drill`,
    { method: "POST", body: JSON.stringify({}) },
  );
}

export function startVerification(recommendationId: string) {
  return request<{ session_id: string; session_kind: string }>(
    `/api/recommendations/${recommendationId}/verify`,
    { method: "POST", body: JSON.stringify({}) },
  );
}

export function getModelSettings() {
  return request<ModelSettingsResponse>("/api/settings/model");
}

export function updateModelSettings(input: ModelSettingsUpdate) {
  const body = {
    ...input,
    api_key: input.api_key?.trim() || undefined,
  };
  return request<ModelSettingsResponse>("/api/settings/model", {
    method: "PUT",
    body: JSON.stringify(body),
  });
}

export function getObservabilitySummary() {
  return request<ObservabilitySummary>("/api/observability/summary");
}

export function testModelConnection() {
  return request<ModelConnectionTestResponse>("/api/settings/model/test", {
    method: "POST",
    body: JSON.stringify({}),
  });
}

export type SkillSummary = {
  skill_id: string;
  name: string;
  category: string;
  level: number | null;
  sample_count: number;
  studied: boolean;
  has_deep_dive: boolean;
};

export type SkillDetail = {
  skill_id: string;
  name: string;
  category: string;
  sections: {
    definition?: string;
    why?: string;
    key_points?: string[];
    pitfalls?: string[];
    examples?: Array<{ level: number; answer: string }>;
    deep_dive?: { mechanism: string; personal_focus: string; pitfalls_extra: string[] };
  };
  has_deep_dive: boolean;
  mastery: { level: number | null; sample_count: number; trend: string; confidence?: number; last_assessed_at?: string | null; session_ordinal?: number | null };
  studied: boolean;
  related_questions: Array<{ prompt: string; template_id: string }>;
  community_questions: Array<{ id: string; text: string; dup_count: number }>;
  recent_answer: { answer_text: string; commentary: string | null } | null;
};

export function getSkills() {
  return request<{ skills: SkillSummary[] }>("/api/skills");
}

export function getSkillDetail(skillId: string) {
  return request<SkillDetail>(`/api/skills/${encodeURIComponent(skillId)}`);
}

export function markSkillStudied(skillId: string) {
  return request<{ skill_id: string; studied: boolean }>(
    `/api/skills/${encodeURIComponent(skillId)}/study`,
    { method: "POST", body: JSON.stringify({}) },
  );
}

export function generateSkillWiki(skillId: string) {
  return request<{ skill_id: string; deep_dive: { mechanism: string; personal_focus: string; pitfalls_extra: string[] } }>(
    `/api/skills/${encodeURIComponent(skillId)}/wiki/generate`,
    { method: "POST", body: JSON.stringify({}) },
  );
}

export function submitDialogAnswer(sessionId: string, text: string) {
  return request<{ stage: string }>(
    `/api/sessions/${sessionId}/dialog/answer`,
    { method: "POST", body: JSON.stringify({ text }) },
  );
}

export function finishDialog(sessionId: string) {
  return request<{ stage: string }>(
    `/api/sessions/${sessionId}/dialog/finish`,
    { method: "POST", body: JSON.stringify({}) },
  );
}

export function skipWrapUp(sessionId: string) {
  return request<{ stage: string }>(
    `/api/sessions/${sessionId}/wrapup/skip`,
    { method: "POST", body: JSON.stringify({}) },
  );
}

export function setTargetDate(profileId: string, date: string | null) {
  return request<{ target_date: string | null }>(
    `/api/profiles/${encodeURIComponent(profileId)}/target-date`,
    { method: "PUT", body: JSON.stringify({ date }) },
  );
}

export interface CommunityQuestion {
  id: string;
  text: string;
  phase: string;
  knowledge_point: string;
  knowledge_point_label: string;
  linked_skill_id: string | null;
  note_url: string;
  dup_count: number;
}

export interface CommunityQuestionFacet {
  value: string;
  count: number;
}

export interface CommunityQuestionList {
  total: number;
  questions: CommunityQuestion[];
  phases: CommunityQuestionFacet[];
  knowledge_points: CommunityQuestionFacet[];
}

export function getCommunityQuestions(params?: {
  phase?: string;
  knowledgePoint?: string;
  limit?: number;
  offset?: number;
}) {
  const search = new URLSearchParams();
  if (params?.phase) search.set("phase", params.phase);
  if (params?.knowledgePoint) search.set("knowledge_point", params.knowledgePoint);
  if (params?.limit != null) search.set("limit", String(params.limit));
  if (params?.offset != null) search.set("offset", String(params.offset));
  const query = search.toString();
  return request<CommunityQuestionList>(`/api/community-questions${query ? `?${query}` : ""}`);
}

export function createCommunityQuestion(payload: {
  text: string;
  phase: string;
  knowledgePoint: string;
}) {
  return request<CommunityQuestion>("/api/community-questions", {
    method: "POST",
    body: JSON.stringify({
      text: payload.text,
      phase: payload.phase,
      knowledge_point: payload.knowledgePoint,
    }),
  });
}

export function deleteCommunityQuestion(id: string) {
  return request<{ deleted: string }>(
    `/api/community-questions/${encodeURIComponent(id)}`,
    { method: "DELETE" },
  );
}
