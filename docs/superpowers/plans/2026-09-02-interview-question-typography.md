# 面试题目字号优化实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将面试页面的项目问题标题调整为更适合连续阅读的字号和行高。

**Architecture:** 只修改现有 Soft Mint 视觉系统中的 `.mint-question-title` 规则，不新增组件、不改变 React 逻辑、不影响首页和报告页。使用一个针对 CSS 契约的前端测试保护字号范围。

**Tech Stack:** Next.js、TypeScript、现有 Node 原生测试脚本、CSS。

## Global Constraints

- 只调整 `frontend/app/interview/[id]/page.tsx` 使用的 `.mint-question-title` 样式。
- 题目字号使用 `clamp(27px, 3vw, 40px)`，行高使用 `1.25`，字距使用 `-0.04em`。
- 不修改首页主标题、报告页标题、答题输入框字号、业务逻辑或接口。
- 保留工作区中此前未提交的用户 UI 改动，不将它们加入本次提交。
- 不推送或同步任何内容到 GitHub。

---

### Task 1: Add a failing typography contract test

**Files:**
- Create: `frontend/lib/interview-typography.test.ts`
- Reference: `frontend/app/globals.css`
- Modify: `frontend/package.json`

**Interfaces:**
- Produces a Node-runnable test that reads the existing CSS and checks the `.mint-question-title` declaration.

- [ ] **Step 1: Write the failing test**

Create a test that reads `frontend/app/globals.css`, extracts the `.mint-question-title` declaration, and asserts that it contains the target values while rejecting the old maximum size:

```ts
import { readFileSync } from "node:fs";

const css = readFileSync(new URL("../app/globals.css", import.meta.url), "utf8");
const match = css.match(/\.mint-question-title\s*\{([^}]+)\}/);

if (!match) throw new Error("missing interview question title styles");
const declaration = match[1];
for (const token of ["clamp(27px, 3vw, 40px)", "line-height: 1.25", "letter-spacing: -0.04em"]) {
  if (!declaration.includes(token)) throw new Error(`missing typography token: ${token}`);
}
if (declaration.includes("58px")) throw new Error("interview question title is still oversized");
```

Add an npm script named `test:interview-typography` that runs this file with the same Node flag used by the existing tests, and include it in the `test` script.

- [ ] **Step 2: Run the focused test and verify RED**

Run: `npm run test:interview-typography`

Expected: FAIL because the current declaration still uses `clamp(32px, 4.8vw, 58px)` and the old line-height and letter-spacing.

### Task 2: Apply the minimal CSS change

**Files:**
- Modify: `frontend/app/globals.css` at the `.mint-question-title` rule.

**Interfaces:**
- Consumes the existing `.mint-question-title` class from `frontend/app/interview/[id]/page.tsx`.
- Produces the smaller responsive title style used by the interview page.

- [ ] **Step 1: Change only the title declaration**

Replace the existing title declaration with:

```css
.mint-question-title {
  margin: 21px 0 0;
  color: var(--color-forest);
  font-family: var(--font-display);
  font-size: clamp(27px, 3vw, 40px);
  letter-spacing: -0.04em;
  line-height: 1.25;
}
```

Do not edit the mobile media query or any other `.mint-*` rule.

- [ ] **Step 2: Run the focused test and verify GREEN**

Run: `npm run test:interview-typography`

Expected: PASS with exit code 0.

- [ ] **Step 3: Commit the focused UI change**

```powershell
git add -- frontend/app/globals.css frontend/lib/interview-typography.test.ts frontend/package.json
git commit -m "fix: reduce interview question title size"
```

### Task 3: Run regression verification

**Files:**
- Test: existing frontend test suite

- [ ] **Step 1: Run all frontend tests**

Run from `frontend`:

```powershell
npm test
```

Expected: all existing copy, UI, supplement, and typography checks exit with code 0.

- [ ] **Step 2: Run the production build**

Run from `frontend`:

```powershell
npm run build
```

Expected: Next.js compilation, type checking, and static generation complete with exit code 0.

- [ ] **Step 3: Check the scoped diff and working tree safety**

Run from the project root:

```powershell
git diff --check HEAD~1..HEAD
git status --short
```

Expected: the latest commit contains only the typography test, package script, and `.mint-question-title` CSS change; previously uncommitted user files remain untouched and no GitHub push is performed.
