from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class QuestionSpec:
    order: int
    category: str
    is_anchor: bool
    prompt: str
    knowledge_point_id: str
    rubric_version: str
    signals: tuple[str, ...]


def build_question_specs() -> list[QuestionSpec]:
    return [
        QuestionSpec(
            order=1,
            category="project",
            is_anchor=True,
            prompt="请介绍一个你亲自参与的 Agent 或 RAG 项目：业务目标是什么，你负责了哪部分？",
            knowledge_point_id="project.ownership_and_context",
            rubric_version="alpha-local-v1",
            signals=("业务目标", "个人负责", "项目结果"),
        ),
        QuestionSpec(
            order=2,
            category="agent",
            is_anchor=True,
            prompt="如果 RAG 系统召回了很多无关内容，你会怎样定位并改进问题？",
            knowledge_point_id="rag.retrieval_diagnosis",
            rubric_version="alpha-local-v1",
            signals=("召回", "相关性", "评估"),
        ),
        QuestionSpec(
            order=3,
            category="reliability",
            is_anchor=True,
            prompt="线上 Agent 延迟突然升高时，你会如何拆解排查并降低影响？",
            knowledge_point_id="engineering.latency_diagnosis",
            rubric_version="alpha-local-v1",
            signals=("延迟", "监控", "降级"),
        ),
        QuestionSpec(
            order=4,
            category="project",
            is_anchor=False,
            prompt="结合你的项目，解释一次关键技术方案的取舍，以及为什么没有选择另一个方案。",
            knowledge_point_id="project.architecture_tradeoffs",
            rubric_version="alpha-local-v1",
            signals=("方案", "取舍", "约束"),
        ),
        QuestionSpec(
            order=5,
            category="agent",
            is_anchor=False,
            prompt="如何设计查询改写、混合检索和重排，使 RAG 的召回效果与延迟保持平衡？",
            knowledge_point_id="rag.query_rewrite_and_hybrid_retrieval",
            rubric_version="alpha-local-v1",
            signals=("查询改写", "混合检索", "rerank", "延迟"),
        ),
        QuestionSpec(
            order=6,
            category="agent",
            is_anchor=False,
            prompt="Agent 需要调用多个工具时，你如何处理工具选择、参数校验和失败重试？",
            knowledge_point_id="agent_runtime.tool_calling",
            rubric_version="alpha-local-v1",
            signals=("工具", "参数校验", "重试"),
        ),
        QuestionSpec(
            order=7,
            category="project",
            is_anchor=False,
            prompt="你会怎样验证项目中的技术效果不是偶然样本，而是可以稳定复现的结果？",
            knowledge_point_id="project.evaluation_and_reproducibility",
            rubric_version="alpha-local-v1",
            signals=("指标", "对照", "复现"),
        ),
        QuestionSpec(
            order=8,
            category="reliability",
            is_anchor=False,
            prompt="如果模型输出出现事实错误或敏感内容，你会如何建立防护和回溯机制？",
            knowledge_point_id="engineering.output_safety",
            rubric_version="alpha-local-v1",
            signals=("校验", "防护", "回溯"),
        ),
    ]
