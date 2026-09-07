# 提示词体系优化 Implementation Plan（prompt-audit-v2）

> **实施状态（2026-09-05）：** 全部完成。评分锚点（assess-v3）+ confidence 语义 + 跑题规则上线；verifier（verify-v2）同步锚点；feedback（feedback-v2）注入参考事实；followup（followup-v2）移除 budget_remaining；wiki（wiki-v2）防重复声明；项目分析（analysis-v3）重构为 JSON 骨架示例 + followup_if_*/difficulty/source_type 指导 + prompt_version 写入 analysis_json；全部提示词版本常量集中在 prompts.py；rubric 项解析宽容化（忽略未知字段）。
> **金标集对比：** 基线 MAE 0.38 → 锚点初版 0.48（1 级锚点过严，0 分题被纠正）→ 微调 1 级锚点后 **0.33**。关键改善：rag 知识点 4/4 全对、0 分"答非所问"从 +3 偏差修正为 ±1、mcp/multi_agent 全对。警告：金标集仅 21 条（单条偏差影响 MAE 0.05），建议扩到 50+ 条再下强结论；1 批评分抖动被鲁棒跳过。

> **背景：** 全量提示词审计发现的核心问题——评分提示词无 0-4 等级锚点（98 分虚高与金标偏严并存的根因）、项目分析提示词无输出结构示例且关键字段（followup_if_* 等）无生成指导、反馈/复核/深讲缺上下文。

**基线：** 改前真实金标 MAE **0.38**（`/tmp/mae_before.log` 留档）。改后必须复跑对比；若 MAE 明显恶化（>0.6）需要回调锚点措辞。

## 改动清单

1. **新建 `backend/app/prompts.py`**：收拢全部系统提示词与版本常量（assess/followup/feedback/verifier/wiki/analysis），新增 `LEVEL_ANCHORS`、`CONFIDENCE_SEMANTICS`、`OFFTOPIC_RULE`。
2. **rubrics.py**：DEFAULT_CRITERIA 行为化（每个维度写清高分与低分行为）。
3. **providers.py**：评分（单/批）prompt 注入锚点 + confidence 语义 + 跑题规则；verifier 注入等级锚点；feedback 注入 reference_facts；followup 移除 budget_remaining；wiki 注入预置 why/pitfalls 防重复。
4. **project_analysis.py**：user prompt 重构（去重、JSON 骨架示例、补 followup_if_*/expected_answer_points/difficulty/source_type 指导）。
5. **skills_flow.py**：feedback/reference 数据接线（rubric_json → reference_facts）；wiki payload 补预置区块。
6. **测试更新 + 全量回归 + 改后 MAE 对比。**

## 约束

- 盲评纪律不变：锚点是"等级标准"，不引入简历/历史信息。
- 旧会话冻结 Rubric 不受影响（criterion 行为化只对新会话生效）。
- 每个提示词模块定义 prompt_version 常量（analysis/followup/feedback 补齐）。
