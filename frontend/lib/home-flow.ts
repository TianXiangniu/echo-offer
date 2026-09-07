type HomeFlowState = { hasResume: boolean; hasAnalysis: boolean };

export function getHomeStep({ hasResume, hasAnalysis }: HomeFlowState): 1 | 2 | 3 {
  return hasAnalysis ? 3 : hasResume ? 2 : 1;
}

export function canStartInterview({ hasResume, hasAnalysis }: HomeFlowState) {
  return hasResume && hasAnalysis;
}
