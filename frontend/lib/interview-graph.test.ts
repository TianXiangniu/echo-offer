import { normalizeGraphState } from "./interview-graph.ts";

const active = normalizeGraphState({
  status: "awaiting_answer",
  nodes: [{ id: "context", status: "active" }],
  current_question: { id: "q1", prompt: "请介绍你的职责" },
});

if (active.canAnswer !== true) throw new Error("waiting graph must accept an answer");
if (active.interview_type !== "project") throw new Error("graph interviews should be project interviews");
if (active.nodes[0]?.label !== "项目与职责") throw new Error("node label must be localized");

const completed = normalizeGraphState({ status: "completed", nodes: [], current_question: null });
if (completed.canAnswer !== false) throw new Error("completed graph must lock the answer input");

console.log("interview graph tests passed");
