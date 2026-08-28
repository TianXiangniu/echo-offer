"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";

import { getReport, Report } from "@/lib/api";

const levelLabels: Record<string, string> = { "0": "无有效内容", "1": "名词层", "2": "基本理解", "3": "场景分析", "4": "深入权衡" };

function percent(value: number) {
  return `${Math.round(value * 100)}%`;
}

function KnowledgeList({ items, emptyText }: { items: Report["strengths"]; emptyText: string }) {
  if (!items.length) return <p className="rounded-2xl bg-ink/5 px-4 py-5 text-sm text-ink/45">{emptyText}</p>;
  return <div className="space-y-3">{items.map((item) => <article key={item.knowledge_point_id} className="rounded-2xl border border-ink/10 bg-white/60 p-4"><div className="flex items-center justify-between gap-4"><span className="font-mono text-xs text-ink/55">{item.knowledge_point_id}</span><span className="rounded-full bg-signal/10 px-2.5 py-1 text-xs font-semibold text-signal">等级 {item.level}</span></div><p className="mt-3 text-sm leading-6 text-ink/70">“{item.evidence}”</p><p className="mt-2 text-xs text-ink/40">证据置信度 {percent(item.confidence)}</p></article>)}</div>;
}

export default function ReportPage() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const [report, setReport] = useState<Report | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    getReport(params.id).then(setReport).catch((caught) => setError(caught instanceof Error ? caught.message : "无法读取报告。"));
  }, [params.id]);

  if (error) return <main className="grid min-h-screen place-items-center bg-paper px-6 text-center text-ink"><div><p className="text-red-700">{error}</p><button onClick={() => router.push("/")} className="mt-6 rounded-xl bg-ink px-5 py-3 text-paper">返回首页</button></div></main>;
  if (!report) return <main className="grid min-h-screen place-items-center bg-paper text-ink">正在整理你的报告…</main>;

  return (
    <main className="min-h-screen bg-paper text-ink">
      <div className="mx-auto max-w-6xl px-5 py-7 sm:px-10">
        <header className="flex items-center justify-between border-b border-ink/10 pb-6"><button onClick={() => router.push("/")} className="font-display text-xl">Agent Echo</button><span className="text-xs uppercase tracking-[0.2em] text-ink/45">Post-interview / Alpha</span></header>
        <section className="grid gap-10 pb-20 pt-14 lg:grid-cols-[0.75fr_1.25fr] lg:gap-20">
          <div><p className="text-xs font-semibold uppercase tracking-[0.22em] text-signal">Your first signal</p><h1 className="mt-5 max-w-xl font-display text-5xl font-semibold leading-tight sm:text-7xl">先看证据，再谈能力。</h1><p className="mt-6 max-w-md text-lg leading-8 text-ink/60">这是一份基于本地规则评估器的 Alpha 报告。它保留你的首答证据，不把训练表现覆盖到首答等级。</p><button onClick={() => router.push("/")} className="mt-8 rounded-xl bg-ink px-5 py-3 font-semibold text-paper transition hover:bg-signal">再做一场 →</button></div>
          <div className="grid gap-4 sm:grid-cols-3"><div className="rounded-3xl bg-ink p-5 text-paper"><p className="text-xs text-white/50">完成度</p><p className="mt-5 font-display text-4xl">{report.completion.completed}<span className="text-xl text-white/40">/{report.completion.total}</span></p><p className="mt-2 text-xs text-white/50">已记录首答</p></div><div className="rounded-3xl border border-ink/10 bg-white/65 p-5"><p className="text-xs text-ink/50">覆盖率</p><p className="mt-5 font-display text-4xl">{percent(report.coverage)}</p><p className="mt-2 text-xs text-ink/50">不是综合分数</p></div><div className="rounded-3xl border border-ink/10 bg-white/65 p-5"><p className="text-xs text-ink/50">锚题</p><p className="mt-5 font-display text-4xl">{report.anchor_coverage.answered}<span className="text-xl text-ink/30">/{report.anchor_coverage.total}</span></p><p className="mt-2 text-xs text-ink/50">跨场比较基础</p></div></div>
        </section>

        <section className="grid gap-6 border-t border-ink/10 py-10 lg:grid-cols-2"><div><div className="mb-5 flex items-end justify-between"><div><p className="text-xs uppercase tracking-[0.2em] text-signal">Strengths</p><h2 className="mt-2 font-display text-3xl">你已经说清楚的部分</h2></div><span className="text-sm text-ink/40">Top 3</span></div><KnowledgeList items={report.strengths} emptyText="当前还没有达到等级 3 的有效观察。" /></div><div><div className="mb-5 flex items-end justify-between"><div><p className="text-xs uppercase tracking-[0.2em] text-ember">Gaps</p><h2 className="mt-2 font-display text-3xl">下一次可以补上的部分</h2></div><span className="text-sm text-ink/40">Top 3</span></div><KnowledgeList items={report.gaps} emptyText="当前没有可展示的缺口。" /></div></section>

        <section className="grid gap-6 border-t border-ink/10 py-10 lg:grid-cols-[1fr_0.8fr]"><div><p className="text-xs uppercase tracking-[0.2em] text-signal">Evidence quality</p><h2 className="mt-2 font-display text-3xl">这份报告的可信边界</h2><div className="mt-5 rounded-3xl border border-ink/10 bg-white/60 p-6"><div className="flex items-center justify-between text-sm"><span>有效证据数</span><strong>{report.valid_evidence_count}</strong></div><div className="mt-4 flex items-center justify-between text-sm"><span>平均证据置信度</span><strong>{percent(report.confidence)}</strong></div><p className="mt-6 border-t border-ink/10 pt-5 text-sm leading-7 text-ink/55">至少三条跨问题、跨场次的独立证据后，才适合形成更稳定的能力判断。本场报告不展示未经校准的 0—100 总分。</p></div></div><div><p className="text-xs uppercase tracking-[0.2em] text-signal">Level distribution</p><h2 className="mt-2 font-display text-3xl">观察等级</h2><div className="mt-5 space-y-3">{Object.entries(report.level_distribution).map(([level, count]) => <div key={level} className="flex items-center gap-3 text-sm"><span className="w-24 text-ink/55">{level} · {levelLabels[level]}</span><div className="h-2 flex-1 overflow-hidden rounded-full bg-ink/10"><div className="h-full rounded-full bg-signal" style={{ width: `${report.valid_evidence_count ? (count / report.valid_evidence_count) * 100 : 0}%` }} /></div><span className="w-5 text-right text-ink/50">{count}</span></div>)}</div></div></section>
        <footer className="border-t border-ink/10 py-8 text-xs text-ink/40">评估器：{report.evaluator} · 本报告是垂直切片演示，不代表最终 LLM 评分质量。</footer>
      </div>
    </main>
  );
}
