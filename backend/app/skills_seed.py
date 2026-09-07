"""知识点 Wiki 预置骨架。

三层内容里的"预置层"：def/why/pitfalls 人工短句；
key_points 从题库 reference_facts 程序化导入；examples 从金标集导入。
种子幂等：已生成的深讲（has_deep_dive）不会被覆盖。
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import BASE_DIR
from .models import SkillCatalog, SkillWiki, utc_now
from .question_bank import QUESTION_TEMPLATES

# 人工短句：是什么 / 面试为什么考 / 常见误区。key_points 与 examples 程序化导入。
SEED_CONTENT: dict[str, dict] = {
    "project.ownership_and_context": {
        "definition": "把项目背景、你的职责边界和业务结果一次讲清楚的表达框架。",
        "why": "开场必问题，面试官用它判断项目真实性和你参与的深度。",
        "pitfalls": [
            "只讲'我们做了什么'，不讲'我负责哪一段'，职责边界模糊。",
            "背景只有一句话，面试官无法判断项目规模与复杂度。",
        ],
    },
    "project.architecture_tradeoffs": {
        "definition": "解释关键技术方案为什么这样选、放弃了什么、代价是什么。",
        "why": "取舍能力是区分'用过'和'做过'的核心信号，几乎必问。",
        "pitfalls": [
            "只讲选了什么，不讲放弃了什么——没有对照就没有取舍。",
            "说不出代价。任何方案都有代价，讲不出代价说明没真正落地过。",
        ],
    },
    "project.evaluation_and_reproducibility": {
        "definition": "用评测集、回归和灰度把'效果变好'变成可复现的事实。",
        "why": "区分'感觉效果不错'和'工程化验证'的分水岭，资深面试官必挖。",
        "pitfalls": [
            "拿单个案例当证据，没有分层的评测集和量化指标。",
            "说不出基线：不知道改之前是多少，提升就无从谈起。",
        ],
    },
    "rag.retrieval_diagnosis": {
        "definition": "对召回坏案例分桶定位（无召回/不相关/排序靠后），再针对性改进的方法。",
        "why": "RAG 面试第一大实操题，考排查方法论而不是背概念。",
        "pitfalls": [
            "直接跳到'换 embedding 模型'，没有先分桶定位问题在哪一层。",
            "区分不开查询侧问题（改写、意图）和索引侧问题（分块、嵌入）。",
        ],
    },
    "rag.query_rewrite_and_hybrid_retrieval": {
        "definition": "用查询改写补意图、混合检索补匹配方式、重排补精度，并平衡延迟。",
        "why": "检索优化的标准工程组合拳，考各环节的作用和代价意识。",
        "pitfalls": [
            "堆术语讲不清每个环节解决什么问题：改写管意图漂移，混合管匹配方式，rerank 管精度。",
            "不讲延迟代价——rerank 候选数、缓存、降级路径是必追问点。",
        ],
    },
    "agent_runtime.tool_calling": {
        "definition": "工具选择、参数 schema 校验、失败重试与错误回传修正的运行时闭环。",
        "why": "Agent 岗位核心工程题，考容错设计而不是 happy path。",
        "pitfalls": [
            "校验失败直接崩溃——正确做法是把错误回传模型让它修正。",
            "重试无上限无退避，且不区分可重试（超时/5xx）与不可重试（参数错误）。",
        ],
    },
    "engineering.latency_diagnosis": {
        "definition": "分段监控定位瓶颈（推理/检索/工具），用 P95 看长尾，分级降级止血。",
        "why": "考线上工程素养：先止血再根治，有数据说话。",
        "pitfalls": [
            "用平均值判断延迟问题，忽略 P95 长尾。",
            "只讲优化不讲降级——高峰期首先需要的是止血手段。",
        ],
    },
    "engineering.output_safety": {
        "definition": "输出侧的格式校验、敏感过滤、事实一致性与引用回溯机制。",
        "why": "对外产品必考，考防护分层和出事后的可回溯性。",
        "pitfalls": [
            "只讲输入过滤不讲输出防护，或反之——两层要配合。",
            "说不出审计与回溯：出问题要能定位到具体请求。",
        ],
    },
    "mcp.tool_ecosystem": {
        "definition": "用 MCP 这类协议统一工具的发现、schema、权限与调用组织方式。",
        "why": "2025 年后 Agent 岗位高频新考点，考协议理解与生态集成能力。",
        "pitfalls": [
            "把 MCP 说成单纯的技术栈名词，讲不清它统一了什么、按什么单位组织能力。",
            "不考虑外部服务故障时的隔离与降级。",
        ],
    },
    "multi_agent.orchestration": {
        "definition": "多智能体的任务分解、消息传递约定、失败隔离与输出仲裁。",
        "why": "考架构判断力：什么时候值得拆、拆了怎么管。",
        "pitfalls": [
            "为拆而拆——单 Agent 能解决就不该拆，先说判断标准。",
            "Agent 间消息没有约定格式，输出冲突时没有仲裁策略。",
        ],
    },
    "evals.observability": {
        "definition": "离线评测集 + 线上指标 + trace 回放构成的评估与可观测体系。",
        "why": "Agent 从 demo 到产品的分水岭，越资深的面试官越看重。",
        "pitfalls": [
            "只有离线评测没有线上指标，或反之。",
            "改动全量上线，没有灰度对比和回归把关。",
        ],
    },
    "memory.design": {
        "definition": "短期记忆放上下文、长期记忆外置存储，写入筛选、按相关性检索、有遗忘策略。",
        "why": "长对话和多会话场景的必考设计题。",
        "pitfalls": [
            "所有对话都写入记忆——写入要有筛选，否则记忆变垃圾场。",
            "不考虑记忆冲突和遗忘：过时记忆会污染回答。",
        ],
    },
    "coding.debug_tool_call": {
        "definition": "读有 bug 的工具调用代码，定位校验、重试、异常处理的问题并给出修法。",
        "why": "考真实代码手感：能不能一眼看出'异常被吞''重试无上限'这类生产事故源。",
        "pitfalls": [
            "只说'有问题'说不出问题在哪一行、为什么错。",
            "给出的修法引入新问题，比如重试加了上限但没有退避。",
        ],
    },
    "coding.write_tool_loop": {
        "definition": "动手写'模型决策→参数校验→工具执行→错误回传→带退避重试'的循环骨架。",
        "why": "检验是否真的写过 Agent 运行时，纸上谈兵一眼就会被看穿。",
        "pitfalls": [
            "循环没有终止条件，或重试没有上限与退避。",
            "校验失败后直接抛异常，没有把错误信息回传模型修正。",
        ],
    },
    "design.agent_platform": {
        "definition": "设计多租户 Agent 平台的分层架构：入口编排、运行时、工具网关、模型网关、存储。",
        "why": "高级岗位的系统设计题，考抽象分层与隔离意识。",
        "pitfalls": [
            "上来就画框图不讲分层逻辑和每层职责。",
            "没有多租户隔离和成本度量方案。",
        ],
    },
    "design.rag_system": {
        "definition": "百万文档、每日十万级查询的 RAG 系统：索引分片、权限过滤、增量更新、缓存。",
        "why": "RAG 岗位的天花板题，考规模化和工程化思维。",
        "pitfalls": [
            "权限过滤时机（召回前 vs 后）不明确，或说不出两种选择的代价。",
            "文档更新要全量重建索引——增量更新是基本要求。",
        ],
    },
    "behavioral.project_conflict": {
        "definition": "用真实经历讲清技术分歧的情境、双方立场、你的处理和结果。",
        "why": "行为题几乎必问，考协作成熟度与真实性。",
        "pitfalls": [
            "说'没有遇到过分歧'——不真实且浪费了一次展示机会。",
            "只讲结论不讲过程：当时的思考、沟通动作和反思才是得分点。",
        ],
    },
    "behavioral.failure_story": {
        "definition": "讲一次线上事故或判断失误：影响面、定位过程、止损与根治、防复发。",
        "why": "考复盘能力和坦诚度，回避失败经历的回答会被扣分。",
        "pitfalls": [
            "把责任推给环境或他人，没有自己的反思。",
            "防复发措施是口号（'以后更仔细'）而不是具体机制。",
        ],
    },
}

# 粗糙名称修正（种子时更新 catalog）
NAME_FIXES = {
    "coding.debug_tool_call": "实战找问题",
    "coding.write_tool_loop": "手写工具调用循环",
    "design.agent_platform": "Agent 平台设计",
    "design.rag_system": "RAG 系统设计",
    "multi_agent.orchestration": "多智能体编排",
    "mcp.tool_ecosystem": "MCP 工具生态",
    "evals.observability": "评估与可观测",
    "memory.design": "记忆设计",
}


def _facts_for(knowledge_point_id: str) -> list[str]:
    """从题库模板导入答题要点（同名知识点全部 facts 去重合并）。"""
    facts: list[str] = []
    for template in QUESTION_TEMPLATES.get(knowledge_point_id, ()):
        for fact in template.reference_facts:
            if fact not in facts:
                facts.append(fact)
    return facts


def _examples_for(knowledge_point_id: str) -> list[dict]:
    """从金标集导入示例回答（3/4 级各取一条）。"""
    golden_path = BASE_DIR / "backend" / "tests" / "golden" / "answers.jsonl"
    examples: list[dict] = []
    if not golden_path.exists():
        return examples
    try:
        with open(golden_path, encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                row = json.loads(line)
                if row.get("knowledge_point_id") == knowledge_point_id and row.get("expected_level", 0) >= 3:
                    examples.append({"level": row["expected_level"], "answer": row["answer"]})
    except (OSError, json.JSONDecodeError):
        return examples
    return examples[:2]


SEED_CATEGORY_BY_PREFIX = {
    "project": "项目",
    "rag": "Agent与RAG",
    "agent_runtime": "Agent运行时",
    "mcp": "Agent运行时",
    "multi_agent": "Agent运行时",
    "engineering": "工程实践",
    "evals": "工程实践",
    "memory": "工程实践",
}


def _category_for(knowledge_point_id: str) -> str:
    prefix = knowledge_point_id.split(".", 1)[0]
    return SEED_CATEGORY_BY_PREFIX.get(prefix, "其他")


def ensure_skill_wiki_seeds(db: Session) -> None:
    """幂等种子：补齐 catalog 与骨架、修正名称；已生成的深讲不覆盖。"""
    catalogs = {row.id: row for row in db.scalars(select(SkillCatalog))}
    for knowledge_point_id, content in SEED_CONTENT.items():
        catalog = catalogs.get(knowledge_point_id)
        if catalog is None:
            catalog = SkillCatalog(
                id=knowledge_point_id,
                canonical_name=NAME_FIXES.get(knowledge_point_id, knowledge_point_id),
                category=_category_for(knowledge_point_id),
            )
            db.add(catalog)
            catalogs[knowledge_point_id] = catalog
        if knowledge_point_id in NAME_FIXES:
            catalog.canonical_name = NAME_FIXES[knowledge_point_id]
        catalog.category = catalog.category or _category_for(knowledge_point_id)
        wiki = db.get(SkillWiki, knowledge_point_id)
        if wiki is not None and wiki.has_deep_dive:
            continue
        sections = {
            "definition": content["definition"],
            "why": content["why"],
            "key_points": _facts_for(knowledge_point_id),
            "pitfalls": content["pitfalls"],
            "examples": _examples_for(knowledge_point_id),
        }
        if wiki is None:
            db.add(
                SkillWiki(
                    skill_id=knowledge_point_id,
                    content_json=json.dumps(sections, ensure_ascii=False),
                    source="preset",
                )
            )
        else:
            existing = json.loads(wiki.content_json or "{}")
            existing.update({k: v for k, v in sections.items() if v})
            wiki.content_json = json.dumps(existing, ensure_ascii=False)
            wiki.updated_at = utc_now()
    db.commit()
