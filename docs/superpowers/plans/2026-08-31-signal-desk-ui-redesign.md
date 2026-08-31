# Signal Desk UI Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 Echo Offer 的首页、面试答题页和评估报告页实现为已确认的 Signal Desk 视觉系统，并把主界面文案改成自然、直接的中文。

**Architecture:** 保留现有 Next.js App Router 页面和后端接口，不改变业务数据流。新增一个只负责界面文案的共享模块，页面继续各自负责布局和交互，颜色、字体、焦点和动效变量集中到 `globals.css`。每完成一个页面就运行对应的类型检查或页面构建验证。

**Tech Stack:** Next.js 15、React 19、TypeScript、Tailwind CSS 3、原生 CSS、Node 24 的 `--experimental-strip-types` 测试运行方式。

## Global Constraints

- 只调整前端界面、文案、布局和状态展示，不改变简历解析、项目分析、面试答题、批量评分和报告接口的业务逻辑。
- 产品面向准备投递 Agent 应用工程师岗位的求职者，页面任务是把项目内容说清楚、完成无提示答题、查看具体面试反馈。
- 使用 `#182438`、`#E9EDF2`、`#F8FAFB`、`#2F57D1`、`#FF7043`、`#AEB8C5` 作为界面基础色。
- 不使用大面积渐变、玻璃拟态、紫色霓虹、浮动光球或装饰性动画。
- 主界面不出现 `Evidence Rail`、`Rubric`、`冻结事实`、`可信边界` 等内部术语；技术信息只进入可展开详情或页脚。
- 桌面端使用左侧进度栏加右侧工作区，移动端折叠为顶部进度条；输入框、按钮和链接保留键盘焦点。
- 生成报告时不显示虚假的百分比或内部模型步骤；超时状态必须说明回答已保存并允许直接重试。
- 每道题提交后只保存回答，全部问题完成后统一生成一次评分报告；UI 不自行计算等级。
- 不增加新的 AI 模型、评分算法、登录、历史场次或跨场能力画像功能。
- 不同步到 GitHub。

---

### Task 1: 建立共享文案契约

**Files:**
- Create: `frontend/lib/ui-copy.ts`
- Create: `frontend/lib/ui-copy.test.ts`
- Modify: `frontend/package.json`

**Interfaces:**
- Produces exported constants `brandCopy`、`homeCopy`、`interviewCopy`、`reportCopy`、`statusCopy`。
- Each page imports the constants instead of duplicating user-facing labels.
- The test runs with `node --experimental-strip-types lib/ui-copy.test.ts` from `frontend`.

- [ ] **Step 1: Write the failing test**

Create `frontend/lib/ui-copy.test.ts` with assertions for the required user-facing copy and forbidden internal wording:

```ts
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `node --experimental-strip-types lib/ui-copy.test.ts`

Expected: FAIL because `frontend/lib/ui-copy.ts` does not exist.

- [ ] **Step 3: Write minimal implementation**

Create `frontend/lib/ui-copy.ts` with the agreed natural Chinese labels:

```ts
export const brandCopy = {
  name: "Echo Offer",
  preparation: "准备面试",
  interview: "面试",
  report: "本场报告",
} as const;

export const homeCopy = {
  eyebrow: "从简历开始",
  projectTitle: "先把项目说清楚。",
  projectDescription: "上传简历后，我们会整理出一个相关项目。内容可以修改，确认无误后再开始面试。",
  uploadTitle: "上传简历",
  uploadHint: "支持 PDF 和 DOCX，解析后可以继续修改。",
  projectSection: "项目内容",
  projectFields: {
    project_name: "项目名称",
    background_goal: "要解决的问题",
    tech_stack: "技术栈",
    responsibilities: "你负责的部分",
    core_solution: "主要方案",
    engineering_challenges: "遇到的难点",
    failure_improvements: "出问题后怎么改",
    quantified_results: "最终结果",
  },
  analyze: "帮我整理这个项目",
  analyzeAgain: "重新整理",
  confirm: "确认项目，开始面试",
} as const;

export const interviewCopy = {
  progress: "答题进度",
  questionOf: (current: number, total: number) => `第 ${current} 题，共 ${total} 题`,
  answerHelp: "先按真实面试回答。全部答完后，系统会一次生成本场报告。",
  noHint: "本题不提供提示",
  saveAndContinue: "保存并继续",
  unknown: "我不知道",
  skip: "跳过",
  completedTitle: "这场面试已经完成。",
  generatingTitle: "正在生成本场报告。",
} as const;

export const reportCopy = {
  content: "报告内容",
  feedbackTitle: "看看哪些地方答得好，哪些还可以补充。",
  answerExcerpt: "回答摘录",
  scoreReason: "评分理由",
  scoreExplanation: "评分说明",
  goodAnswers: "回答较好的地方",
  improvements: "可以改进的地方",
  completed: "完成题目",
  goodCount: "回答较好",
  improveCount: "需要加强",
} as const;

export const statusCopy = {
  saved: "回答已经保存。",
  generating: "正在整理回答，请保持页面打开。",
  timeoutTitle: "这次没有拿到评分结果。",
  timeoutReason: "模型服务响应较慢",
  timeoutDescription: "回答已经保存，不需要重新答题。可以直接再试一次，也可以稍后回来。",
  timeoutAction: "重新生成报告",
  backHome: "返回首页",
} as const;
```

Add the test script to `frontend/package.json`:

```json
"test:copy": "node --experimental-strip-types lib/ui-copy.test.ts"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npm run test:copy`

Expected: PASS with exit code 0.

- [ ] **Step 5: Commit**

```bash
git add frontend/lib/ui-copy.ts frontend/lib/ui-copy.test.ts frontend/package.json
git commit -m "feat: add natural UI copy contract"
```

### Task 2: 实现全局视觉基础

**Files:**
- Modify: `frontend/app/globals.css`
- Modify: `frontend/app/layout.tsx`
- Modify: `frontend/tailwind.config.ts`

**Interfaces:**
- Pages consume CSS variables and existing Tailwind color names without changing API calls.
- `RootLayout` exposes the new product title and `lang="zh-CN"`.

- [ ] **Step 1: Write the failing test**

Add a static contract test to `frontend/lib/ui-copy.test.ts` that checks the source stylesheet contains the approved tokens:

```ts
import { readFileSync } from "node:fs";

const css = readFileSync(new URL("../app/globals.css", import.meta.url), "utf8");
for (const token of ["#182438", "#E9EDF2", "#F8FAFB", "#2F57D1", "#FF7043", "prefers-reduced-motion"]) {
  if (!css.includes(token)) throw new Error(`missing visual token: ${token}`);
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm run test:copy`

Expected: FAIL because the current stylesheet still uses the old `#16151f` and `#f6f1e8` foundation and does not define the approved interaction tokens.

- [ ] **Step 3: Write minimal implementation**

Update `globals.css` with the approved system:

```css
:root {
  --color-navy: #182438;
  --color-cool-gray: #e9edf2;
  --color-content: #f8fafb;
  --color-blue: #2f57d1;
  --color-orange: #ff7043;
  --color-line: #aeb8c5;
  --font-display: "Bahnschrift", "Microsoft YaHei UI", sans-serif;
  --font-body: "Segoe UI", "Microsoft YaHei UI", sans-serif;
  --font-mono: "Cascadia Mono", "Consolas", monospace;
}

* { box-sizing: border-box; }

body {
  margin: 0;
  background: var(--color-cool-gray);
  color: var(--color-navy);
  font-family: var(--font-body);
}

button, input, textarea { font: inherit; }
button:focus-visible, input:focus-visible, textarea:focus-visible, a:focus-visible {
  outline: 3px solid var(--color-orange);
  outline-offset: 3px;
}

@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    scroll-behavior: auto !important;
    animation-duration: 0.001ms !important;
    transition-duration: 0.001ms !important;
  }
}
```

Update Tailwind aliases to point to the same tokens and update metadata title to `Echo Offer`.

- [ ] **Step 4: Run test to verify it passes**

Run: `npm run test:copy && npx tsc --noEmit`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/app/globals.css frontend/app/layout.tsx frontend/tailwind.config.ts frontend/lib/ui-copy.test.ts
git commit -m "feat: add signal desk visual foundation"
```

### Task 3: 重做首页为项目准备工作区

**Files:**
- Modify: `frontend/app/page.tsx`
- Modify: `frontend/lib/ui-copy.ts`

**Interfaces:**
- Keep `parseResume`, `analyzeAgentProjectStream`, `createProfile`, and `createSession` calls unchanged.
- Keep existing upload, analysis, editable project fields, error handling, and submit behavior.
- Produce a desktop left progress rail and right project work area, with a mobile stacked layout.

- [ ] **Step 1: Write the failing test**

Extend `frontend/lib/ui-copy.test.ts` to check the home page source uses the shared copy and no forbidden visible wording:

```ts
const homePage = readFileSync(new URL("../app/page.tsx", import.meta.url), "utf8");
for (const token of ["homeCopy", "准备进度", "确认项目，开始面试"]) {
  if (!homePage.includes(token)) throw new Error(`home page missing: ${token}`);
}
for (const token of ["Evidence Rail", "冻结事实", "模型引用证据"]) {
  if (homePage.includes(token)) throw new Error(`home page leaked: ${token}`);
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm run test:copy`

Expected: FAIL because the current page keeps inline copy and internal wording such as `模型引用证据`.

- [ ] **Step 3: Write minimal implementation**

Refactor only the page presentation:

```tsx
import { brandCopy, homeCopy } from "@/lib/ui-copy";

const steps = ["上传简历", "检查项目内容", "开始面试"];

// Keep the existing handlers. Replace the rendered structure with:
// <main className="min-h-screen bg-cool-gray text-navy">
//   <header>Echo Offer / 准备面试</header>
//   <div className="signal-shell">
//     <aside aria-label="准备进度">...</aside>
//     <section>title, upload panel, project fields, analysis questions, submit</section>
//   </div>
// </main>
```

Use the exact approved labels: `上传简历`、`检查项目内容`、`你负责的部分`、`主要方案`、`遇到的难点`、`最终结果`、`帮我整理这个项目` and `确认项目，开始面试`.

Keep AI analysis as an optional action. The analysis progress text should say `正在整理项目内容` or `正在生成问题`, not expose provider or pipeline names. Keep the upload note that complete resume text is sent to SiliconFlow, because that is a factual privacy boundary.

- [ ] **Step 4: Run test to verify it passes**

Run: `npm run test:copy && npx tsc --noEmit`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/app/page.tsx frontend/lib/ui-copy.ts frontend/lib/ui-copy.test.ts
git commit -m "feat: redesign project intake workspace"
```

### Task 4: 重做答题页和完成状态

**Files:**
- Modify: `frontend/app/interview/[id]/page.tsx`
- Modify: `frontend/lib/assessment-flow.ts`
- Modify: `frontend/lib/ui-copy.ts`

**Interfaces:**
- Keep `getSession`, `submitAnswer`, `assessSession`, and report routing unchanged.
- Preserve the one-batch assessment behavior after the final answer.
- Preserve the retry path and saved-answer guarantee.

- [ ] **Step 1: Write the failing test**

Extend `frontend/lib/ui-copy.test.ts` with a source contract:

```ts
const interviewPage = readFileSync(new URL("../app/interview/[id]/page.tsx", import.meta.url), "utf8");
const assessmentFlow = readFileSync(new URL("./assessment-flow.ts", import.meta.url), "utf8");
for (const token of ["interviewCopy", "保存并继续", "本题不提供提示", "答题进度"]) {
  if (!interviewPage.includes(token)) throw new Error(`interview page missing: ${token}`);
}
for (const token of ["Evidence Rail", "Rubric", "请求模型", "校验证据"]) {
  if (interviewPage.includes(token)) throw new Error(`interview page leaked: ${token}`);
  if (assessmentFlow.includes(token)) throw new Error(`assessment flow leaked: ${token}`);
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm run test:copy`

Expected: FAIL because the current page uses inline copy and exposes `请求模型` and `校验证据` in the progress display.

- [ ] **Step 3: Write minimal implementation**

Import `brandCopy` and `interviewCopy`. Replace the values in `frontend/lib/assessment-flow.ts` with the user-facing stages `保存回答`、`整理回答`、`生成报告`，and keep internal state names private if the API needs them. Keep the existing state and functions. Replace the layout with:

```tsx
<main className="min-h-screen bg-content text-navy">
  <header>Echo Offer / 第 {question.order} 题，共 {session.progress.total} 题</header>
  <div className="signal-shell">
    <aside aria-label="答题进度">completed questions, current step, report state</aside>
    <form>category, question, answer textarea, save/unknown/skip actions</form>
  </div>
</main>
```

Use `保存并继续` for the primary action. Use `答题说明` for the side note: `每道回答都会保存。全部答完后，系统会一次生成本场报告。`

For the completed state, show `正在生成本场报告。`, `回答已经保存。`, and `重新生成报告` when assessment is pending or failed. Do not show fake percentages or internal AI stages. The visual indicator may use a short CSS scan line, but it must stop under `prefers-reduced-motion`.

- [ ] **Step 4: Run test to verify it passes**

Run: `npm run test:copy && npx tsc --noEmit`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/app/interview/[id]/page.tsx frontend/lib/assessment-flow.ts frontend/lib/ui-copy.ts frontend/lib/ui-copy.test.ts
git commit -m "feat: redesign interview workspace"
```

### Task 5: 重做报告页和失败恢复文案

**Files:**
- Modify: `frontend/app/report/[id]/page.tsx`
- Modify: `frontend/lib/ui-copy.ts`

**Interfaces:**
- Keep `getReport`, `assessSession`, report retry, level rendering, and status counts unchanged.
- Keep per-question level, answer excerpt, score reason, strengths, gaps, and evidence quality data available.
- Rename only visible labels; do not rename API response properties.

- [ ] **Step 1: Write the failing test**

Extend `frontend/lib/ui-copy.test.ts` with:

```ts
const reportPage = readFileSync(new URL("../app/report/[id]/page.tsx", import.meta.url), "utf8");
for (const token of ["reportCopy", "回答摘录", "评分理由", "本场报告"]) {
  if (!reportPage.includes(token)) throw new Error(`report page missing: ${token}`);
}
for (const token of ["Rubric evidence", "Evidence quality", "Level distribution", "可信边界", "有效证据数"]) {
  if (reportPage.includes(token)) throw new Error(`report page leaked: ${token}`);
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm run test:copy`

Expected: FAIL because the current report page exposes `Rubric 证据`、`可信边界` and `模型说明`.

- [ ] **Step 3: Write minimal implementation**

Import `brandCopy` and `reportCopy`. Keep the data mapping and retry handler. Render:

```tsx
<main className="min-h-screen bg-content text-navy">
  <header>Echo Offer / 本场报告</header>
  <div className="signal-shell">
    <aside aria-label="报告内容">整体情况, 回答较好的地方, 可以改进的地方, 评分说明</aside>
    <section>
      <h1>看看哪些地方答得好，哪些还可以补充。</h1>
      <summary metrics="完成题目 / 回答较好 / 需要加强" />
      <article>回答摘录, 评分 3/4, 评分理由</article>
    </section>
  </div>
</main>
```

Use `评分说明` for the reliability section. Explain in plain Chinese that the report is based on the answers in this session and that unfinished or failed evaluations are not included in the useful result. Keep retry copy as `重新生成报告` and never instruct users to re-answer.

- [ ] **Step 4: Run test to verify it passes**

Run: `npm run test:copy && npx tsc --noEmit`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/app/report/[id]/page.tsx frontend/lib/ui-copy.ts frontend/lib/ui-copy.test.ts
git commit -m "feat: redesign assessment report"
```

### Task 6: 统一响应式细节并做视觉回归

**Files:**
- Modify: `frontend/app/globals.css`
- Modify: `frontend/app/page.tsx`
- Modify: `frontend/app/interview/[id]/page.tsx`
- Modify: `frontend/app/report/[id]/page.tsx`

**Interfaces:**
- No API or data contract changes.
- Desktop and mobile layouts use the same copy and state semantics.

- [ ] **Step 1: Write the failing test**

Add a source-level contract to `frontend/lib/ui-copy.test.ts`:

```ts
for (const path of ["../app/page.tsx", "../app/interview/[id]/page.tsx", "../app/report/[id]/page.tsx"]) {
  const source = readFileSync(new URL(path, import.meta.url), "utf8");
  if (!source.includes("aria-label")) throw new Error(`${path} needs named navigation/work areas`);
}
const css = readFileSync(new URL("../app/globals.css", import.meta.url), "utf8");
if (!css.includes("@media (max-width")) throw new Error("responsive layout contract missing");
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm run test:copy`

Expected: FAIL until all three pages use named work areas and the shared responsive shell.

- [ ] **Step 3: Write minimal implementation**

Add the responsive rules and semantic landmarks:

```css
.signal-shell { display: grid; grid-template-columns: 220px minmax(0, 1fr); }
@media (max-width: 800px) {
  .signal-shell { grid-template-columns: 1fr; }
  .signal-rail { display: flex; overflow-x: auto; }
  .signal-actions { position: sticky; bottom: 0; }
}
```

Check that long Chinese questions wrap, no page has horizontal overflow, bottom actions remain reachable, and the orange focus outline is visible against both backgrounds.

- [ ] **Step 4: Run test to verify it passes**

Run: `npm run test:copy && npx tsc --noEmit && npm run build`

Expected: PASS, with all App Router routes generated successfully.

- [ ] **Step 5: Commit**

```bash
git add frontend/app/globals.css frontend/app/page.tsx frontend/app/interview/[id]/page.tsx frontend/app/report/[id]/page.tsx frontend/lib/ui-copy.test.ts
git commit -m "test: verify responsive signal desk UI"
```

### Task 7: 完成验证并整理本地运行入口

**Files:**
- No new source files.
- Verify: `frontend/lib/ui-copy.test.ts`, all three pages, `frontend/app/globals.css`.

- [ ] **Step 1: Run the full local verification**

Run from the repository root:

```powershell
python -m pytest backend/tests -q
Push-Location frontend
npm run test:copy
npx tsc --noEmit
npm run build
Pop-Location
git diff --check
git status --short --branch
```

Expected: backend tests pass, copy contract passes, TypeScript check passes, production build passes, and only intentionally committed changes remain.

- [ ] **Step 2: Verify local services**

Start or restart the backend and frontend with the existing ports:

```powershell
python -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8010
```

```powershell
$env:NEXT_PUBLIC_API_URL = "http://127.0.0.1:8010"
npm run dev -- --hostname 127.0.0.1 --port 3000
```

Check `http://127.0.0.1:8010/health` returns HTTP 200 and `http://127.0.0.1:3000` returns HTTP 200.

- [ ] **Step 3: Do a visual pass**

Open `http://127.0.0.1:3000` and inspect all three routes at desktop and mobile widths. Confirm:

1. 首页先看到上传简历和项目内容，不需要理解内部术语。
2. 答题页一次只突出当前问题和保存动作。
3. 报告页先显示回答摘录与评分理由，再显示补充信息。
4. 超时后仍能看到回答已保存和重新生成入口。
5. 页面没有渐变、玻璃卡片、无意义图标或装饰性动画。

- [ ] **Step 4: Commit any final verification-only adjustments**

```bash
git add frontend
git commit -m "chore: verify signal desk UI locally"
```
