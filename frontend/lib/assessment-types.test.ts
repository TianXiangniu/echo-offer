import type {
  AssessmentBatchResponse,
  AssessmentResult,
  ProjectAnalysisDetails,
  ProjectFact,
  ProjectQuestionDetail,
  RubricObservation,
} from "./api";
import { assessmentStages, isAssessmentRetryable } from "./assessment-flow.ts";

const rubricObservation: RubricObservation = {
  rubric_id: "mechanism",
  level: 3,
  evidence_start: 0,
  evidence_end: 2,
  quoted_text: "机制",
  confidence: 0.8,
  validity: "valid",
};

const assessment: AssessmentResult = {
  status: "valid",
  evaluator: "siliconflow-blind-rubric-v1",
  level: 3,
  confidence: 0.8,
  error_code: null,
  error_reason: null,
  rubric_items: [rubricObservation],
};

if (assessment.rubric_items[0]?.rubric_id !== "mechanism") {
  throw new Error("AI assessment type contract failed");
}

const batchResponse: AssessmentBatchResponse = {
  status: "valid",
  batch_id: "batch-1",
  evaluated_count: 2,
  total_count: 3,
  assessments: [],
};

if (batchResponse.evaluated_count !== 2) {
  throw new Error("batch assessment type contract failed");
}

if (assessmentStages.length !== 3 || assessmentStages[1] !== "整理回答") {
  throw new Error("batch assessment stage contract failed");
}

if (!isAssessmentRetryable("pending") || isAssessmentRetryable("valid")) {
  throw new Error("batch assessment retry contract failed");
}

const details: ProjectAnalysisDetails = {
  context: {
    project_type: "企业知识库 Agent",
  },
  ownership: {
    owned_modules: "检索链路",
  },
  architecture: {},
  agent_details: {},
  tradeoffs: {},
  engineering: {},
  evaluation: {},
  evolution: {},
};

const fact: ProjectFact = {
  fact_id: "fact-1",
  field: "ownership.owned_modules",
  value: "检索链路",
  status: "extracted",
  source_type: "resume",
  evidence: [],
  confidence: 0.96,
  user_confirmed: false,
};

const question: ProjectQuestionDetail = {
  order: 1,
  question_group: "project",
  chain_id: "project-main",
  prompt: "你负责了哪些部分？",
  intent: "确认个人贡献",
  depends_on: null,
  source_fields: ["background_goal", "ownership.owned_modules"],
  source_fact_ids: ["fact-1"],
  expected_answer_points: [],
  followup_if_incomplete: "请先说明你的职责边界。",
  followup_if_conflicting: "请澄清你和团队的分工。",
  difficulty: "medium",
};

if (details.ownership?.owned_modules !== "检索链路") {
  throw new Error("project analysis details type contract failed");
}

if (fact.status !== "extracted" || question.question_group !== "project") {
  throw new Error("project fact/question type contract failed");
}
