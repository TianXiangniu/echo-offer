import { strict as assert } from "node:assert";
import { existsSync, readFileSync } from "node:fs";

const api = readFileSync(new URL("./api.ts", import.meta.url), "utf8");
const pagePath = new URL("../app/profile/page.tsx", import.meta.url);
const homePage = readFileSync(new URL("../app/page.tsx", import.meta.url), "utf8");
const consolePage = readFileSync(new URL("../app/console/page.tsx", import.meta.url), "utf8");
const historyPage = readFileSync(new URL("../app/history/page.tsx", import.meta.url), "utf8");

assert.match(api, /export type ProfileSummary/);
assert.match(api, /export type ProfileSnapshot/);
assert.match(api, /getProfileSummary/);
assert.match(api, /getProfileHistory/);
assert.match(api, /updateRecommendationStatus/);
assert.equal(existsSync(pagePath), true, "profile page is missing");
for (const source of [homePage, consolePage, historyPage]) {
  assert.match(source, /href=["']\/profile["']/);
}
assert.match(historyPage, /profile_id/);

const page = readFileSync(pagePath, "utf8");
for (const token of [
  "getInterviewHistory",
  "getProfileSummary",
  "getProfileHistory",
  "我还要补什么",
  "优先回看",
  "接着练",
  "再答几次看看",
  "查看完整记录",
  "以前的面试记录",
  "查看这次回答",
  "还没有足够的回答可以判断",
  "再完成几次面试，这里的建议会更具体。",
  "/profile",
]) {
  const escaped = token.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  assert.match(page, new RegExp(escaped), `missing profile page contract: ${token}`);
}

for (const token of ["0～100", "冻结事实", "盲评分器", "稳定程度", "有效样本", "画像"]) {
  assert.equal(page.includes(token), false, `internal wording should not appear: ${token}`);
}

assert.match(page, /#question-\$\{encodeURIComponent\(recommendation\.source_question_id\)\}/);

console.log("profile page contract tests passed");
