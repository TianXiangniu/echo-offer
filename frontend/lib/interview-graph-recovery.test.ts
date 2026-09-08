import { normalizeGraphState } from "./interview-graph.ts";

const view = normalizeGraphState({
  status: "awaiting_answer",
  degraded: true,
  nodes: [],
  current_question: { prompt: "保底问题" },
});

if (view.degraded !== true) throw new Error("degraded state must be preserved");
if (view.current_question?.prompt !== "保底问题") throw new Error("question must survive recovery");
console.log("interview graph recovery tests passed");
