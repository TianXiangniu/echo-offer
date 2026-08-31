export const brandCopy = {
  name: "Echo Offer",
  preparation: "准备面试",
  interview: "面试",
  report: "本场报告",
} as const;

export const homeCopy = {
  eyebrow: "从简历开始",
  projectTitle: "先把项目说清楚。",
  projectDescription: "上传简历后，我们会整理出一个相关项目。内容可以修改，确认无误后再开始面试。",
  uploadTitle: "上传简历",
  uploadHint: "支持 PDF 和 DOCX，解析后可以继续修改。",
  projectSection: "项目内容",
  projectFields: {
    project_name: "项目名称",
    background_goal: "要解决的问题",
    tech_stack: "技术栈",
    responsibilities: "你负责的部分",
    core_solution: "主要方案",
    engineering_challenges: "遇到的难点",
    failure_improvements: "出问题后怎么改",
    quantified_results: "最终结果",
  },
  analyze: "帮我整理这个项目",
  analyzeAgain: "重新整理",
  confirm: "确认项目，开始面试",
} as const;

export const interviewCopy = {
  progress: "答题进度",
  questionOf: (current: number, total: number) => `第 ${current} 题，共 ${total} 题`,
  answerHelp: "先按真实面试回答。全部答完后，系统会一次生成本场报告。",
  noHint: "本题不提供提示",
  saveAndContinue: "保存并继续",
  unknown: "我不知道",
  skip: "跳过",
  completedTitle: "这场面试已经完成。",
  generatingTitle: "正在生成本场报告。",
} as const;

export const reportCopy = {
  content: "报告内容",
  feedbackTitle: "看看哪些地方答得好，哪些还可以补充。",
  answerExcerpt: "回答摘录",
  scoreReason: "评分理由",
  scoreExplanation: "评分说明",
  goodAnswers: "回答较好的地方",
  improvements: "可以改进的地方",
  completed: "完成题目",
  goodCount: "较好回答（展示）",
  improveCount: "需要加强（展示）",
} as const;

export const statusCopy = {
  saved: "回答已经保存。",
  generating: "正在整理回答，请保持页面打开。",
  timeoutTitle: "这次没有拿到评分结果。",
  timeoutReason: "模型服务响应较慢",
  timeoutDescription: "回答已经保存，不需要重新答题。可以直接再试一次，也可以稍后回来。",
  timeoutAction: "重新生成报告",
  backHome: "返回首页",
} as const;
