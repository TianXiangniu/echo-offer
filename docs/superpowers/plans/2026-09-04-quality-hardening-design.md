# 评分可信与练习闭环强化设计（Quality Hardening Design N1–N6）

> **文档性质：** 总体设计文档，覆盖六项改进（N1–N6）。每个模块动工前按惯例拆成独立 implementation plan。
>
> **实施状态（2026-09-04）：** N1–N6 已全部实现并通过全量回归（后端 pytest 194 项、前端 tsc + 契约测试）。与本文的两处偏差：N4 的追问链终结（预算耗尽/达到轮次上限/模型收束）统一返回 `followup: null`，waived 记录仅作幂等记账；N2 的自动重评只在复核与评分分歧 ≥2 级时触发一次且不级联，重评后仍分歧则标 `disputed`。金标集首版 21 条已入库（`backend/tests/golden/answers.jsonl`），校准脚本 `scripts/eval_scorer.py`（`--provider fake` 冒烟 / 默认真实调用）。
>
> **前置：** 承接《2026-09-04-practicality-optimization-design.md》（M0–M5，已实施）。本文解决 M 系列落地后遗留的六个问题：画像刷分、评分语义校验缺位、报告理由静态化、追问只有一轮且无人设、模型成本翻倍无开关、题库覆盖空白。

**优先级路线图：**

| 模块 | 内容 | 优先级 | 预估 |
|---|---|---|---|
| N1 | 画像样本来源权重（修复刷分） | P0 | 半天 |
| N5 | 追问/反馈开关 + token 用量记录 | P0 | 半天+半天 |
| N3 | 报告评分理由个性化（模型 commentary） | P1 | 半天 |
| N4 | 追问链（每题 2 轮）+ 面试官人设 | P1 | 1–1.5 天 |
| N6 | 题库扩展（系统设计/手写代码/行为题 + 实战槽） | P2 | 1–2 天 |
| N2 | 评分语义校验 verifier + 金标集 | P2 | 1–2 天 |

**全局约束（沿用 M 系列并新增）：**

- 评分器职责单一：人设、语气、追问上下文**绝不进入评分 prompt**；评分不读取练习反馈与画像。
- 首答与追问回答不可变语义不变；所有新表/列走 Alembic 迁移；提交只保留本地分支。
- 所有开关关闭时的行为是"不调用模型、返回空结果"，而不是报错。

---

## N1 — 画像样本来源权重（修复刷分）

### 问题

画像按知识点取最近 5 个样本、按近度加权（5→1），drill 会话的评分与正式面试**完全等价**：用户对同一薄弱点反复开 drill，等级被练习分数刷高，"练了"被当成了"会了"。

### 设计

样本有效权重 = 近度权重（5→1，现状不变）× 来源权重：

```python
KIND_WEIGHTS = {
    "interview": 1.0,      # 正式面试：完整证据链
    "drill": 0.5,          # 练习：刚练完的题，分数虚高
    "verification": 1.2,   # 延迟验证：隔 3 天还能答出来，掌握度最强证据
}
```

- 等级聚合、置信度、`valid_sample_count`、趋势全部沿用现有公式，只把输入权重换成有效权重。
- verification 权重 > 1 的含义：验证通过是升级的正路，drill 只是定位手段——把"验证"从仪式感变成真正驱动等级的机制。
- 无需新表：`session_kind` 已存在，`profile_engine` 组装 session_samples 时带上即可。

### 落点

- Modify: `backend/app/profile_engine.py`（样本组装处带 session_kind，乘 KIND_WEIGHTS）。
- Modify: `backend/tests/test_profile_engine.py`。

### 验收

- 初始等级 2（正式面试样本）后，连续 3 次 drill 4 分样本，聚合等级仍 < 4。
- 一次 verification 4 分样本能显著抬升等级（权重 1.2 生效）。
-存量 interview 会话行为不变（权重 1.0 回归现状）。

---

## N5 — 追问/反馈开关 + token 用量记录

### 问题

每题提交 = 追问决策 1 次 + 练习反馈 1 次，一场面试的模型调用从约 3 次涨到 19 次，且用户无法关闭任何一项、也看不到消耗。

### 设计

**开关**：`model_settings` 加两列 `followup_enabled`、`practice_feedback_enabled`（Boolean，默认 True）。console 表单加两个开关，`ModelSettingsUpdate/Response` 同步字段。

- 关闭时 `decide` 返回 `{followup: null}`、feedback 返回 `{feedback: null}`，**不调用模型**；前端现有 null 处理天然兼容。
- 追问被关闭时，`get_session_view` 的追问恢复逻辑不受影响（永远查不到 pending）。

**用量记录**：provider 在每次模型响应后解析 `usage`（prompt/completion tokens），挂在 `self.last_usage`；调用方在调用后立即读取并写入 `OperationJob.raw_response_json`（批量评分）、followup/feedback 行为不单独建表，仅累计到会话对应的最近 job（可选项，先只做批量评分——它是大头）。

> 已知取舍：`app.state.*_provider` 是共享实例，并发请求下 `last_usage` 有竞态。本地单用户工具可接受，代码加注释说明；未来多用户化时改为 per-request provider 或返回值携带。

### 落点

- 迁移 0010：model_settings 两列。
- Modify: `models.py`、`model_settings.py`、`schemas.py`、`main.py`（decide/feedback 路由前置检查）、`followup_flow.py`、`feedback_flow.py`、`providers.py`（usage 解析）、`assessment_flow.py`（写 job）、console 前端表单。
- Modify: `backend/tests/test_model_settings.py`、`test_settings_api.py`、`test_followup.py`。

### 验收

- 两开关关闭时，fake provider 的 `decide_calls` / `feedback_calls` 均为 0，接口返回 200 + null。
- 一场批量评分后 `GET /api/jobs/{id}` 的 raw_response_json 含 usage 字段。
- console 契约测试覆盖两个开关的文案与保存。

---

## N3 — 报告评分理由个性化

### 问题

报告页每题的"评分理由"是前端按等级数字套的静态文案，与用户实际回答无关。

### 设计

- 批量评分输出每个 case 增加可选字段 `comment`：一句话（≤80 字符）说明为什么是这个等级，必须落到该回答的具体内容。
- 程序校验：非字符串/超长 → 截断或置空，**缺失容忍**（不因此 invalid）。
- 迁移 0011：`assessment_runs.commentary` TEXT 可空。显式"不知道"的题用程序文案"这题选择了直接说不知道"。
- 报告接口把 commentary 带进每题条目；前端有则替换静态理由，无则回退 `reasonForLevel`。

### 落点

- Modify: `providers.py`（prompt + 解析）、`assessment_flow.py`（持久化）、迁移 0011、`reporting_flow.py`、`schemas.py`、报告页 + 契约测试。

### 验收

- 模型缺省 comment 时评分流程不受影响（回归现有用例）。
- 报告接口携带 commentary；前端契约测试断言"优先展示个性化理由"。

---

## N4 — 追问链 + 面试官人设

### 问题

每题最多 1 次追问，练不到"被连挖两层"；追问决策无面试官姿态，所有追问都是礼貌 probe。

### 设计

**追问链**（数据模型已预留 `round`）：

- 每题最多 **2 轮**（`FOLLOWUP_MAX_ROUNDS = 2`），全场预算 4 次不变（一条链消耗 2 次）。
- `decide` 语义从"每题一次幂等"改为"返回该题下一个待答追问"：
  1. 该题存在 pending 追问 → 原样返回（幂等）。
  2. 已答轮数 r：r ≥ 2 或预算耗尽 → 写入 `status=waived, round=r+1` 的终结记录并返回 null（后续重复 decide 命中记录，不再调模型）。
  3. 否则调用决策模型，上下文新增 `previous_followups`（已答追问的问与答），prompt 增加第二层追问指引："回答了追问但仍有含糊、矛盾或值得再挖的点时，可继续追问一次；已经清楚则收束。"
- 新追问落库 `round = 已答轮数 + 1`；预算每轮 +1。
- 前端：`handleFollowupSubmit` 成功后再调一次 decide，pending 即渲染下一张追问卡；现有 pending 恢复逻辑兼容 round 2，无需改数据结构。

**人设**：三档预设 `gentle / standard / pressure`，存 `model_settings.persona`（console 下拉，默认 standard）。只改追问决策与练习反馈的 system prompt 语气（压力档：抓矛盾、质疑数字、短句逼问），**评分 prompt 永远无人设**。

### 落点

- Modify: `followup_flow.py`（round 化 decide）、`providers.py`（PERSONA_PROMPTS + 决策上下文）、`feedback_flow.py`（语气）、迁移 0010（persona 与 N5 开关同批）、console。
- Modify: `test_followup.py`（链式用例、预算共享用例、人设 prompt 断言）。

### 验收

- 决策序列 [True, True]：第一轮追问答完后 decide 产出 round=2 追问，预算从 0 变 2。
- r=2 后 decide 返回 null 且不再调模型（终结记录命中）。
- 全场预算 4 仍为硬上限（链消耗 2）。
- persona=pressure 时决策 prompt 含压力档文案；评分 prompt 不受 persona 影响（断言两个 prompt 内容）。

---

## N6 — 题库扩展：系统设计 / 手写代码 / 行为题 + 实战槽

### 问题

10 个知识点偏应用问答；面试权重很高的系统设计、手写代码、行为协作三类空白；行为题套通用 criterion 别扭。

### 设计

**新增 5 个知识点**（各 2 道模板题，沿用现有平行题机制）：

| knowledge_point_id | 形态 | category | Rubric 倾斜 |
|---|---|---|---|
| `design.agent_platform` | 系统设计：高并发 Agent 平台 | design | engineering 1.5 |
| `design.rag_system` | 系统设计：日百万级 RAG | design | engineering 1.5 |
| `coding.write_tool_loop` | 手写代码：文字写带校验+重试+退避的工具调用循环 | coding | correctness 1.5 |
| `behavioral.project_conflict` | 行为题：项目分歧 | behavioral | criterion 覆写 |
| `behavioral.failure_story` | 行为题：线上事故复盘 | behavioral | criterion 覆写 |

**机制改动 1 — 模板级 criterion 覆写**：`QuestionTemplate` 加可选 `criteria_override: tuple[tuple[str, str], ...]`，`build_rubric` 在 DEFAULT_CRITERIA 基础上按 rubric_id 替换 criterion 文本。行为题示例：叙述真实具体 / 讲清当时思考过程 / 有具体情境与角色 / 有反思与后续改进。覆写随 Rubric 快照冻结，评分链路无感知。

**机制改动 2 — 实战槽**：rng 抽题时槽位布局改为「1 锚题 + 2 通用 + 1 锚题 + 1 实战」：最后一个固定槽固定从 `{design.*, coding.*, behavioral.*}` 知识点轮换抽取（排除本场已用知识点），保证每场必考一个非问答型考点。默认（无 rng）布局保持原 5 题不变，兼容存量测试。

**前端**：面试页 `categoryLabels` 加 `design: "设计题"`、`behavioral: "行为题"`、`coding: "代码题"`；报告页 `knowledgePointLabels` 补 5 个中文标签；契约测试同步。

**练习闭环兼容**：新知识点自动进入 `QUESTION_TEMPLATES`，drill/verification 与画像聚合无需改动；N2 金标集必须覆盖新题型（手写代码题评分边界最模糊，优先攒标注）。

### 落点

- Modify: `question_bank.py`（题池、criteria_override、实战槽）、`rubrics.py`（build_rubric 支持覆写）、`practice_flow.py`（无改动或仅常量）、面试页/报告页 + 契约测试。
- Modify: `test_question_bank.py`、`test_api.py`、`test_practice_loop.py`。

### 验收

- rng 抽题时最后固定槽必为实战类知识点，且与同场其他知识点不重复。
- 行为题 Rubric 快照的 criterion 为覆写文本；非行为题仍为默认文本。
- 默认布局回归不变（现有 test_question_bank 默认用例不修改断言仍通过）。
- 端到端：实战题从出题、作答、评分到画像聚合跑通（fake provider）。

---

## N2 — 评分语义校验 verifier + 金标集

### 问题

证据校验只验"逐字命中 + 哈希"，不防"引用真实存在但与 Rubric 项无关"或"引用不支持该等级"；单评审无复核；评分质量没有校准基准。

### 设计

**验证 pass**（不替换评分器，在其后追加一道工序）：

1. `AssessmentBatch` 流程新增 `verifying` 阶段（OperationJob 事件机制现成）：把每个 case 的「rubric_id + criterion + 引用片段 + 等级 + 回答」批量发给 verifier 模型，输出 JSON：

```json
{"items": [{"rubric_id": "...", "quote_relevant": true, "level_supported": true, "suggested_level": null}]}
```

2. 分歧处理规则（程序侧强制）：
   - `quote_relevant=false` → 观察项按现有 `invalid_evidence` 路径置 invalid，run 降级。
   - `level_supported=false` 且 `|suggested_level - level| >= 2` → 对该 case 独立重评一次（不带复核意见，保持盲评）→ 重评结果为准；重评后仍差 ≥2 → `AssessmentRun.status = "disputed"`（新状态值），报告按 partial 展示并允许重评。
   - 其余 → 采纳原结果。
3. verifier 输出不写分数进正式观察，只影响 run 状态与重评触发。

**prompt_version**：评分/verifier prompt 常量各带版本号（如 `assess-v2`），`_create_batch_job` 写入 `OperationJob.prompt_version`——该字段已存在但从未赋值。

**金标集**：`backend/tests/golden/answers.jsonl`（每条：知识点、题目、回答、人工标注的各 rubric 等级），`scripts/eval_scorer.py` 用真实 provider 跑分，输出每个 rubric_id 的 MAE 与 disputed 率。手动运行（依赖 API key，不进 CI）。起步规模：每个知识点 2–3 条 × 0–4 级覆盖，20–30 条即可暴露模型偏见；N6 新题型优先攒标注。**规则：任何评分 prompt 变更，先跑金标集对比版本 MAE 再上线。**

### 落点

- Modify: `assessment_flow.py`（verifying 阶段 + 分歧处理 + disputed 状态）、`providers.py`（verifier 方法 + PROMPT_VERSION）、`reporting_flow.py`（disputed 状态文案）、前端 `isAssessmentRetryable` 白名单加 `disputed`。
- Create: `scripts/eval_scorer.py`、`backend/tests/golden/answers.jsonl`（首版 20+ 条）。
- Modify: `test_assessment_batch.py`（分歧路径：relevant=false / 等级差≥2 重评 / disputed）。

### 验收

- quote_relevant=false 的 case：run invalid，报告 partial（复用现有降级）。
- 等级差 ≥2：恰好触发一次重评（fake provider 计数断言），重评结果被采纳。
- 重评仍分歧：run.status = "disputed"，报告可重评。
- job 事件序列含 verifying 阶段；prompt_version 落库。
- eval_scorer.py 对金标集输出 MAE 报告（用 fake provider 冒烟测试脚本逻辑）。

---

## 明确不做（本期范围外）

- 语音面试、OCR、多用户/部署、数据导出（维持暂缓结论）。
- 多评审平均（verifier 已提供第二意见，2–3 倍成本不划算）。
- embedding 余弦相似度做语义过滤（阈值不可校准，仅未来可作预过滤器）。
- 画像聚合公式的其他改动（趋势窗口、方向多画像）——只动来源权重。

## 实施顺序

```
N1 刷分修复（半天） → N5 开关+用量（1 天） → N3 报告理由（半天）
→ N4 追问链+人设（1–1.5 天） → N6 题库扩展（1–2 天） → N2 verifier+金标集（1–2 天）
```

N2 放最后：金标集应覆盖 N6 新题型后再建，verifier 才有完整校准基础。每个模块动工前产出独立 implementation plan，并遵守全局约束。
