import type { AssessmentBatchResponse, AssessmentResult, RubricObservation } from "./api";
import { assessmentStages, isAssessmentRetryable } from "./assessment-flow";

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
