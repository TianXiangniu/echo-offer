import type { AssessmentResult, RubricObservation } from "./api";

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
