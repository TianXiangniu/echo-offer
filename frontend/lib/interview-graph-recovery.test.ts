import { normalizeGraphState } from "./interview-graph.ts";

const view = normalizeGraphState({
  status: "awaiting_answer",
  degraded: true,
  nodes: [],
  current_question: { id: "fallback-question", prompt: "保底问题" },
  assessment: { status: "valid", batch_id: null, evaluated_count: 6, total_count: 6, assessments: [] },
});

if (view.degraded !== true) throw new Error("degraded state must be preserved");
if (view.current_question?.prompt !== "保底问题") throw new Error("question must survive recovery");
if (view.assessment?.status !== "valid") throw new Error("assessment must survive recovery");
console.log("interview graph recovery tests passed");
