export type InterviewType = "foundation" | "project";

const entries = {
  foundation: {
    path: "/interview",
    title: "大模型基础面试",
    description: "从题库抽取技术问题，练习模型、Agent、RAG 和工程基础。",
    action: "开始基础面试",
  },
  project: {
    path: "/project",
    title: "项目经历面试",
    description: "上传简历，让 AI 整理项目，再围绕真实经历进行连续追问。",
    action: "整理项目并开始",
  },
} as const;

export function interviewEntry(type: InterviewType) {
  return entries[type];
}

export function interviewEntryPath(type: InterviewType) {
  return interviewEntry(type).path;
}

export function interviewTypeLabel(type: InterviewType) {
  return interviewEntry(type).title;
}

export function interviewRecordTitle(type: InterviewType, projectName: string | null) {
  return type === "foundation" ? interviewTypeLabel(type) : projectName || interviewTypeLabel(type);
}
