export const assessmentStages = [
  "保存回答",
  "整理回答",
  "生成报告",
] as const;

export type AssessmentStage = (typeof assessmentStages)[number];

const retryableAssessmentStatuses = new Set(["pending", "invalid", "rejected"]);

export function isAssessmentRetryable(status: string) {
  return retryableAssessmentStatuses.has(status);
}
