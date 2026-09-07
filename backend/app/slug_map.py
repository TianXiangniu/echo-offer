"""题库 new: slug → skill_catalog.id 的收敛映射（唯一数据源）。

migration 0016 与 import_community_questions.py 共用本表。
只映射语义确实贴合的能力项，其余 new: slug 保留为题库自有话题。
"""

SLUG_MAP: dict[str, str] = {
    "new:agent_harness": "agent_runtime.tool_calling",
    "new:agent_skills": "agent_runtime.tool_calling",
    "new:agent_planning": "multi_agent.orchestration",
    "new:agent_basics": "design.agent_platform",
    "new:agent_fundamentals": "design.agent_platform",
    "new:context_engineering": "memory.design",
    "new:agent_guardrails": "engineering.output_safety",
}
