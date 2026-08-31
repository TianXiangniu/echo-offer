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
