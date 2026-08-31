# 简历项目分析 SSE 流式输出设计

## 1. 目标与范围

本次只为“上传简历后进行 Agent 项目分析”增加 SSE 流式进度输出，不修改答题评分逻辑。

用户在网页端点击 AI 分析后，可以立即看到处理阶段；模型返回并通过校验后，前端一次性接收完整项目分析结果和三道面试题。

本次不做模型 token 逐字展示，也不改变现有普通分析接口。普通接口继续作为兼容和故障回退路径。

## 2. 接口设计

新增接口：

```text
POST /api/resumes/{resume_id}/agent-project-analysis/stream
Content-Type: application/json
Accept: text/event-stream
```

请求体与现有接口保持一致：

```json
{
  "resume_text": "完整简历文本"
}
```

响应使用 `text/event-stream`，每个事件以空行分隔。响应头设置 `Cache-Control: no-cache` 和 `X-Accel-Buffering: no`，避免代理缓存事件。

现有接口仍保留：

```text
POST /api/resumes/{resume_id}/agent-project-analysis
```

## 3. SSE 事件协议

### 3.1 阶段事件

```text
event: stage
data: {"stage":"received","message":"已接收简历"}
```

阶段值固定为：

- `received`：请求已接收并完成基本校验
- `analyzing`：正在调用模型分析项目
- `validating`：正在校验模型 JSON 和简历证据
- `completed`：结果已保存

### 3.2 心跳事件

模型调用期间每 10 秒发送一次：

```text
event: heartbeat
data: {"stage":"analyzing"}
```

心跳只用于保持连接和更新前端状态，不包含模型中间思考内容。

### 3.3 完整结果事件

模型响应完成、JSON 归一化、证据校验和数据库保存全部成功后，发送：

```text
event: result
data: {"analysis_id":"...","resume_id":"...","status":"draft", "project":{}, "questions":[]}
```

`data` 使用现有 `AgentProjectAnalysisResponseEnvelope` 的完整结构。前端只在收到该事件后更新分析结果，不渲染不完整 JSON。

### 3.4 完成事件

```text
event: done
data: {"status":"completed"}
```

`done` 必须出现在 `result` 之后。

### 3.5 错误事件

```text
event: error
data: {"code":"provider_timeout","message":"模型请求超时"}
```

错误代码沿用现有模型服务错误代码。发生错误时，后端把分析记录标记为 `failed`，发送 `error` 后结束流，不发送 `result` 或 `done`。

## 4. 后端数据流

1. 路由校验简历 ID、文本长度和当前用户归属。
2. 发送 `received` 事件。
3. 创建分析记录，发送 `analyzing` 事件。
4. 将同步模型调用放入后台线程，异步生成器在等待期间发送心跳。
5. 模型返回后执行现有 JSON 归一化和简历证据逐字校验，发送 `validating` 事件。
6. 校验成功后提交分析记录，发送 `result` 和 `done`。
7. 模型超时、连接失败、格式异常或证据无效时回滚/标记失败并发送 `error`。

数据库只保存通过完整校验的分析结果；流式输出不会降低现有证据校验要求。

## 5. 前端数据流

前端使用 `fetch` 发送 POST 请求并读取 `ReadableStream`，不使用原生 `EventSource`，因为请求需要携带 JSON body。

前端状态增加当前分析阶段：

- 点击分析后显示“已接收简历”
- 收到 `analyzing` 后显示“正在分析项目”
- 收到心跳时保持加载状态
- 收到 `validating` 后显示“正在校验证据”
- 收到 `result` 后填充项目字段和三道题
- 收到 `error` 后显示错误信息并允许重新分析

连接结束但没有收到 `done` 时，前端显示“分析连接中断，请重试”。

## 6. 兼容性与错误处理

- 普通分析接口保持原行为，便于 API 调试和 SSE 不可用时回退。
- SSE 响应开始后无法再修改 HTTP 状态码，因此业务错误统一通过 `error` 事件表达。
- 不把 API Key 返回到前端或写入 SSE 数据。
- 不向前端发送模型的 `reasoning_content`，避免泄露内部推理和增加传输负担。
- 关闭浏览器连接后，服务端停止后续事件发送；正在执行的上游请求仍受已有超时限制。

## 7. 测试计划

后端测试：

- 正常事件顺序为 `stage(received)`、`stage(analyzing)`、`stage(validating)`、`result`、`done`。
- 心跳事件可以在模型等待期间产生。
- 返回结果保持完整分析响应结构。
- 模型超时、格式异常、证据无效时发送 `error`，且不发送 `result`。
- 现有普通接口和既有测试继续通过。

前端验证：

- TypeScript 类型检查和生产构建通过。
- 页面可以显示分析阶段并在最终结果到达后填充分析内容。
- 刷新或重新分析时清理旧的流状态。

