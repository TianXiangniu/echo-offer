export type GraphNodeStatus = "not_started" | "active" | "covered" | "needs_confirmation" | string;

export type GraphPlanNodeView = {
  id: string;
  kind: string;
  label: string;
  status: GraphNodeStatus;
};

export type GraphQuestionView = {
  id: string;
  order?: number;
  category?: string;
  prompt: string;
  knowledge_point_id?: string;
  answered?: boolean;
  followup?: null;
  feedback?: null;
};

export type GraphSessionView = {
  session_id?: string;
  status: string;
  mode: "graph";
  stage: string;
  current_question: GraphQuestionView | null;
  nodes: GraphPlanNodeView[];
  progress: { completed: number; total: number };
  timeline: DialogMessage[];
  canAnswer: boolean;
};

type GraphStateInput = {
  session_id?: string;
  status?: string;
  stage?: string;
  mode?: string;
  current_question?: GraphQuestionView | null;
  nodes?: Array<Partial<GraphPlanNodeView> & { id?: string }>;
  progress?: Partial<GraphSessionView["progress"]>;
  timeline?: DialogMessage[];
};

const NODE_LABELS: Record<string, string> = {
  context: "项目与职责",
  opening: "项目背景",
  project: "项目与职责",
  architecture: "架构设计",
  challenge: "难点与故障",
  tradeoff: "方案取舍",
  evidence: "效果与验证",
};

function nodeLabel(node: Partial<GraphPlanNodeView> & { id?: string }) {
  const key = String(node.kind || node.id || "");
  return NODE_LABELS[key] || String(node.label || node.kind || node.id || "面试节点");
}

export function normalizeGraphState(state: GraphStateInput): GraphSessionView {
  const status = String(state.status || "planning");
  const nodes = (state.nodes || []).map((node, index) => ({
    id: String(node.id || `node-${index}`),
    kind: String(node.kind || node.id || "graph"),
    label: nodeLabel(node),
    status: String(node.status || "not_started") as GraphNodeStatus,
  }));
  const total = Number(state.progress?.total ?? nodes.length);
  const completed = Number(state.progress?.completed ?? nodes.filter((node) => node.status === "covered").length);
  const currentQuestion = state.current_question || null;
  return {
    session_id: state.session_id,
    status,
    mode: "graph",
    stage: String(state.stage || "graph"),
    current_question: currentQuestion,
    nodes,
    progress: { completed, total },
    timeline: state.timeline || [],
    canAnswer: status === "awaiting_answer" && Boolean(currentQuestion),
  };
}
import type { DialogMessage } from "./api";
