import { strict as assert } from "node:assert";
import { readFileSync } from "node:fs";

const api = readFileSync(new URL("./api.ts", import.meta.url), "utf8");
const page = readFileSync(new URL("../app/profile/page.tsx", import.meta.url), "utf8");
const report = readFileSync(new URL("../app/report/[id]/page.tsx", import.meta.url), "utf8");
const globals = readFileSync(new URL("../app/globals.css", import.meta.url), "utf8");

function getRuleBlock(source: string, selector: string) {
  const match = source.match(new RegExp(`${selector} \\{[\\s\\S]*?\\}`, "m"));
  assert.ok(match, `missing rule block for ${selector}`);
  return match[0];
}

function getMediaBlock(source: string, mediaQuery: string) {
  const start = source.lastIndexOf(`@media (${mediaQuery}) {`);
  assert.ok(start >= 0, `missing media block for ${mediaQuery}`);
  const nextMedia = source.indexOf("\n@media ", start + 1);
  return source.slice(start, nextMedia === -1 ? undefined : nextMedia);
}

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

for (const field of [
  "source_session_id",
  "source_question_id",
  "source_question",
  "source_answer_excerpt",
  "source_level",
]) {
  assert.match(page, new RegExp(`${field}:\\s*updated\\.${field}[,\\s]`));
  assert.doesNotMatch(page, new RegExp(`${field}:\\s*updated\\.${field}\\s*\\?\\?`));
}

const weakPointCard = getRuleBlock(globals, "\\.mint-weak-point-card");
assert.match(weakPointCard, /padding:\s*25px 27px 24px/);

const weakPointSource = getRuleBlock(globals, "\\.mint-weak-point-source");
assert.match(weakPointSource, /border-left:\s*2px solid var\(--color-coral\)/);

const weakPointActions = getRuleBlock(globals, "\\.mint-weak-point-actions");
assert.match(weakPointActions, /display:\s*flex/);
assert.match(weakPointActions, /flex-wrap:\s*wrap/);

const mobileMedia = getMediaBlock(globals, "max-width: 820px");
assert.match(mobileMedia, /\.mint-weak-point-card/);
assert.match(mobileMedia, /\.mint-weak-point-actions/);

const reducedMotionMedia = getMediaBlock(globals, "prefers-reduced-motion: reduce");
assert.match(reducedMotionMedia, /transition-duration:\s*0\.01ms/);
assert.match(reducedMotionMedia, /animation-duration:\s*0\.01ms/);

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
