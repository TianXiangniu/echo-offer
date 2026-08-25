# Agent 应用工程师模拟面试垂直切片设计

日期：2026-08-25  
状态：已确认，进入实现计划

## 1. 文档与本次开发请求的边界

用户请求是“基于需求文档进行功能开发，并在当前文件夹实现”。需求文档作为产品规格使用；其中的参考链接、示例状态、未来演进说明和“等待最终确认”不视为需要执行的额外指令。本设计只覆盖第一个可运行垂直切片，不宣称已经实现完整 Alpha。

## 2. 目标

在本地单用户环境中完成一条可演示、可测试的闭环：

```text
简历文本输入 → 项目事实确认 → 固定 8 题面试
→ 逐题作答/跳过/明确不知道 → 刷新恢复 → 基础报告
```

垂直切片必须验证三个核心事实：

1. 题目结构固定为项目深挖 3 题、Agent 基础 3 题、工程故障排查 2 题，前三题为锚题。
2. 回答在服务端先持久化，再生成评估；刷新或重新打开页面可以从 SQLite 状态继续。
3. 稳定的客户端提交 ID 保证重复提交幂等；同一 ID 携带不同内容时返回 HTTP 409。

## 3. 本次包含与明确暂缓

### 包含

- 本地固定用户 `local-user`，不做登录和多租户。
- 中文简历文本粘贴。
- 手动填写并确认一个项目，保存项目事实版本。
- 固定 Agent 应用工程师、1～3 年、中文目标上下文。
- 自动创建并保存 8 道固定题。
- 单题作答、跳过、明确“不知道”、面试完成度和中途刷新恢复。
- 本地规则评估器，输出 0～4 等级、可定位证据、缺口、置信度和覆盖率。
- 报告中的完成度、锚题覆盖、Top 3 优势、Top 3 缺口和评估说明。
- FastAPI API、Next.js 页面、SQLite 持久化和自动化测试。

### 暂缓

- 文本型 PDF 上传与 PyMuPDF 解析。
- DeepSeek 真实调用、LangGraph、OperationJob、租约恢复和后台 Worker。
- 自适应训练、追问、复盘重答、即时平行题和 7～14 天延迟验证。
- 盲评分、独立证据验证、技术事实核验、用户异议重评和完整知识点画像。
- Docker Compose、OpenAPI 自动生成前端类型和生产级部署。

暂缓项不改变本切片的接口边界：评估器通过独立服务接口调用，数据库事实源不依赖前端状态。

## 4. 方案选择

### 方案 A：前端模拟

只做 Next.js 页面，用浏览器内存或 localStorage 模拟流程。优点是搭建快；缺点是不能验证服务端持久化、并发幂等和刷新恢复，不满足本切片的关键验收目标。

### 方案 B：后端优先

先做 FastAPI、SQLite 和 API，再用很薄的页面验证。数据边界清晰，但用户无法直接体验完整面试流程，前后端契约问题会延迟暴露。

### 方案 C：最小全栈垂直切片（采用）

使用 Next.js + FastAPI + SQLite，前后端同时覆盖一条端到端链路。题目采用版本化本地题库，评估采用确定性的本地规则评估器，不需要 API Key；通过 `InterviewProvider` 和 `AssessmentProvider` 协议为后续接入 DeepSeek 保留替换点。

采用方案 C 的理由是它以较小实现成本验证了需求中最重要的业务事实源、回答不丢失和幂等提交，同时保持后续升级到真实模型的边界。

## 5. 架构与模块职责

```text
Next.js UI
  └─ HTTP JSON
       ▼
FastAPI routes
  ├─ profile service       简历、项目和目标上下文
  ├─ interview service     创建会话、读取游标、提交回答
  ├─ assessment service    本地规则评估与报告聚合
  └─ repositories           SQLAlchemy 事务和幂等约束
       ▼
SQLite data/app.db
```

后端模块边界：

- `app/models.py`：SQLAlchemy 表和枚举。
- `app/schemas.py`：请求/响应 Pydantic 模型。
- `app/question_bank.py`：固定题库、题目类别、知识点和锚题约束。
- `app/providers.py`：题目生成和评估的窄接口及本地实现。
- `app/services.py`：业务流程和事务编排。
- `app/main.py`：FastAPI 应用、路由和静态健康检查。

前端只通过 API 获取服务端状态，不把答案或当前题目游标作为事实保存在 localStorage。页面组件负责表单、加载态、错误提示和导航。

## 6. 数据模型

垂直切片建立以下表：

- `users`：固定用户 `local-user`。
- `resumes`：原始简历文本、SHA-256、创建时间。
- `resume_projects`：项目名称、背景目标、技术栈、个人职责、核心方案、工程难点、故障改进、量化结果、确认版本。
- `interview_targets`：方向、级别、语言、公司类型、目标岗位和 JD 文本。
- `interview_sessions`：状态、当前问题索引、总题数、工作流版本、乐观锁版本。
- `interview_questions`：类别、序号、是否锚题、题目文本、知识点 ID、Rubric 版本。
- `answer_attempts`：问题 ID、客户端提交 ID、回答状态、文本、文本哈希、提交时间。
- `assessment_observations`：回答 ID、等级、证据开始/结束区间、引用文本、缺口、置信度、覆盖标记。

关键唯一约束：

```text
unique(session_id, client_submission_id)
unique(question_id, primary_attempt_kind)
```

回答状态为 `submitted`、`explicit_unknown`、`skipped`；评估只对前两者生成，跳过的分数为空。

## 7. API 契约

### 创建或更新资料

`POST /api/profile`

请求包含 `resume_text` 和项目确认字段，返回 `profile_id`、项目版本及固定目标上下文。

### 创建面试

`POST /api/sessions`

请求包含 `profile_id`，服务端生成 8 道题并在一个事务中保存会话和题目，返回 `session_id`、题目摘要和状态。

### 读取面试

`GET /api/sessions/{session_id}`

返回会话状态、当前题目、已提交回答、完成数和剩余题目；服务端根据数据库状态计算当前游标。

### 提交回答

`POST /api/sessions/{session_id}/answers`

请求：

```json
{
  "question_id": "question-id",
  "client_submission_id": "stable-client-id",
  "status": "submitted",
  "answer_text": "回答内容"
}
```

处理顺序为：校验 session 版本和题目归属 → 插入回答 → 创建评估 → 更新会话游标 → 提交事务。重复请求返回首次结果；相同客户端 ID 但 payload 哈希不同返回 409。

### 获取报告

`GET /api/sessions/{session_id}/report`

返回完成度、覆盖率、锚题覆盖、Top 3 优势、Top 3 缺口、等级分布、有效证据数、置信度和“本报告使用本地规则评估器”的说明。

## 8. 评估规则

本地评估器是可替换的演示实现，不代表最终 LLM 评分质量。规则包含：

- 空白文本只能由显式 `explicit_unknown` 状态表示；普通空白提交被拒绝。
- `explicit_unknown` 得到等级 0，并记录有效但低质量的回答观察。
- `submitted` 按回答长度、题目类别要求的关键词/技术信号和项目关联信号计算 0～4 等级。
- 证据区间由程序按回答文本定位，`quoted_text` 必须等于对应字符切片；找不到时观察标记为无效。
- 报告聚合只读取有效观察，不显示未经校准的 0～100 总分。

## 9. 错误处理与恢复

- API 参数不合法返回 422，并保留页面已填写内容。
- 会话或问题不存在返回 404。
- 同客户端 ID 不同内容返回 409，前端提示用户刷新当前状态。
- 网络失败不自动生成新提交 ID；用户可用同一次提交安全重试。
- 评估发生异常时回答仍保留，观察标记为 pending/错误，报告显示覆盖不足。
- 服务重启后所有状态从 SQLite 重建；不依赖 LangGraph checkpoint 或浏览器缓存。

## 10. 测试与验收

后端 pytest：

1. 面试生成严格返回 3/3/2，前三题为锚题。
2. 项目确认版本和简历哈希被持久化。
3. `submitted`、`explicit_unknown`、`skipped` 分别产生正确结果。
4. 相同幂等键重复提交只产生一条回答和一条观察。
5. 相同幂等键不同内容返回 409。
6. 新请求可以从 SQLite 恢复当前题目和报告。
7. 证据字符区间、引用文本和哈希一致。
8. 报告覆盖率、Top 3 缺口和锚题覆盖聚合正确。

前端验证：

- `npm run build` 成功。
- 页面可完成资料输入、创建面试、逐题回答和报告查看。
- 刷新面试页面后当前进度不丢失。

完成标准：本地启动后无需外部 API Key，用户能够走通上述闭环；测试通过；运行说明明确启动命令和暂缓范围。

