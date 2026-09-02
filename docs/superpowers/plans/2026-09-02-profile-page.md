# 用户画像页面实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将已有用户画像后端能力接入一个自然、可操作的 `/profile` 前端页面。

**Architecture:** 扩展面试历史摘要返回 `profile_id`，前端用历史记录整理画像选择项，再按选择读取画像摘要和快照；画像页只消费已有结构化接口，建议状态通过现有 PATCH 接口更新。页面沿用当前 Agent Echo 的排版和颜色，但用能力行、建议卡片和时间线表达长期变化，避免通用仪表盘。

**Tech Stack:** FastAPI、SQLAlchemy、SQLite、Next.js App Router、React、TypeScript、现有 CSS token 系统、Node 静态契约测试、pytest。

## Global Constraints

- 本地单用户模式，不引入登录、云端存储或新的数据库表。
- 打开画像页面和切换画像不得调用模型。
- 不显示 0～100 总分或内部评估术语。
- 不推送 GitHub；只保留本地分支和本地提交。
- 保留当前工作区中与本功能无关的未提交改动。

---

### Task 1: 扩展画像入口数据和前端 API 类型

**Files:**
- Modify: `backend/app/schemas.py` (`InterviewHistoryItem`)
- Modify: `backend/app/services.py` (`list_interview_history`)
- Test: `backend/tests/test_interview_history.py`
- Modify: `frontend/lib/api.ts`
- Test: `frontend/lib/profile-page.test.ts`

**Interfaces:**
- `InterviewHistoryItem.profile_id: str | None` 返回该场面试关联的画像 ID。
- `getProfileSummary(profileId: string)` 返回 `ProfileSummary`。
- `getProfileHistory(profileId: string)` 返回 `ProfileSnapshot[]`。
- `updateRecommendationStatus(recommendationId: string, status: RecommendationStatus)` 返回更新后的建议。

- [ ] **Step 1: 写后端失败测试，要求历史摘要返回 profile_id**

在现有历史记录测试中创建关联画像和面试会话，断言返回项包含相同的 `profile_id`。

```python
def test_history_item_exposes_profile_id(client):
    profile = client.post("/api/profile", json={
        "resume_text": "张三\nAgent 工程师\n做过一个检索项目",
        "project": {"name": "检索项目", "background": "内部知识检索", "tech_stack": "Python"},
    }).json()
    session = client.post("/api/sessions", json={"profile_id": profile["profile_id"]}).json()

    item = next(
        entry for entry in client.get("/api/interviews/history").json()
        if entry["session_id"] == session["session_id"]
    )

    assert item["profile_id"] == profile["profile_id"]
```

- [ ] **Step 2: 运行测试确认它先失败**

Run: `python -m pytest backend/tests/test_interview_history.py -q`

Expected: FAIL because the history item does not yet expose `profile_id`.

- [ ] **Step 3: 写最小后端实现**

在 `InterviewHistoryItem` 增加可空 `profile_id` 字段，并在 `list_interview_history` 组装结果时写入 `session.profile_id`。在 `frontend/lib/api.ts` 增加画像摘要、快照、建议状态的精确类型和三个请求函数。

- [ ] **Step 4: 写前端失败契约测试**

新增 `frontend/lib/profile-page.test.ts`，读取画像页面和 API 文件，断言存在画像接口、等级标签、建议状态操作和自然中文文案，同时断言不包含 `0～100`、`冻结事实`、`盲评分器`。

- [ ] **Step 5: 运行前端契约测试确认它先失败**

Run: `npm run test:profile`

Expected: FAIL because the profile page and its API calls do not yet exist.

- [ ] **Step 6: 运行后端和前端针对性测试确认通过**

Run: `python -m pytest backend/tests/test_interview_history.py -q` and `npm run test:profile`

Expected: PASS。

- [ ] **Step 7: Commit**

```bash
git add backend/app/schemas.py backend/app/services.py backend/tests/test_interview_history.py frontend/lib/api.ts frontend/lib/profile-page.test.ts frontend/package.json
git commit -m "feat: expose profile history data"
```

### Task 2: 实现用户画像页面和画像选择

**Files:**
- Create: `frontend/app/profile/page.tsx`
- Modify: `frontend/app/history/page.tsx`
- Modify: `frontend/app/page.tsx`
- Modify: `frontend/app/console/page.tsx`
- Test: `frontend/lib/profile-page.test.ts`

**Interfaces:**
- `/profile` 读取历史记录，按 `profile_id` 聚合画像选项。
- 画像选择后读取 `getProfileSummary(profileId)` 和 `getProfileHistory(profileId)`。
- 历史卡片链接到 `/profile?profile_id={profile_id}`；没有画像 ID 时不显示链接。

- [ ] **Step 1: 写页面结构失败契约**

扩展静态测试，要求出现 `/profile`、`getInterviewHistory`、`getProfileSummary`、`getProfileHistory`、`技能`、`学习建议`、`最近变化`、加载和错误处理文案。

- [ ] **Step 2: 运行测试确认它先失败**

Run: `npm run test:profile`

Expected: FAIL because the route and navigation do not yet exist。

- [ ] **Step 3: 实现最小页面**

创建客户端页面：加载历史记录并按画像 ID 去重；无记录时显示开始面试入口；有记录时默认选择最近画像，也读取 `window.location.search` 中的 `profile_id`；并行请求摘要与快照；将技能显示为五格等级点、目标等级、有效回答次数和自然趋势文案；将推荐显示为原因、行动步骤和完成标准。

- [ ] **Step 4: 接入导航和历史卡片入口**

在首页、模型设置页、历史页面导航加入“用户画像”；历史卡片增加“查看能力概况”链接，并保留原有查看结果、继续面试和删除操作。

- [ ] **Step 5: 运行针对性测试确认通过**

Run: `npm run test:profile && npm run test:ui && npm run test:history`

Expected: PASS。

- [ ] **Step 6: Commit**

```bash
git add frontend/app/profile/page.tsx frontend/app/history/page.tsx frontend/app/page.tsx frontend/app/console/page.tsx frontend/lib/profile-page.test.ts
git commit -m "feat: add profile overview page"
```

### Task 3: 增加建议状态操作和页面样式

**Files:**
- Modify: `frontend/app/profile/page.tsx`
- Modify: `frontend/app/globals.css`
- Test: `frontend/lib/profile-page.test.ts`

**Interfaces:**
- 建议状态使用后端支持的 `recommended | in_progress | completed | dismissed`。
- 状态更新成功后保留当前页面和其它建议，只更新被操作项。
- 状态更新失败时显示明确错误，保留原状态。

- [ ] **Step 1: 写状态操作失败契约**

在静态测试中断言页面调用 `updateRecommendationStatus`，包含四种后端状态名，并有“开始练习”“已完成”“暂时放一放”等用户可理解的操作文案。

- [ ] **Step 2: 运行测试确认它先失败**

Run: `npm run test:profile`

Expected: FAIL because the page has not wired the recommendation mutation。

- [ ] **Step 3: 实现状态操作和样式**

增加建议卡片操作按钮、局部忙碌状态和错误提示；增加方向选择、能力行、等级点、趋势标记、建议卡片、时间线和移动端布局样式。使用现有 `mint-*` token，不新增渐变、霓虹色或通用 dashboard 图表。

- [ ] **Step 4: 运行测试确认通过**

Run: `npm run test:profile && npm run test:ui`

Expected: PASS。

- [ ] **Step 5: Commit**

```bash
git add frontend/app/profile/page.tsx frontend/app/globals.css frontend/lib/profile-page.test.ts
git commit -m "feat: add profile learning actions"
```

### Task 4: 文档和全量验证

**Files:**
- Modify: `README.md`

- [ ] **Step 1: 更新本地使用说明**

补充 `/profile` 路径、画像来源于有效面试结果、建议状态可在页面更新，并明确页面不会因为查看或切换画像而调用模型。

- [ ] **Step 2: 运行完整验证**

Run: `python -m pytest backend/tests -q`、`npm test`、`npm run build`、`git diff --check`。

Expected: 后端测试、前端测试和生产构建全部成功；`git diff --check` 无错误。

- [ ] **Step 3: 检查敏感信息和工作区**

运行 `rg --hidden --glob '!**/.git/**' --glob '!frontend/node_modules/**' --glob '!frontend/.next/**' --pcre2 -l 'sk-[A-Za-z0-9]{20,}' .`，只输出文件名，不输出匹配内容；检查 `git status --short`，确认此前无关改动仍保留。

- [ ] **Step 4: Commit**

```bash
git add README.md
git commit -m "docs: document profile page"
```
