import { readFileSync } from "node:fs";

const api = readFileSync(new URL("./api.ts", import.meta.url), "utf8");
const page = readFileSync(new URL("../app/history/page.tsx", import.meta.url), "utf8");

for (const token of ["InterviewHistoryItem", "getInterviewHistory", "deleteInterview", "/api/interviews/history", "/api/sessions/"]) {
  if (!api.includes(token)) throw new Error(`history API contract missing: ${token}`);
}
for (const token of ["面试记录", "继续面试", "查看结果", "重新生成", "删除记录", "再试一次", "还没有面试记录", "/interview/", "/report/"]) {
  if (!page.includes(token)) throw new Error(`history page contract missing: ${token}`);
}
if (/0～100|冻结事实|可信边界|Evidence Rail|Rubric/.test(page)) {
  throw new Error("internal evaluation copy leaked into history page");
}

console.log("history page contract tests passed");
