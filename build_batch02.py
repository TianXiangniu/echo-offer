# -*- coding: utf-8 -*-
import json

out = []

def q(text, phase, kp):
    return {"text": text, "phase": phase, "knowledge_point": kp}

out.append({
 "note_id": "69bd3f36000000001f007eaf",
 "note_url": "https://www.xiaohongshu.com/explore/69bd3f36000000001f007eaf?xsec_token=AByHRVzRVPE7oMruTybCXzaUl_DPhME7KaTP_sDuW1jRY=&xsec_source=pc_search",
 "questions": [
  q("在多模态Embedding时，你如何平衡文本语义和图像视觉特征在计算相似度时的权重？\n追问1：如果用户搜的是图纸里的某个特定参数，但向量召回了一堆外观相似的零件图，你觉得是什么出了问题？\n追问2：Ragas的Context Precision如果很低，你怎么优化？", "项目", "rag.retrieval_diagnosis"),
  q("你的向量记忆库是如何做去重？\n追问1：如果用户反复说同一件事，你会重复存储还是进行语义合并？\n追问2：使用MCP接入多个测评工具时，如果两个工具对同一个问题回答格式不统一，怎么处理？", "项目", "memory.design"),
  q("当用户提问很含糊时，你的Agent是直接检索知识库，还是先进行反问确认？", "八股", "design.agent_platform"),
  q("如果Agent发现调用的工具报错，如何设计Prompt引导它用报错信息进行重试，而不是直接报错给用户？", "八股", "agent_runtime.tool_calling"),
  q("在长对话中，除了截断，你了解哪些更高效的上下文压缩方法？", "八股", "new:context_engineering"),
  q("在一个多Agent系统里，由LLM做Router分发任务和由固定规则分发相比，各有什么优劣？", "八股", "multi_agent.orchestration"),
  q("在Milvus里，你如何实现BM25和向量检索分数对齐？", "八股", "rag.query_rewrite_and_hybrid_retrieval"),
  q("如果限定只检索某个时间之后的数据，向量数据库里如何实现标量过滤？", "八股", "design.rag_system"),
  q("了解LoRA微调吗？在训练LoRA时，两个参数矩阵分别是如何初始化的？", "八股", "new:llm_finetuning"),
  q("讲讲QLoRA的核心思想", "八股", "new:llm_finetuning"),
  q("如果你微调的是逻辑推理任务，相比于对话任务，你认为秩应该大还是小？", "八股", "new:llm_finetuning"),
  q("在推理阶段，为了消除LoRA带来的额外延迟，你会进行权重Merge吗？", "八股", "new:llm_finetuning"),
  q("在垂域指令微调时，如果模型原本的通用能力下降，你有哪些方法解决？", "八股", "new:llm_finetuning"),
  q("DPO在训练时，为什么不需要像PPO那样在线采样生成回答？DPO数据格式是什么样的？", "八股", "new:llm_finetuning"),
  q("如果并发调用10个不同的Embedding接口，asyncio.gather相比多线程在资源消耗上有什么优势？", "八股", "new:cs_fundamentals"),
  q("手撕：合并K个升序链表", "手撕", "new:algorithm"),
 ]
})

out.append({
 "note_id": "6a78819f000000002500daa7",
 "note_url": "https://www.xiaohongshu.com/explore/6a78819f000000002500daa7?xsec_token=ABOlPrjPayf92CiC7rfROx45NOt9Mjjg-4Ncp1ZUIpz_E=&xsec_source=pc_search",
 "questions": [
  q("为什么这个场景一定要用 Agent，而不是 Workflow？", "八股", "design.agent_platform"),
  q("怎么证明 Agent 比原方案更合适？", "八股", "project.evaluation_and_reproducibility"),
 ]
})

out.append({
 "note_id": "69aa4276000000001b017513",
 "note_url": "https://www.xiaohongshu.com/explore/69aa4276000000001b017513?xsec_token=ABOn6EMkoO1rWFRwcCWei4mKi9bi9MC1oTx9pfXe8oN-A=&xsec_source=pc_search",
 "questions": [
  q("解释LoRA训练方法，以及低秩矩阵更新的原理和优势", "八股", "new:llm_finetuning"),
  q("有了解传统精排方法吗，比如LTR（Learning To Rank）", "八股", "new:cs_fundamentals"),
  q("有了解Qwen3的embedding和Reranker模型吗，结构和特点是什么", "八股", "new:transformer_architecture"),
  q("结合项目讲大模型训练的几个阶段的特点和异同", "项目", "new:llm_finetuning"),
  q("介绍GRPO、PPO、DPO，分别需要几个模型，需要训练的是哪些", "八股", "new:llm_finetuning"),
  q("重要性采样有哪些方法，比如裁剪、KL散度约束、加权归一", "八股", "new:llm_finetuning"),
  q("介绍GSPO的优化点，腾讯最近出的SPO系列算法有关注吗", "八股", "new:llm_finetuning"),
  q("大模型微调过程中，如何避免灾难性遗忘", "八股", "new:llm_finetuning"),
  q("模型蒸馏在大模型落地中的作用和常用方案", "八股", "new:llm_finetuning"),
  q("PyTorch实现GQA（分组查询注意力）", "手撕", "new:transformer_architecture"),
  q("接雨水，要求手写两种方法：暴力法和双指针", "手撕", "new:algorithm"),
  q("经典SQL题：分组统计、排序、条件筛选", "手撕", "new:algorithm"),
 ]
})

out.append({
 "note_id": "69193401000000001b02134a",
 "note_url": "https://www.xiaohongshu.com/explore/69193401000000001b02134a?xsec_token=ABZOIW9wTu_azxc1DPe1m-H3QE1O7ST0yoMXyvwDdxOXk=&xsec_source=pc_search",
 "questions": [
  q("请介绍 Transformer 的结构组成及各部分作用", "八股", "new:transformer_architecture"),
  q("如何降低 Transformer 的计算复杂度？常见的稀疏注意力变体有哪些？", "八股", "new:transformer_architecture"),
  q("LoRA微调的原理是什么？秩 r 的选择会对模型表现产生什么影响？", "八股", "new:llm_finetuning"),
  q("kv cache是什么？为什么能极大地提升推理速度？", "八股", "new:transformer_architecture"),
  q("RAG的完整流程，构建向量检索库时如何处理时间衰减对召回的影响？", "八股", "design.rag_system"),
  q("微调时的训练数据是怎么构建的？如何保证样本多样性和质量？", "项目", "new:llm_finetuning"),
  q("在 RAG+知识图谱的 Agent 系统中，知识图谱更新的机制是怎样的？是怎样保证实时性的？", "八股", "design.rag_system"),
  q("训练 LoRA 模型时，你是如何选择冻结层的？依据是什么？", "项目", "new:llm_finetuning"),
  q("在高并发查询 Agent 系统中，你会如何优化召回和生成阶段的延迟？", "八股", "engineering.latency_diagnosis"),
  q("大规模 Agent 系统在多线程/多进程场景下的资源调度策略如何设计？", "八股", "new:system_design"),
  q("如果你要在 GPU 资源有限的条件下同时提供推理和微调服务，如何做资源分配和任务调度以保证时延和吞吐？", "八股", "new:system_design"),
  q("代码：lc15 三数之和", "手撕", "new:algorithm"),
  q("介绍下self-attention，计算其时间复杂度。", "八股", "new:transformer_architecture"),
  q("为什么要用multi-head attention？", "八股", "new:transformer_architecture"),
  q("PPO的clip机制？在线强化学习和离线强化学习有什么区别？RLHF是哪一种？", "八股", "new:llm_finetuning"),
  q("为什么要用reference model? 为了解决什么问题？", "八股", "new:llm_finetuning"),
  q("如何让多个agent协同工作的？举个具体的协同机制例子。", "八股", "multi_agent.orchestration"),
  q("如果一个agent误判导致策略冲突，如何处理？", "八股", "multi_agent.orchestration"),
  q("有没有用到类似AutoGen或LangChain的框架？为什么选这个框架？", "八股", "design.agent_platform"),
  q("你是怎么设计agent的记忆系统？", "八股", "memory.design"),
  q("长期记忆如何存储？如果历史记录量非常大，怎么优化查询效率？", "八股", "memory.design"),
  q("有没有做记忆衰退，避免旧数据干扰新任务？", "八股", "memory.design"),
  q("你们这种模块堆叠的架构是怎么设计视觉问答模块和动作模块的协同逻辑的？", "八股", "multi_agent.orchestration"),
  q("human feedback是怎么被agent消化吸收的？有没有用rl进行策略更新？", "八股", "multi_agent.orchestration"),
  q("有没有做过模型压缩？比如在车载端或低端设备上的推理加速？", "八股", "new:llm_finetuning"),
  q("如果量化后理解能力下降怎么办？怎么做精度补偿？", "八股", "new:llm_finetuning"),
  q("你怎么处理响应速度与推理精度之间的tradeoff？是先召回再精排，还是单次生成？", "八股", "engineering.latency_diagnosis"),
  q("如果要做电商agent，你会选择哪些模态的信息作为输入？比如文本评论、图像、视频、购买记录？", "八股", "design.agent_platform"),
 ]
})

out.append({
 "note_id": "6a1adb36000000003502ab9f",
 "note_url": "https://www.xiaohongshu.com/explore/6a1adb36000000003502ab9f?xsec_token=ABkNkw8xA2P_3UuJWsx0kFrY-1PeMKp7BmO2ljxMAtSls=&xsec_source=pc_search",
 "questions": [
  q("项目是网上找的还是什么？", "项目", "project.ownership_and_context"),
  q("有实习过吗？", "HR", "new:cs_fundamentals"),
  q("项目中挑战最大的是什么？", "项目", "project.ownership_and_context"),
  q("出现幻觉怎么处理？", "八股", "design.rag_system"),
  q("提示词具体是怎么做？", "八股", "new:prompt_engineering"),
  q("还有其他提示词吗？", "八股", "new:prompt_engineering"),
  q("Agent的短期长期记忆是怎么实现的？", "八股", "memory.design"),
  q("如果让你设计一个Agent要考虑哪些模块？", "八股", "design.agent_platform"),
  q("如果遇到api超时和报错怎么解决？", "八股", "agent_runtime.tool_calling"),
  q("有没有考虑用大模型自己排除api超时和报错？", "八股", "agent_runtime.tool_calling"),
  q("消耗token过快怎么排查？", "八股", "evals.observability"),
  q("讲一下java线程池？", "八股", "new:cs_fundamentals"),
  q("如果你重新设计一个线程池会怎么设计？", "八股", "new:cs_fundamentals"),
  q("怎么把class文件加载到jvm中？", "八股", "new:cs_fundamentals"),
  q("mysql的undolog，redolog，binlog区别和场景？", "八股", "new:cs_fundamentals"),
  q("什么是两阶段提交？", "八股", "new:cs_fundamentals"),
  q("多线程写一个死锁", "手撕", "new:cs_fundamentals"),
  q("随便写一个单例模式", "手撕", "new:cs_fundamentals"),
  q("为什么要加volatile关键字？", "八股", "new:cs_fundamentals"),
  q("算法：合并两个有序数组", "手撕", "new:algorithm"),
 ]
})

out.append({
 "note_id": "6a6d60b9000000003400fa53",
 "note_url": "https://www.xiaohongshu.com/explore/6a6d60b9000000003400fa53?xsec_token=AB0Gm3eMOeIcA9doaaNObFcfyvvMn7AoFQsMVWPeddaKQ=&xsec_source=pc_search",
 "questions": []
})

out.append({
 "note_id": "6a86ca650000000032021585",
 "note_url": "https://www.xiaohongshu.com/explore/6a86ca650000000032021585?xsec_token=ABs_6Wz7HBZc9YAK_6iUqDKhXwwyjKy0TeOQ8FtNxtoco=&xsec_source=pc_search",
 "questions": [
  q("你的agent调了三个工具开始死循环了，异常处理写在哪？", "八股", "agent_runtime.tool_calling"),
  q("召回不准怎么监控怎么评测？", "八股", "rag.retrieval_diagnosis"),
 ]
})

out.append({
 "note_id": "69d903b50000000023006a93",
 "note_url": "https://www.xiaohongshu.com/explore/69d903b50000000023006a93?xsec_token=ABp7AJrnJdhnxtb7OJlqau9ykpHgzpMP5sJURkeHzIU2k=&xsec_source=pc_search",
 "questions": []
})

path = r"E:\MediaCrawler\data\xhs\jsonl\corpus\full\batch_02_output.jsonl"
with open(path, "w", encoding="utf-8") as f:
    for rec in out:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")

# 回读逐行校验
with open(path, encoding="utf-8") as f:
    lines = [l for l in f.read().splitlines() if l.strip()]
assert len(lines) == 8, len(lines)
phases = {"项目", "八股", "手撕", "HR"}
for i, l in enumerate(lines):
    r = json.loads(l)
    assert set(r) == {"note_id", "note_url", "questions"}, (i, set(r))
    for qq in r["questions"]:
        assert set(qq) == {"text", "phase", "knowledge_point"}
        assert qq["phase"] in phases
        assert qq["text"].strip()
print("OK", len(lines), "records;", sum(len(r["questions"]) for r in out), "questions total")
for r in out:
    print(r["note_id"], len(r["questions"]))
