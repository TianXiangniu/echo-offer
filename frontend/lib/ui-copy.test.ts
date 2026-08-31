import { readFileSync } from "node:fs";
import { homeCopy, interviewCopy, reportCopy, statusCopy } from "./ui-copy.ts";

const required = [
  homeCopy.projectTitle,
  interviewCopy.saveAndContinue,
  reportCopy.feedbackTitle,
  statusCopy.timeoutTitle,
];

if (required.some((value) => !value.trim())) throw new Error("required UI copy is empty");

const forbidden = /Evidence Rail|Rubric|冻结事实|可信边界|模型说明/;
const allCopy = JSON.stringify({ homeCopy, interviewCopy, reportCopy, statusCopy });
if (forbidden.test(allCopy)) throw new Error("internal terminology leaked into UI copy");

if (homeCopy.projectTitle !== "先把项目说清楚。") throw new Error("home title mismatch");
if (statusCopy.timeoutAction !== "重新生成报告") throw new Error("timeout action mismatch");

const css = readFileSync(new URL("../app/globals.css", import.meta.url), "utf8");
for (const token of ["#182438", "#E9EDF2", "#F8FAFB", "#2F57D1", "#FF7043", "prefers-reduced-motion"]) {
  if (!css.toUpperCase().includes(token.toUpperCase())) throw new Error(`missing visual token: ${token}`);
}

const homePage = readFileSync(new URL("../app/page.tsx", import.meta.url), "utf8");
for (const token of ["homeCopy", "准备进度", "确认项目，开始面试"]) {
  if (!homePage.includes(token)) throw new Error(`home page missing: ${token}`);
}
for (const token of ["Evidence Rail", "冻结事实", "模型引用证据"]) {
  if (homePage.includes(token)) throw new Error(`home page leaked: ${token}`);
}

const interviewPage = readFileSync(new URL("../app/interview/[id]/page.tsx", import.meta.url), "utf8");
const assessmentFlow = readFileSync(new URL("./assessment-flow.ts", import.meta.url), "utf8");
for (const token of ["interviewCopy", "保存并继续", "本题不提供提示", "答题进度"]) {
  if (!interviewPage.includes(token)) throw new Error(`interview page missing: ${token}`);
}
for (const token of ["Evidence Rail", "Rubric", "请求模型", "校验证据"]) {
  if (interviewPage.includes(token)) throw new Error(`interview page leaked: ${token}`);
  if (assessmentFlow.includes(token)) throw new Error(`assessment flow leaked: ${token}`);
}
