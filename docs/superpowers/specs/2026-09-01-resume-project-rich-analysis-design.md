# 简历项目深度分析设计

## 目标

在不增加用户填写负担的前提下，让 Echo Offer 能从简历中整理出更完整、可核对的项目事实，并生成有上下文关系的项目面试问题。

## 设计原则

1. 用户页面只保留少量核心字段；缺失信息按需询问。
2. 简历原文、用户确认内容、AI 推断和未知信息必须分开保存。
3. AI 不得把推断内容当成项目事实写入问题前提。
4. 项目题与固定题分组，项目题保持连续追问关系。
5. 后台分析结果版本化保存，避免以后修改提示词时覆盖历史记录。

## 用户可见字段

现有八个项目字段继续作为主表单：

- 项目名称
- 项目要解决什么问题
- 你负责的部分
- 你是怎么做的
- 使用了哪些技术
- 哪里最难
- 出过什么问题，怎么改
- 最后有什么结果

前五项为必填，后三项允许为空。AI 分析完成后，只在以下信息会明显影响出题时询问补充：项目周期/阶段、独立或团队完成、个人负责边界、项目规模、部署情况、方案取舍、结果验证方式、已知不足。一次最多展示三个补充问题。

## 后台分析结构

`ResumeProjectAnalysis.analysis_json` 保存版本化分析快照，顶层结构如下：

```json
{
  "schema_version": "project-analysis-v2",
  "project": {
    "core": {
      "project_name": "",
      "background_goal": "",
      "tech_stack": "",
      "responsibilities": "",
      "core_solution": "",
      "engineering_challenges": "",
      "failure_improvements": "",
      "quantified_results": ""
    },
    "context": {},
    "ownership": {},
    "architecture": {},
    "agent_details": {},
    "tradeoffs": {},
    "engineering": {},
    "evaluation": {},
    "evolution": {},
    "limitations": []
  },
  "facts": [],
  "missing_information": [],
  "conflicting_information": [],
  "interview_hooks": [],
  "question_chain": [],
  "selection_reason": "",
  "confidence": 0
}
```

后台字段组：

- `context`：项目类型、领域、周期、阶段、用户、团队、约束和使用场景。
- `ownership`：个人负责模块、设计、实现、测试、部署、运维、协作边界和最大贡献。
- `architecture`：系统边界、输入输出、组件、数据流、接口、存储、缓存、异步和部署。
- `agent_details`：模型、Prompt、上下文、工具调用、记忆、路由、检索、重排、引用和幻觉控制。没有对应能力时保持空值。
- `tradeoffs`：最终方案、备选方案、未选原因、优缺点、适用边界和技术债务。
- `engineering`：延迟、成本、流量、超时、重试、降级、幂等、并发、监控、安全和隐私。
- `evaluation`：指标定义、基线、数据集、样本量、测试方式、离线/线上结果、消融和复现条件。
- `evolution`：初版、迭代、架构变化、废弃方案、当前版本和后续计划。

每个事实对象包含：

```json
{
  "fact_id": "fact-1",
  "field": "ownership.owned_modules",
  "value": "负责检索链路和监控",
  "status": "extracted",
  "source_type": "resume",
  "evidence": [{
    "quote": "负责检索链路和监控",
    "start_offset": 20,
    "end_offset": 31,
    "text_hash": ""
  }],
  "confidence": 0.96,
  "user_confirmed": false
}
```

`status` 取 `extracted`、`confirmed`、`inferred`、`missing`、`conflicting`、`rejected`。只有 `extracted` 和 `confirmed` 可以直接进入问题事实；`inferred` 只能变成开放式确认问题。

## 面试问题结构

项目主问题保持三题，但补充问题生成信息：

```json
{
  "order": 1,
  "question_group": "project",
  "chain_id": "project-main",
  "prompt": "",
  "intent": "确认背景和个人贡献",
  "depends_on": null,
  "source_fields": ["background_goal", "ownership.owned_modules"],
  "source_fact_ids": ["fact-1"],
  "expected_answer_points": [],
  "followup_if_incomplete": "",
  "followup_if_conflicting": "",
  "difficulty": "medium"
}
```

三题顺序固定为：背景与个人贡献、核心方案与取舍、故障/结果/边界。固定题使用不同的 `question_group` 和 `chain_id`，不能与项目题混在一起。

## 校验与兼容

- 保留现有 API 字段，旧的 AI 返回仍可被规范化。
- 新字段均允许为空，不影响已有项目确认流程。
- AI 返回的证据必须是简历原文的字面片段；无法定位的证据标记为无效。
- 没有事实时输出空值并加入 `missing_information`，禁止编造数字、用户量、上线状态和技术组件。
- 保存 `schema_version`、模型名、供应商和时间，支持后续分析版本并存。

## 分阶段实现

第一阶段实现后台结构规范化、问题链 metadata、项目分析提示词和确认时的分析快照保存；不在本次扩大用户表单，不新增独立项目事实表，也不改变评分流程。

