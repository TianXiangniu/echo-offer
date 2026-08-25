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

export type ProfileResponse = {
  profile_id: string;
  user_id: string;
  project_version: number;
  resume_text_hash: string;
  direction: string;
  level: string;
  language: string;
};

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

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
    this.name = "ApiError";
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, {
      ...init,
      headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
    });
  } catch {
    throw new ApiError(0, "暂时无法连接面试服务，请确认后端运行在 http://localhost:8000。");
  }

  const body = (await response.json().catch(() => ({}))) as { detail?: string };
  if (!response.ok) {
    throw new ApiError(response.status, body.detail ?? `请求失败（${response.status}）`);
  }
  return body as T;
}

export function createProfile(input: { resume_text: string; project: ProjectInput }) {
  return request<ProfileResponse>("/api/profile", { method: "POST", body: JSON.stringify(input) });
}

export function createSession(profileId: string) {
  return request<SessionResponse>("/api/sessions", { method: "POST", body: JSON.stringify({ profile_id: profileId }) });
}

export function getSession(sessionId: string) {
  return request<SessionView>(`/api/sessions/${sessionId}`);
}

export function submitAnswer(sessionId: string, input: AnswerInput) {
  return request<{ answer: Record<string, string>; observation: Observation | null }>(
    `/api/sessions/${sessionId}/answers`,
    { method: "POST", body: JSON.stringify(input) },
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
};

export function getReport(sessionId: string) {
  return request<Report>(`/api/sessions/${sessionId}/report`);
}
