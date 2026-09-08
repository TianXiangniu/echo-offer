# Graph 真实端到端验收与可恢复性增强设计

## 1. 目标

补齐上下文面试 Graph 的最后一段产品闭环：从 API 启动、模型角色降级、回答提交、断点恢复到完成态读取都可验证；模型未配置或暂时不可用时，用户仍能继续一场可审计的面试，不因内部异常看到 500 或异常堆栈。

## 2. 范围与非目标

本阶段只处理 Graph 的运行时可靠性和用户可见降级状态，不新增模型、不增加数据库表、不改变 classic/dialog 流程、不重做评分器，也不加入自动停止服务或后台任务。

## 3. 设计方案

### 3.1 启动上下文

`POST /api/sessions/{id}/graph/start` 在第一次运行前读取已确认的 `ResumeProjectAnalysis`。只将 `extracted/confirmed` 的事实和已确认项目字段写入 Graph State；State 继续禁止简历全文、API Key、ORM 对象、原始模型响应和思维链。没有可用分析快照时使用项目字段生成确定性事实 ID。

### 3.2 角色级降级

每个模型角色独立设置异常边界：

- Planner 解析失败、provider 未配置或 provider 请求失败：使用固定六节点、无事实前提的保底计划。
- Interviewer 失败：使用当前节点的 `opening_question`，并将问题类型标记为 clarification/opening。
- Evidence Verifier 失败：返回 `insufficient`、空 claims、空 coverage、置信度 0；程序按既有追问上限路由，不伪造“已覆盖”。

只有 `ValueError`/`TypeError` 或带 provider error code 的模型错误会进入降级；其他 RuntimeError 继续抛出，保留事务回滚和程序错误可见性。降级只写安全的 `state_updated` 事件：`role`、`status`、`degraded=true`，不包含错误文本、prompt 或响应。

### 3.3 提交、幂等和完成态

恢复接口先按 `client_submission_id` 查询业务回答：同 ID 同内容直接返回当前 Graph State，不再次 invoke Graph、不再次写回答、不再次产生模型调用；同 ID 不同内容仍返回 409。若 checkpoint 已是 `completed`，任何后续 resume 都只返回稳定的完成态，不重新进入 interrupt，也不新增回答记录。

### 3.4 前端反馈

安全公开状态增加可选 `degraded` 标记。面试页在该标记为真时显示“模型暂不可用，已切换保底问题”，不展示异常 code、堆栈或模型内容。刷新页面仍从 `graph/state` 恢复该标记和当前问题；SSE 只继续发送白名单事件。

## 4. 数据流

```text
graph/start
  → hydrate project facts
  → planner (or fallback plan)
  → interviewer (or opening fallback)
  → interrupt
  → graph/resume
      ├─ duplicate submission → public state
      ├─ completed checkpoint → public completed state
      └─ verifier (or insufficient fallback) → deterministic route
```

Graph checkpoint 仍是执行游标，现有 SQLAlchemy 表仍是业务审计来源。模型降级事件和问题/回答事件沿用同一投影事务；投影失败时 checkpoint 保留，下一次 `graph/state` 继续修复投影。

## 5. 测试与验收

1. 上下文测试证明 Graph State 只包含确认事实和必要项目字段。
2. Provider 未配置的 fake agent 能通过 API 启动并返回保底问题，SSE 不包含回答原文或异常文本。
3. 同一提交 ID 重复 resume 不增加 `AnswerAttempt`，也不触发第二次 Graph invoke。
4. 六个节点完成后再次 resume 返回 `completed`，回答数和 checkpoint 不变。
5. 现有 RuntimeError 回滚、SQLite 重启恢复、classic/dialog 回归继续通过。
6. 前端契约测试覆盖 `degraded` 状态文案；后端全量测试和前端测试通过，服务重启后 `/health` 与 `/console` 均为 200。

## 6. 回滚

本阶段不改旧模式和数据库结构；如需回滚，主页仍可创建 `mode="dialog"`，已存在的 Graph 会话和 checkpoint 保持可读。
