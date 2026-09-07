from dataclasses import dataclass, replace
import random as random_module
from collections.abc import Sequence


@dataclass(frozen=True, slots=True)
class QuestionSpec:
    order: int
    category: str
    is_anchor: bool
    prompt: str
    knowledge_point_id: str
    rubric_version: str
    signals: tuple[str, ...]
    reference_facts: tuple[str, ...] = ()
    template_id: str = ""
    rubric_weights: tuple[tuple[str, float], ...] = ()
    criteria_override: tuple[tuple[str, str], ...] = ()
    rubric_snapshot: object | None = None


@dataclass(frozen=True, slots=True)
class ProjectQuestionData:
    prompt: str
    knowledge_point_id: str
    signals: tuple[str, ...]
    reference_facts: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class QuestionTemplate:
    """同一知识点下的一道平行题：考察点相同，切入场景不同。"""

    template_id: str
    prompt: str
    signals: tuple[str, ...]
    reference_facts: tuple[str, ...] = ()
    rubric_weights: tuple[tuple[str, float], ...] = ()
    criteria_override: tuple[tuple[str, str], ...] = ()


def category_for_kp(knowledge_point_id: str) -> str:
    prefix = knowledge_point_id.split(".", 1)[0]
    if prefix in {"engineering", "evals"}:
        return "reliability"
    if prefix in {"design", "coding", "behavioral"}:
        return prefix
    return "agent"


# 实战槽：每场固定题的最后一槽从这些知识点轮换，保证必考一个非问答型考点。
PRACTICAL_KNOWLEDGE_POINTS: tuple[str, ...] = (
    "design.agent_platform",
    "design.rag_system",
    "coding.write_tool_loop",
    "coding.debug_tool_call",
    "behavioral.project_conflict",
    "behavioral.failure_story",
)


# 锚题优先从这些知识点里抽，保证每场至少覆盖一个核心诊断类考点。
ANCHOR_KNOWLEDGE_POINTS: tuple[str, ...] = (
    "rag.retrieval_diagnosis",
    "engineering.latency_diagnosis",
    "mcp.tool_ecosystem",
    "multi_agent.orchestration",
)

# 不传 rng 时的确定性默认布局（与早期版本一致）。
DEFAULT_FIXED_KNOWLEDGE_POINTS: tuple[str, ...] = (
    "rag.retrieval_diagnosis",
    "rag.query_rewrite_and_hybrid_retrieval",
    "agent_runtime.tool_calling",
    "engineering.latency_diagnosis",
    "engineering.output_safety",
)

# 固定题槽位中作为锚题的位置（叠加项目题 1 号锚，全场共 3 个锚题）。
FIXED_ANCHOR_OFFSETS: frozenset[int] = frozenset({0, 3})


def _templates(
    knowledge_point_id: str,
    prompts: Sequence[str],
    signals: tuple[str, ...],
    reference_facts: tuple[str, ...],
    rubric_weights: tuple[tuple[str, float], ...] = (),
    criteria_override: tuple[tuple[str, str], ...] = (),
) -> tuple[QuestionTemplate, ...]:
    return tuple(
        QuestionTemplate(
            template_id=f"{knowledge_point_id}#v{index}",
            prompt=prompt,
            signals=signals,
            reference_facts=reference_facts,
            rubric_weights=rubric_weights,
            criteria_override=criteria_override,
        )
        for index, prompt in enumerate(prompts, start=1)
    )


QUESTION_TEMPLATES: dict[str, tuple[QuestionTemplate, ...]] = {
    "rag.retrieval_diagnosis": _templates(
        "rag.retrieval_diagnosis",
        (
            "如果 RAG 系统召回了很多无关内容，你会怎样定位并改进问题？",
            "上线后用户反馈 RAG 答案经常答非所问，你会怎么系统性地区分是检索的问题还是生成的问题？",
            "假设你的 RAG 在部分文档上召回率很高但答案不相关，你会如何定位并修复这个错位？",
        ),
        ("召回", "相关性", "评估"),
        (
            "先对坏案例分桶：无召回、召回不相关、相关但排序靠后",
            "用标注评测集量化召回率与相关性，先定位再改",
            "区分查询侧（改写、意图）与索引侧（分块、嵌入）问题",
            "改进后用同一评测集回归验证，避免偶然样本",
        ),
    ),
    "rag.query_rewrite_and_hybrid_retrieval": _templates(
        "rag.query_rewrite_and_hybrid_retrieval",
        (
            "如何设计查询改写、混合检索和重排，使 RAG 的召回效果与延迟保持平衡？",
            "多轮对话里用户的追问往往不完整，你会怎样设计查询改写与上下文补全来保证检索质量？",
            "如果关键词检索和向量检索的结果经常不一致，你会怎么设计融合与重排策略，并控制整体延迟？",
        ),
        ("查询改写", "混合检索", "rerank", "延迟"),
        (
            "查询改写解决意图漂移与口语化表达，多轮对话要补全上下文",
            "混合检索里关键词补精确匹配，向量补语义泛化",
            "rerank 用交叉编码器对少量候选精排，控制候选数以平衡延迟",
            "每一级都有延迟预算与降级路径（如高峰跳过 rerank）",
        ),
    ),
    "agent_runtime.tool_calling": _templates(
        "agent_runtime.tool_calling",
        (
            "Agent 需要调用多个工具时，你如何处理工具选择、参数校验和失败重试？",
            "如果模型频繁选错工具或编造不存在的工具，你会从提示词、schema 和运行时三个层面分别怎么改进？",
            "当一个工具调用失败会级联影响整个 Agent 任务时，你会怎样设计工具层的容错：校验、重试、降级？",
        ),
        ("工具", "参数校验", "重试"),
        (
            "依据工具描述与任务让模型选择工具，参数按 schema 校验",
            "校验失败把错误信息回传模型让其修正，而不是直接崩溃",
            "重试要有上限与退避，区分可重试与不可重试错误",
            "对有副作用的工具做幂等或确认保护",
        ),
    ),
    "engineering.latency_diagnosis": _templates(
        "engineering.latency_diagnosis",
        (
            "线上 Agent 延迟突然升高时，你会如何拆解排查并降低影响？",
            "用户抱怨 Agent 响应忽快忽慢，你会如何建立延迟监控和归因方法，把问题定位到具体环节？",
            "高峰期 Agent 的 P95 延迟超标，你会怎样在不明显牺牲答案质量的前提下做分级降级？",
        ),
        ("延迟", "监控", "降级"),
        (
            "先看分段监控定位瓶颈：模型推理、检索、外部工具调用",
            "区分单次慢与整体慢：看 P95 等长尾指标而不是平均值",
            "降级手段：缓存、缩小上下文、跳过非必需步骤",
            "先止血再优化，改进后压测或灰度验证",
        ),
    ),
    "engineering.output_safety": _templates(
        "engineering.output_safety",
        (
            "如果模型输出出现事实错误或敏感内容，你会如何建立防护和回溯机制？",
            "你要为面向外部客户的问答产品设计输出安全方案：幻觉、敏感内容和合规风险分别怎么防护？",
            "一次事故中 Agent 泄漏了不该输出的内部信息，你会如何事后回溯、定位根因并防止复发？",
        ),
        ("校验", "防护", "回溯"),
        (
            "输出侧校验：格式校验、敏感内容过滤、事实一致性检查",
            "答案要能回溯到检索来源，引用与原文可对应",
            "敏感内容有拦截与替换策略，并保留审计日志",
            "输入过滤与输出防护配合，出问题能定位到具体请求",
        ),
    ),
    "mcp.tool_ecosystem": _templates(
        "mcp.tool_ecosystem",
        (
            "如果要给你的 Agent 接入一组外部工具，你会怎样用 MCP 这类协议来设计工具的发现、权限和调用？",
            "Agent 需要同时使用本地工具和第三方 MCP 服务，你会如何设计工具注册、权限控制和故障隔离？",
        ),
        ("MCP", "工具", "schema"),
        (
            "MCP 统一了工具发现与调用的协议，能力按 server 组织",
            "工具权限按 server 或工具粒度控制，敏感操作要确认",
            "外部工具服务不可用时要能隔离与降级，不拖垮主流程",
            "工具 schema 描述质量直接影响模型选择与传参准确性",
        ),
    ),
    "multi_agent.orchestration": _templates(
        "multi_agent.orchestration",
        (
            "什么时候应该把单个 Agent 拆成多智能体？你会怎样设计任务分解、消息传递和失败隔离？",
            "多智能体系统里两个 Agent 的输出互相矛盾时，你会怎样设计仲裁与一致性机制？",
        ),
        ("编排", "任务分解", "隔离"),
        (
            "先判断是否真的需要多智能体：单 Agent 能解决就不拆",
            "任务分解要有清晰接口与状态，避免隐式依赖",
            "单个子 Agent 失败要能隔离，有超时与重试",
            "Agent 间消息要有约定格式，输出冲突时要有仲裁策略",
        ),
    ),
    "evals.observability": _templates(
        "evals.observability",
        (
            "你会怎样为一个上线的 Agent 建立评估体系：离线评测集、线上指标和回归测试分别怎么做？",
            "一次模型升级后 Agent 效果出现波动，你会如何用 trace 和评测数据定位回退的原因？",
        ),
        ("评估", "指标", "回归"),
        (
            "离线评测集覆盖核心场景，每次改动跑回归",
            "线上指标：任务完成率、用户反馈、成本与延迟",
            "trace 记录每一步的输入输出，能回放到具体失败样本",
            "模型或提示词改动先灰度对比，再全量",
        ),
    ),
    "memory.design": _templates(
        "memory.design",
        (
            "Agent 的对话会超出上下文窗口，你会怎样设计短期记忆与长期记忆的存取策略？",
            "如果 Agent 需要跨会话记住用户偏好，你会怎样设计记忆的写入、检索和遗忘机制？",
        ),
        ("记忆", "上下文", "检索"),
        (
            "短期记忆放上下文，长期记忆外置存储按需检索",
            "记忆写入要有筛选，不是所有对话都值得记",
            "检索记忆要兼顾相关性与新鲜度，冲突时以新为准",
            "要有遗忘与清理策略，防止过时记忆污染回答",
        ),
    ),
    "coding.debug_tool_call": _templates(
        "coding.debug_tool_call",
        (
            "下面这段工具调用代码在模型传错参数时直接抛异常终止了，请指出至少两处问题并说明怎么改：\n"
            "```python\n"
            "def call_tool(name, args):\n"
            "    tool = TOOLS[name]\n"
            "    result = tool.run(**args)\n"
            "    return result\n"
            "```",
            "这段重试逻辑会把失败的工具调用无限重试下去，请找出问题并给出至少两处修改：\n"
            "```python\n"
            "while True:\n"
            "    try:\n"
            "        result = tool.run(args)\n"
            "        break\n"
            "    except Exception:\n"
            "        pass\n"
            "```",
        ),
        ("异常", "重试", "校验"),
        (
            "参数要先按 schema 校验，校验失败把错误回传模型修正",
            "重试要有上限与退避，不能无限循环",
            "异常不能被静默吞掉，要记录并区分可重试与不可重试",
            "对有副作用的工具要有幂等保护",
        ),
        # 实战题：找 bug 更看重判断正确性，场景化表达权重降低
        (("correctness", 1.5), ("scenario", 0.5)),
    ),
    "design.agent_platform": _templates(
        "design.agent_platform",
        (
            "请设计一个日均处理百万次调用的企业级 Agent 平台：架构分层、工具接入、隔离与计费怎么做？",
            "如果要把一个内部单机 Agent 原型扩展为支持 500 个团队共用的平台，你会怎么设计多租户与故障隔离？",
        ),
        ("架构", "分层", "隔离"),
        (
            "先分层：入口编排、Agent 运行时、工具网关、模型网关、存储",
            "多租户隔离：配额、并发上限、失败互不影响",
            "工具接入要有 schema 治理与权限审批",
            "成本与延迟要有度量，先立指标再谈优化",
        ),
        (("engineering", 1.5),),
    ),
    "design.rag_system": _templates(
        "design.rag_system",
        (
            "请设计一个面向百万文档、日均十万查询的企业 RAG 系统：索引、检索、评估与更新流程怎么搭？",
            "如果企业文档每天新增上万篇且有权限要求，你会怎么设计索引更新与检索时的权限过滤？",
        ),
        ("架构", "索引", "权限"),
        (
            "索引按更新频率与权限域分片，增量更新不重建全量",
            "检索层权限过滤要在召回前或召回后明确二选一并说清代价",
            "评估集分权限域与文档类型，更新前后跑回归",
            "冷热分层与缓存应对高频重复查询",
        ),
        (("engineering", 1.5),),
    ),
    "coding.write_tool_loop": _templates(
        "coding.write_tool_loop",
        (
            "请用文字写出一段 Agent 工具调用循环的伪代码或 Python：模型决定调哪个工具、校验参数、失败重试（带上限与退避）、把错误回传模型修正。",
            "请写出把一个外部 HTTP API 封装成 Agent 工具的关键代码要点：参数校验、超时、错误分类和幂等保护各放在哪一步？",
        ),
        ("校验", "重试", "回传"),
        (
            "参数先按 schema 校验，校验失败把错误信息回传模型修正",
            "重试有上限与指数退避，只对可重试错误重试",
            "外部调用设超时，超时与失败要区分处理",
            "有副作用的调用要幂等键或确认保护",
        ),
        (("correctness", 1.5),),
    ),
    "behavioral.project_conflict": _templates(
        "behavioral.project_conflict",
        (
            "讲一次你在项目中和同事在技术方案上有分歧的经历：分歧是什么，你怎么处理的，结果如何？",
            "如果产品经理坚持一个你认为技术上走不通的方案，你会怎么沟通和处理？请结合真实经历。",
        ),
        ("分歧", "沟通", "结果"),
        (
            "有具体情境：项目背景、双方立场、分歧焦点",
            "讲清当时的思考与沟通动作，而不是只讲结论",
            "结果如实说，包括没说服对方的情况",
            "有反思：下次会怎么做得不一样",
        ),
        (),
        (
            ("correctness", "叙述真实且具体，能自洽"),
            ("mechanism", "讲清当时的思考与判断过程"),
            ("scenario", "有具体情境、角色和冲突焦点"),
            ("engineering", "有反思与后续改进"),
        ),
    ),
    "behavioral.failure_story": _templates(
        "behavioral.failure_story",
        (
            "讲一次你负责的线上事故或严重 bug：怎么发生的，你怎么定位和恢复的，之后做了什么防止复发？",
            "说一个你判断失误、造成返工或损失的决定：当时的判断依据是什么，后来哪里错了？",
        ),
        ("事故", "定位", "复盘"),
        (
            "事故有具体背景与影响面，不回避自己的责任",
            "定位过程有方法：从现象到根因的推理链",
            "恢复动作分止损与根治两步",
            "防复发措施具体可执行，不是口号",
        ),
        (),
        (
            ("correctness", "叙述真实、具体、可自洽"),
            ("mechanism", "讲清定位与决策的推理过程"),
            ("scenario", "有具体情境、影响面与时间线"),
            ("engineering", "有防复发的具体措施"),
        ),
    ),
}


def _default_project_specs() -> list[QuestionSpec]:
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
            category="project",
            is_anchor=False,
            prompt="结合你的项目，解释一次关键技术方案的取舍，以及为什么没有选择另一个方案。",
            knowledge_point_id="project.architecture_tradeoffs",
            rubric_version="alpha-local-v1",
            signals=("方案", "取舍", "约束"),
        ),
        QuestionSpec(
            order=3,
            category="project",
            is_anchor=False,
            prompt="你会怎样验证项目中的技术效果不是偶然样本，而是可以稳定复现的结果？",
            knowledge_point_id="project.evaluation_and_reproducibility",
            rubric_version="alpha-local-v1",
            signals=("指标", "对照", "复现"),
        ),
    ]


def _custom_project_specs(project_questions: Sequence[ProjectQuestionData]) -> list[QuestionSpec]:
    if len(project_questions) != 3:
        raise ValueError("exactly three project questions are required")
    return [
        QuestionSpec(
            order=index,
            category="project",
            is_anchor=index == 1,
            prompt=question.prompt,
            knowledge_point_id=question.knowledge_point_id,
            rubric_version="alpha-local-v1",
            signals=question.signals,
            reference_facts=question.reference_facts,
        )
        for index, question in enumerate(project_questions, start=1)
    ]


def _fresh_pool(knowledge_point_id: str, excluded_template_ids: set[str] | frozenset[str]):
    pool = QUESTION_TEMPLATES.get(knowledge_point_id, ())
    fresh = [template for template in pool if template.template_id not in excluded_template_ids]
    return pool, fresh


def _select_fixed_specs(
    excluded_template_ids: set[str] | frozenset[str],
    rng: random_module.Random | None,
) -> list[QuestionSpec]:
    if rng is None:
        points = list(DEFAULT_FIXED_KNOWLEDGE_POINTS)
    else:
        anchor_candidates = [
            point
            for point in ANCHOR_KNOWLEDGE_POINTS
            if _fresh_pool(point, excluded_template_ids)[1]
        ] or [
            point for point in ANCHOR_KNOWLEDGE_POINTS if QUESTION_TEMPLATES.get(point)
        ]
        first_anchor = rng.choice(anchor_candidates)
        second_candidates = [point for point in anchor_candidates if point != first_anchor]
        if second_candidates:
            second_anchor = rng.choice(second_candidates)
        else:
            second_anchor = rng.choice(
                [point for point in QUESTION_TEMPLATES if point != first_anchor]
            )
        rest = [
            point
            for point in QUESTION_TEMPLATES
            if point not in {first_anchor, second_anchor}
        ]
        rng.shuffle(rest)
        practical_fresh = [
            point
            for point in PRACTICAL_KNOWLEDGE_POINTS
            if point not in {first_anchor, second_anchor}
            and _fresh_pool(point, excluded_template_ids)[1]
        ]
        practical = rng.choice(
            practical_fresh
            or [point for point in PRACTICAL_KNOWLEDGE_POINTS if point not in {first_anchor, second_anchor}]
        )
        generals = [point for point in rest if point != practical]
        # 锚题位于固定题槽位的第 1 和第 4 位（offset 0 和 3），末槽为实战题
        points = [first_anchor, *generals[:2], second_anchor, practical]

    specs = []
    for offset, knowledge_point_id in enumerate(points):
        pool, fresh = _fresh_pool(knowledge_point_id, excluded_template_ids)
        chosen = rng.choice(fresh) if rng and fresh else (fresh[0] if fresh else pool[0])
        specs.append(
            QuestionSpec(
                order=4 + offset,
                category=category_for_kp(knowledge_point_id),
                is_anchor=offset in FIXED_ANCHOR_OFFSETS,
                prompt=chosen.prompt,
                knowledge_point_id=knowledge_point_id,
                rubric_version="alpha-local-v1",
                signals=chosen.signals,
                reference_facts=chosen.reference_facts,
                template_id=chosen.template_id,
                rubric_weights=chosen.rubric_weights,
                criteria_override=chosen.criteria_override,
            )
        )
    return specs


def build_question_specs(
    project_questions: Sequence[ProjectQuestionData] | None = None,
    *,
    excluded_template_ids: set[str] | None = None,
    rng: random_module.Random | None = None,
) -> list[QuestionSpec]:
    project_specs = (
        _default_project_specs()
        if project_questions is None
        else _custom_project_specs(project_questions)
    )
    fixed_specs = _select_fixed_specs(excluded_template_ids or frozenset(), rng)
    return project_specs + fixed_specs


def build_knowledge_specs(
    *,
    excluded_template_ids: set[str] | None = None,
    rng: random_module.Random | None = None,
) -> list[QuestionSpec]:
    """对话式面试：只生成 5 道知识题（项目部分由对话深挖替代）。"""
    specs = _select_fixed_specs(excluded_template_ids or frozenset(), rng)
    return [replace(spec, order=index) for index, spec in enumerate(specs, start=1)]
