import type { AssessmentBatchResponse } from "./api.ts";
import { isAssessmentRetryable } from "./assessment-flow.ts";
import { assessmentFailureMessage, hasUsableAssessmentResult } from "./assessment-copy.ts";

const batchResponse: AssessmentBatchResponse = {
  status: "valid",
  batch_id: "batch-1",
  job_id: "job-1",
  job_status: "succeeded",
  job_error_code: null,
  job_error_message: null,
  evaluated_count: 2,
  total_count: 3,
  assessments: [],
};

if (!isAssessmentRetryable("pending") || isAssessmentRetryable("valid")) {
  throw new Error("batch assessment retry contract failed");
}

const truncatedResponse: AssessmentBatchResponse = {
  ...batchResponse,
  status: "pending",
  job_status: "partial",
  job_error_code: "provider_output_truncated",
  job_error_message: "模型输出达到长度上限，内容不完整",
};

if (!assessmentFailureMessage(truncatedResponse).includes("输出太长")) {
  throw new Error("assessment error copy contract failed");
}

if (!hasUsableAssessmentResult(truncatedResponse)) {
  throw new Error("partial assessment result should remain viewable");
}

console.log("assessment copy tests passed");
