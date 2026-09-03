import { strict as assert } from "node:assert";
import { readFileSync } from "node:fs";

const api = readFileSync(new URL("./api.ts", import.meta.url), "utf8");
const page = readFileSync(new URL("../app/profile/page.tsx", import.meta.url), "utf8");
const report = readFileSync(new URL("../app/report/[id]/page.tsx", import.meta.url), "utf8");
const globals = readFileSync(new URL("../app/globals.css", import.meta.url), "utf8");

assert.match(api, /source_session_id: string \| null/);
assert.match(api, /source_question_id: string \| null/);
assert.match(api, /source_question: string \| null/);
assert.match(api, /source_answer_excerpt: string \| null/);
assert.match(api, /source_level: number \| null/);
assert.match(page, /我还要补什么/);
assert.match(page, /优先回看/);
assert.match(page, /接着练/);
assert.match(page, /再答几次看看/);
assert.match(page, /查看这次回答/);
assert.match(page, /还没有足够的回答可以判断/);
assert.match(page, /question-/);
assert.match(report, /question-/);
assert.match(globals, /\.mint-question-/);

for (const forbidden of [
  "冻结事实",
  "盲评分器",
  "稳定程度",
  "有效样本",
  "profile_snapshot",
  "last_session_id",
]) {
  assert.equal(page.includes(forbidden), false);
}

console.log("profile weak points contract tests passed");
