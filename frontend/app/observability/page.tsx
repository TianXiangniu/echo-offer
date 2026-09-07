"use client";

import { useEffect, useState } from "react";

type Summary = {
  call_count: number; known_cost_cny: string; unpriced_call_count: number;
  total_tokens: number; success_rate: number | null; average_latency_ms: number | null;
  items: Array<{ id: string; call_kind: string; model_name: string; status: string; error_code: string | null; total_tokens: number | null; cost_cny: string | null; latency_ms: number; finished_at: string }>;
};

export default function ObservabilityPage() {
  const [summary, setSummary] = useState<Summary>();
  const [error, setError] = useState("");
  useEffect(() => {
    fetch(`${process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000"}/api/observability/summary`)
      .then((response) => response.ok ? response.json() : Promise.reject(new Error("读取模型观测失败")))
      .then(setSummary).catch((caught) => setError(caught.message));
  }, []);
  return <main className="mint-page"><div className="mint-shell">
    <header className="mint-header"><a className="mint-brand" href="/">✦ Agent Echo</a><nav className="mint-nav"><a className="mint-nav-link" href="/console">模型设置</a><span className="mint-nav-current">模型观测</span></nav></header>
    <section className="mint-console-intro"><div><p className="mint-overline">LOCAL OBSERVABILITY</p><h1 className="mint-console-title">模型调用与成本</h1><p className="mint-lead">仅统计本机调用；未配置模型价格的记录不会被当作免费调用。</p></div></section>
    {error && <p className="mint-alert">{error}</p>}
    {!summary && !error && <p className="mint-note">正在读取最近调用…</p>}
    {summary && <><section className="mint-console-layout"><div className="mint-card"><p className="mint-card-kicker">已知成本</p><strong>¥{Number(summary.known_cost_cny).toFixed(4)}</strong><p className="mint-note">{summary.unpriced_call_count} 次未定价</p></div><div className="mint-card"><p className="mint-card-kicker">模型调用</p><strong>{summary.call_count}</strong><p className="mint-note">成功率 {summary.success_rate === null ? "—" : `${Math.round(summary.success_rate * 100)}%`}</p></div><div className="mint-card"><p className="mint-card-kicker">Token</p><strong>{summary.total_tokens.toLocaleString()}</strong><p className="mint-note">已返回 usage 的调用</p></div><div className="mint-card"><p className="mint-card-kicker">平均延迟</p><strong>{summary.average_latency_ms ?? "—"} ms</strong><p className="mint-note">包含成功与失败请求</p></div></section>
    <section className="mint-card"><h2 className="mint-settings-title">最近调用</h2><table><thead><tr><th>时间</th><th>类型</th><th>模型</th><th>状态</th><th>Token</th><th>成本</th><th>延迟</th></tr></thead><tbody>{summary.items.map((item) => <tr key={item.id}><td>{new Date(item.finished_at).toLocaleString("zh-CN")}</td><td>{item.call_kind}</td><td>{item.model_name}</td><td>{item.status === "succeeded" ? "成功" : item.error_code ?? "失败"}</td><td>{item.total_tokens ?? "—"}</td><td>{item.cost_cny === null ? "未配置" : `¥${Number(item.cost_cny).toFixed(4)}`}</td><td>{item.latency_ms} ms</td></tr>)}</tbody></table></section></>}
  </div></main>;
}
