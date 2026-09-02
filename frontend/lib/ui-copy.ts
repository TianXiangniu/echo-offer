import type { MissingInformationItem } from "./api";

export const brandCopy = {
  name: "Echo Offer",
  preparation: "准备面试",
  interview: "面试",
  report: "本场结果",
} as const;

export const homeCopy = {
  eyebrow: "Echo Offer · Agent 面试准备",
  projectTitle: "把你做过的项目，讲清楚。",
  projectDescription: "上传一份简历，我们先挑出一个项目；你确认内容后，再按真实面试的方式练一遍。",
  uploadTitle: "上传你的简历",
  uploadHint: "支持 PDF 和 DOCX，上传后可以检查文字。",
  projectSection: "确认一个项目",
  projectFields: {
    project_name: "项目名称",
    background_goal: "它要解决什么问题",
    tech_stack: "技术栈",
    responsibilities: "你负责的部分",
    core_solution: "你是怎么做的",
    engineering_challenges: "哪里最难",
    failure_improvements: "出过什么问题，怎么改",
    quantified_results: "最后有什么结果",
  },
  analyze: "从简历里整理项目",
  analyzeAgain: "重新整理",
  confirm: "确认内容，开始面试",
} as const;

export const interviewCopy = {
  progress: "题目进度",
  questionOf: (current: number, total: number) => `第 ${current} 题 / 共 ${total} 题`,
  answerHelp: "按你真实做过的事情来答，全部答完后，再一起看看结果。",
  noHint: "这题不提供提示",
  saveAndContinue: "保存并继续",
  unknown: "我不知道",
  skip: "跳过",
  completedTitle: "这场练习完成了。",
  generatingTitle: "正在整理你的结果。",
} as const;

export const reportCopy = {
  content: "结果回看",
  feedbackTitle: "先看看答得好的地方，再补上缺的部分。",
  answerExcerpt: "你的回答",
  scoreReason: "为什么这样判断",
  scoreExplanation: "这次结果怎么来的",
  goodAnswers: "答得好的地方",
  improvements: "可以补充的地方",
  completed: "完成题目",
  goodCount: "答得扎实",
  improveCount: "需要补充",
} as const;

export const statusCopy = {
  saved: "回答已经保存。",
  generating: "正在整理回答，请先不要关闭页面。",
  timeoutTitle: "结果还没有生成出来。",
  timeoutReason: "服务响应比较慢",
  timeoutDescription: "回答已经保存，不需要重新答题。可以再试一次，也可以稍后回来。",
  timeoutAction: "再生成一次",
  backHome: "返回首页",
} as const;

const missingInformationPromptMap: Record<string, string> = {
  project_name: "这个项目具体叫什么名字？",
  background_goal: "这个项目当时为什么要做？",
  tech_stack: "当时主要用了哪些技术或工具？",
  responsibilities: "哪些部分是你亲自完成的？",
  core_solution: "核心方案是怎么设计的？",
  engineering_challenges: "过程中最难的技术问题是什么？",
  failure_improvements: "出过什么问题？后来怎么改进的？",
  quantified_results: "最后效果怎么样？有数据吗？",
  "context.stage": "项目做到什么阶段了？",
  "context.scale": "这个项目实际服务了多大规模？",
  "context.users": "这个项目实际服务了多大规模？",
  "context.timeline": "这个项目是在哪个阶段推进的？",
  "ownership.owned_modules": "哪些部分是你亲自完成的？",
  "ownership.collaborators": "你和谁一起配合，边界怎么分？",
  "ownership.scope": "哪些部分是你亲自完成的？",
  "architecture.pipeline": "核心方案是怎么设计的？",
  "architecture.tools": "当时主要用了哪些技术或工具？",
  "architecture.retrieval": "核心方案是怎么设计的？",
  "agent_details.loop": "Agent 在关键环节是怎么工作的？",
  "agent_details.tools": "Agent 用到了哪些工具，怎么调用的？",
  "tradeoffs.chosen_approach": "为什么最后选了这个方案？",
  "tradeoffs.rejected_options": "当时放弃过哪些方案，为什么？",
  "engineering.latency_diagnosis": "线上变慢时你是怎么排查的？",
  "engineering.output_safety": "你怎么保证输出结果更稳、更安全？",
  "evaluation.metrics": "最后效果怎么样？有数据吗？",
  "evaluation.baseline": "有没有和旧方案或基线做过对比？",
  "evolution.iterations": "上线后又迭代或优化过什么？",
};

const forbiddenMissingInformationTerms = /冻结事实|可信边界模型|可信边界|模型说明|请求模型|校验证据|锚题|可用摘录|平均参考程度|Evidence Rail|Rubric/i;

function inferMissingInformationPrompt(item: string) {
  if (forbiddenMissingInformationTerms.test(item)) return null;
  if (/流量|规模|用户量|调用量|并发|qps/i.test(item)) return "这个项目实际服务了多大规模？";
  if (/阶段|上线|落地|发布|时间线/i.test(item)) return "项目做到什么阶段了？";
  if (/负责|亲自|职责|模块|owner|ownership/i.test(item)) return "哪些部分是你亲自完成的？";
  if (/指标|效果|结果|准确|召回|时延|延迟|成本|baseline|评估/i.test(item)) return "最后效果怎么样？有数据吗？";
  if (/技术栈|框架|模型|数据库|工具/i.test(item)) return "当时主要用了哪些技术或工具？";
  if (/架构|方案|流程|链路|检索|agent/i.test(item)) return "核心方案是怎么设计的？";
  if (/难点|故障|稳定性|安全|异常|排查/i.test(item)) return "过程中最难的技术问题是什么？";
  if (/失败|改进|优化|迭代/i.test(item)) return "出过什么问题？后来怎么改进的？";
  return null;
}

export function getMissingInformationPrompts(items: MissingInformationItem[]) {
  const prompts: string[] = [];

  for (const item of items) {
    const normalized = item.trim();
    if (!normalized) continue;
    const prompt = missingInformationPromptMap[normalized] ?? inferMissingInformationPrompt(normalized);
    if (!prompt || prompts.includes(prompt)) continue;
    prompts.push(prompt);
    if (prompts.length === 3) break;
  }

  return prompts;
}
