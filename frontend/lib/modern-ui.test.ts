import { readFileSync } from "node:fs";

const css = readFileSync(new URL("../app/globals.css", import.meta.url), "utf8");
const homePage = readFileSync(new URL("../app/page.tsx", import.meta.url), "utf8");
const interviewPage = readFileSync(new URL("../app/interview/[id]/page.tsx", import.meta.url), "utf8");
const reportPage = readFileSync(new URL("../app/report/[id]/page.tsx", import.meta.url), "utf8");
const copy = readFileSync(new URL("./ui-copy.ts", import.meta.url), "utf8");

for (const token of ["--color-mint-50", "--color-forest", "--color-coral", ".mint-page", ".mint-card", "prefers-reduced-motion"]) {
  if (!css.includes(token)) throw new Error(`missing Soft Mint visual contract: ${token}`);
}

for (const [name, source] of [["home", homePage], ["interview", interviewPage], ["report", reportPage]] as const) {
  if (!source.includes("mint-page")) throw new Error(`${name} page is not using the Soft Mint layout`);
  if (source.includes("signal-rail") || source.includes("signal-workspace")) {
    throw new Error(`${name} page still uses the workbench layout`);
  }
}

for (const token of ["把你做过的项目，", "上传你的简历", "按真实面试的方式练一遍"]) {
  if (!copy.includes(token)) throw new Error(`copy is missing natural home text: ${token}`);
}

for (const token of ["你的回答", "保存并继续", "全部答完后，再一起看看结果"]) {
  if (!copy.includes(token) && !interviewPage.includes(token)) throw new Error(`interview page missing natural copy: ${token}`);
}

for (const token of ["答得好的地方", "可以补充的地方", "下一步练习"]) {
  if (!reportPage.includes(token)) throw new Error(`report page missing natural report copy: ${token}`);
}

const forbidden = /Evidence Rail|Rubric|冻结事实|可信边界|模型说明|请求模型|校验证据|锚题|可用摘录|平均参考程度/;
if (forbidden.test(`${homePage}${interviewPage}${reportPage}`)) throw new Error("internal terminology leaked into the UI");
