import type { AssessmentBatchResponse } from "./api";

const assessmentErrorMessages: Record<string, string> = {
  provider_auth_failed: "评分服务的配置有问题。",
  provider_rate_limited: "评分服务现在比较忙。",
  provider_timeout: "评分服务响应超时。",
  provider_output_truncated: "模型输出太长，内容没有完整返回。",
  provider_connection_failed: "暂时连不上评分服务。",
  empty_model_response: "评分服务没有返回内容。",
  invalid_json: "评分服务返回的内容无法读取。",
  invalid_model_response: "评分服务返回的结构不完整。",
  invalid_schema: "评分服务返回的字段不符合要求。",
  invalid_batch_case: "评分结果和本场回答没有对应上。",
  invalid_evidence: "部分回答里的引用无法核对。",
  stale_job: "上一轮评分已经超时，正在允许重新生成。",
  system_error: "整理结果时遇到了本地错误。",
};

export function hasUsableAssessmentResult(result: AssessmentBatchResponse) {
  return (
    result.status === "valid" ||
    result.status === "partial" ||
    result.job_status === "partial"
  );
}

export function assessmentFailureMessage(result: AssessmentBatchResponse) {
  const code =
    result.job_error_code ??
    result.assessments.find((item) => item.assessment.error_code)?.assessment.error_code;
  const message = assessmentErrorMessages[code ?? ""] ?? "这次没有拿到完整结果。";
  if (result.status === "partial" || result.job_status === "partial") {
    return `部分题目已经完成。${message}已完成的结果会保留。`;
  }
  if (result.status === "pending" || result.job_status === "running") {
    return `结果还在处理中。${message}`;
  }
  return message;
}
