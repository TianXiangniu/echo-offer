import { canStartInterview, getHomeStep } from "./home-flow.ts";

if (getHomeStep({ hasResume: false, hasAnalysis: false }) !== 1) {
  throw new Error("initial state must be step 1");
}

if (getHomeStep({ hasResume: true, hasAnalysis: false }) !== 2) {
  throw new Error("parsed resume must be step 2");
}

if (getHomeStep({ hasResume: true, hasAnalysis: true }) !== 3) {
  throw new Error("analysis result must be step 3");
}

if (canStartInterview({ hasResume: true, hasAnalysis: false })) {
  throw new Error("analysis is required");
}

console.log("home flow tests passed");
