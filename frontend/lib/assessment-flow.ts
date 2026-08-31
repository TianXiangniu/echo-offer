export const assessmentStages = [
  "收集回答",
  "请求模型",
  "校验证据",
  "生成报告",
] as const;

export type AssessmentStage = (typeof assessmentStages)[number];

const retryableAssessmentStatuses = new Set(["pending", "invalid", "rejected"]);

export function isAssessmentRetryable(status: string) {
  return retryableAssessmentStatuses.has(status);
}
