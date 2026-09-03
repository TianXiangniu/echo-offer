import type { LearningRecommendation } from "./api";

export function replaceRecommendation(
  recommendations: LearningRecommendation[],
  updated: LearningRecommendation,
): LearningRecommendation[] {
  return recommendations.map((item) => item.id === updated.id ? updated : item);
}
