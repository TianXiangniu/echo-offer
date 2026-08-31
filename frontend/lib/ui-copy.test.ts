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
