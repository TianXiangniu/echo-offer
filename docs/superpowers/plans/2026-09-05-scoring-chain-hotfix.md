# 评分链热修与实践入口补全 Implementation Plan（#10/#8/#11/#5/#1）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复真实模型走查暴露的评分链缺陷（重评必败、证据匹配失败率 50%），补齐"无薄弱项时的练习入口"，修正两处误导性文案；最终用真实会话 `5c06f2ee...`（3 道 pending 题）做真机回归验收。

**Architecture:** #10 用短序号替代 UUID 作为模型回传的关联 ID（程序侧映射回真 ID，兼容旧格式）；#8 证据定位升级为"精确 → 空白归一 → 引号归一"三层匹配，命中后映射回原文区间（审计语义不变）；#11 复用 drill 抽题逻辑新增随机练习端点；#5 会话视图追问展示改为 pending 优先；#1/#9 为纯文案修正。

**Tech Stack:** FastAPI, SQLAlchemy, Pydantic, SQLite, Next.js 15, TypeScript, pytest, Node 契约测试。

> **实施状态（2026-09-05）：** 全部完成。#10 短序号关联上线（解析器兼容旧 UUID）；#8 三层宽容定位 + 归一化比对上线；真机回归通过——真实会话 `5c06f2ee...` 重评后 `job_status=succeeded`、**score_100=98**、6 题全部有效；#11 `POST /api/practice/drill` + 画像页"随机练一轮"入口上线；#5、#1、invalid 标签文案完成。回归 201 项 pytest + 前端 tsc/契约测试全过。评测 prompt 变更已用 `eval_scorer.py --provider fake` 冒烟；真实 MAE 基线待用户跑。

## Global Constraints

- 不改变盲评分语义：短序号只做关联，不进评分内容；宽容匹配后的 quote 仍必须逐字对应原文某个真实切片。
- 动了评分 prompt（#10）后，用 `scripts/eval_scorer.py --provider fake` 冒烟对比（真实 MAE 基线待用户跑）。
- 修复验证以真实会话 `5c06f2ee-4d3c-4dab-99ec-83a5c210367e` 重评为最终验收。
- 提交只保留本地分支，不 push。

---

## File Map

- Modify: backend/app/providers.py — #10 case_ref 字段与 prompt；#8 引号归一常量
- Modify: backend/app/assessment_engine.py — #10 解析器接受 case_id（兼容旧 UUID）；#8 `_locate_quote` 宽容定位与校验
- Modify: backend/app/assessment_flow.py — #10 case_ref 生成与映射
- Modify: backend/app/practice_flow.py — #11 随机练习（_create_practice_session 参数化）
- Modify: backend/app/main.py — #11 `POST /api/practice/drill`
- Modify: backend/app/followup_flow.py — #5 followups_for_session pending 优先
- Modify: backend/app/schemas.py — #11 请求体
- Modify: frontend/lib/api.ts、frontend/app/profile/page.tsx — #11 随机练按钮
- Modify: frontend/app/report/[id]/page.tsx — invalid 状态文案
- Modify: frontend/app/page.tsx — #1 粘贴路径文案
- Modify/Create: backend/tests/test_assessment_batch.py、test_assessment_engine.py、test_practice_loop.py、test_followup.py — 回归测试

## Interfaces

#10 关联协议（prompt 内）：

```json
{"cases": [{"case_id": "c1", "question": "...", "rubric_items": [...], "reference_facts": [...], "answer": "..."}]}
→ {"items": [{"case_id": "c1", "rubric_items": [...], "comment": "..."}]}
```

解析器规则：优先 `case_id`（映射回 case），兼容旧 `answer_id+question_id`；case 去重按 case 对象身份。

#8 宽容定位：

```python
def _locate_quote(haystack: str, quote: str) -> tuple[int, int] | None:
    """精确 → 空白归一(映射回原文) → 引号归一+空白归一。"""
```

`validate_rubric_observations` 的切片比对同步改为归一化比对（两侧经同一归一化后相等）。

## Tasks

- [ ] 1. #10：case_ref 贯通（Case 字段/prompt/解析器/flow 映射）+ 单测（短 ID 成功、旧 UUID 兼容、ID 错乱报 invalid_batch_case）
- [ ] 2. #8：_locate_quote 三层匹配 + validate 归一化比对 + 单测（空白/换行/引号差异命中，编造引用仍 invalid）
- [ ] 3. 真机回归 A：重启后端，对会话 5c06f2ee 重评 → 3 道 pending 题有效、score_100 非空
- [ ] 4. #11：随机练习端点 + 画像页入口按钮 + 测试
- [ ] 5. #5：followups_for_session pending 优先 + 测试
- [ ] 6. 文案：报告 invalid 标签、首页粘贴路径说明 + 契约测试
- [ ] 7. 全量回归（pytest + tsc + 契约测试）+ 设计文档状态更新
