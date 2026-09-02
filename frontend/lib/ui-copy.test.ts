import { readFileSync } from "node:fs";
import { homeCopy, interviewCopy, reportCopy, statusCopy } from "./ui-copy.ts";

const required = [homeCopy.projectTitle, interviewCopy.saveAndContinue, reportCopy.feedbackTitle, statusCopy.timeoutTitle];
if (required.some((value) => !value.trim())) throw new Error("required UI copy is empty");

const forbidden = /Evidence Rail|Rubric|冻结事实|可信边界|模型说明|请求模型|校验证据|锚题|可用摘录|平均参考程度/;
const allCopy = JSON.stringify({ homeCopy, interviewCopy, reportCopy, statusCopy });
if (forbidden.test(allCopy)) throw new Error("internal terminology leaked into UI copy");

if (homeCopy.projectTitle !== "把你做过的项目，讲清楚。") throw new Error("home title mismatch");
if (homeCopy.uploadTitle !== "上传你的简历") throw new Error("resume upload copy mismatch");
if (statusCopy.timeoutAction !== "再生成一次") throw new Error("timeout action mismatch");

const css = readFileSync(new URL("../app/globals.css", import.meta.url), "utf8");
for (const token of ["--color-mint-50", "--color-forest", "--color-coral", ".mint-page", ".mint-card", "prefers-reduced-motion"]) {
  if (!css.includes(token)) throw new Error(`missing visual token: ${token}`);
}

const homePage = readFileSync(new URL("../app/page.tsx", import.meta.url), "utf8");
for (const token of ["mint-page", "homeCopy", "mint-upload-card", "确认内容，开始面试"]) {
  if (!homePage.includes(token)) throw new Error(`home page missing: ${token}`);
}

const interviewPage = readFileSync(new URL("../app/interview/[id]/page.tsx", import.meta.url), "utf8");
for (const token of ["mint-page", "interviewCopy", "保存并继续", "题目进度", "你的回答"]) {
  if (!interviewPage.includes(token)) throw new Error(`interview page missing: ${token}`);
}

const reportPage = readFileSync(new URL("../app/report/[id]/page.tsx", import.meta.url), "utf8");
for (const token of ["mint-page", "reportCopy", "你的回答", "每道题的反馈", "本场结果", "重点问题完成"]) {
  if (!reportPage.includes(token)) throw new Error(`report page missing: ${token}`);
}
if (!reportPage.includes('?? "处理中"')) throw new Error("report status needs a natural fallback");
if (!reportPage.includes('?? "暂时无法判断"')) throw new Error("report level needs a natural fallback");

for (const source of [homePage, interviewPage, reportPage]) {
  if (source.includes("signal-rail") || source.includes("signal-workspace")) throw new Error("workbench layout leaked into a route");
  if (forbidden.test(source)) throw new Error("internal terminology leaked into a route");
  if (!source.includes("aria-label")) throw new Error("route needs named navigation/work areas");
}

for (const token of ["先做这一步", "随时可以修改", "先把简历放进来", "把简历放进来"]) {
  if (homePage.includes(token)) throw new Error(`AI-like home copy remains: ${token}`);
}

if (!css.includes("@media (max-width")) throw new Error("responsive layout contract missing");
