const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

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
  evidence: Array<{ field: keyof ProjectInput; quote: string }>;
  questions: ProjectQuestionInput[];
  missing_information: MissingInformationItem[];
  facts: ProjectFact[];
  question_chain: ProjectQuestionDetail[];
};

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

export type SessionView = {
  session_id: string;
  status: string;
  current_question: Question | null;
  questions: Array<Question & { answered: boolean }>;
  progress: { completed: number; total: number };
};

export type AnswerInput = {
  question_id: string;
  client_submission_id: string;
  status: "submitted" | "explicit_unknown" | "skipped";
  answer_text: string;
};

export type Observation = {
  id: string;
  level: number;
  evidence_start: number;
  evidence_end: number;
  quoted_text: string;
  confidence: number;
  gaps: string[];
  validity: string;
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
  api_key_configured: boolean;
  updated_at: string | null;
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
};

export type ModelConnectionTestResponse = {
  ok: boolean;
  message: string;
  model: string;
  latency_ms: number;
  error_code?: string | null;
};

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
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

  const body = (await response.json().catch(() => ({}))) as { detail?: string };
  if (!response.ok) {
    throw new ApiError(response.status, body.detail ?? `请求失败（${response.status}）`);
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
    { method: "POST", body: JSON.stringify({ resume_text: resumeText }) },
  );
}

export async function analyzeAgentProjectStream(
  resumeId: string,
  resumeText: string,
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
        body: JSON.stringify({ resume_text: resumeText }),
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

export function createProfile(input: {
  resume_text: string;
  resume_id?: string;
  analysis_id?: string;
  project: ProjectInput;
  project_questions?: ProjectQuestionInput[];
}) {
  return request<ProfileResponse>("/api/profile", { method: "POST", body: JSON.stringify(input) });
}

export function createSession(profileId: string) {
  return request<SessionResponse>("/api/sessions", { method: "POST", body: JSON.stringify({ profile_id: profileId }) });
}

export function getSession(sessionId: string) {
  return request<SessionView>(`/api/sessions/${sessionId}`);
}

export function submitAnswer(sessionId: string, input: AnswerInput) {
  return request<{
    answer: Record<string, string>;
    observation: Observation | null;
    assessment: AssessmentResult | null;
  }>(
    `/api/sessions/${sessionId}/answers`,
    { method: "POST", body: JSON.stringify(input) },
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
  }>;
};

export function getReport(sessionId: string) {
  return request<Report>(`/api/sessions/${sessionId}/report`);
}

export function getModelSettings() {
  return request<ModelSettingsResponse>("/api/settings/model");
}

export function updateModelSettings(input: ModelSettingsUpdate) {
  const body: Record<string, string | number | boolean> = {
    base_url: input.base_url,
    model: input.model,
    assessment_model: input.assessment_model,
    clear_api_key: input.clear_api_key,
    temperature: input.temperature,
    max_tokens: input.max_tokens,
    timeout_seconds: input.timeout_seconds,
    assessment_batch_size: input.assessment_batch_size,
  };
  if (input.api_key?.trim()) body.api_key = input.api_key.trim();
  return request<ModelSettingsResponse>("/api/settings/model", {
    method: "PUT",
    body: JSON.stringify(body),
  });
}

export function testModelConnection() {
  return request<ModelConnectionTestResponse>("/api/settings/model/test", {
    method: "POST",
    body: JSON.stringify({}),
  });
}
