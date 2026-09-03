"use client";

import { useEffect, useMemo, useState } from "react";

import {
  getInterviewHistory,
  getProfileHistory,
  getProfileSummary,
  updateRecommendationStatus,
  type InterviewHistoryItem,
  type LearningRecommendation,
  type ProfileSnapshot,
  type ProfileSummary,
  type RecommendationStatus,
} from "@/lib/api";

type ProfileChoice = {
  id: string;
  label: string;
  direction: string;
  targetTitle: string;
  sessionCount: number;
  updatedAt: string;
};

const dateFormatter = new Intl.DateTimeFormat("zh-CN", {
  year: "numeric",
  month: "long",
  day: "numeric",
  hour: "2-digit",
  minute: "2-digit",
});

function formatDate(value: string) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "时间未知" : dateFormatter.format(date);
}

function buildProfileChoices(items: InterviewHistoryItem[]) {
  const choices = new Map<string, ProfileChoice>();
  for (const item of items) {
    if (!item.profile_id) continue;
    const current = choices.get(item.profile_id);
    if (current) {
      current.sessionCount += 1;
      if (item.updated_at > current.updatedAt) current.updatedAt = item.updated_at;
      continue;
    }
    choices.set(item.profile_id, {
      id: item.profile_id,
      label: item.target_title || item.project_name || "未命名方向",
      direction: item.direction || "求职方向未设置",
      targetTitle: item.target_title || "目标岗位未设置",
      sessionCount: 1,
      updatedAt: item.updated_at,
    });
  }
  return [...choices.values()].sort((left, right) => right.updatedAt.localeCompare(left.updatedAt));
}

function trendCopy(trend: string) {
  if (trend === "improving" || trend === "up") return { label: "最近有进步", tone: "up" };
  if (trend === "declining" || trend === "down") return { label: "最近需要回看", tone: "down" };
  if (trend === "stable") return { label: "保持稳定", tone: "steady" };
  return { label: "还需要更多回答", tone: "quiet" };
}

function performanceCopy(level: number) {
  if (level >= 3) return "已经比较稳了";
  if (level >= 2) return "方向有了，再讲具体些";
  if (level >= 1) return "还在把基础讲清楚";
  return "先从核心思路开始补";
}

function statusCopy(status: RecommendationStatus) {
  if (status === "in_progress") return "练习中";
  if (status === "completed") return "已完成";
  if (status === "dismissed") return "先放一放";
  return "待开始";
}

function statusAction(recommendation: LearningRecommendation) {
  if (recommendation.status === "completed") {
    return { label: "重新开始", status: "in_progress" as RecommendationStatus };
  }
  if (recommendation.status === "dismissed") {
    return { label: "重新安排", status: "recommended" as RecommendationStatus };
  }
  if (recommendation.status === "in_progress") {
    return { label: "标记完成", status: "completed" as RecommendationStatus };
  }
  return { label: "开始练习", status: "in_progress" as RecommendationStatus };
}

const weakPointSections = [
  { priority: "high", title: "优先回看", description: "先回到最值得重听的一次回答。" },
  { priority: "medium", title: "接着练", description: "方向已经有了，再把细节讲完整。" },
  { priority: "insufficient_data", title: "再答几次看看", description: "记录还少，先多答几次再下结论。" },
] as const;

function recommendationSourceHref(recommendation: LearningRecommendation): string | null {
  if (!recommendation.source_session_id || !recommendation.source_question_id) {
    return null;
  }
  return `/report/${encodeURIComponent(recommendation.source_session_id)}#question-${encodeURIComponent(recommendation.source_question_id)}`;
}

function plainRecommendationReason(recommendation: LearningRecommendation) {
  if (!recommendation.source_question) {
    return "还没有足够的回答可以判断，先积累几次相关回答。";
  }
  if (recommendation.priority === "high") {
    return "这次回答提到了方向，但做法、边界或验证还可以说得更具体。";
  }
  if (recommendation.priority === "medium") {
    return "方向基本清楚，再补上具体做法和限制。";
  }
  return "现在的记录还少，再答几次更容易看准。";
}

export default function ProfilePage() {
  const [historyItems, setHistoryItems] = useState<InterviewHistoryItem[]>([]);
  const [selectedProfileId, setSelectedProfileId] = useState("");
  const [summary, setSummary] = useState<ProfileSummary | null>(null);
  const [snapshots, setSnapshots] = useState<ProfileSnapshot[]>([]);
  const [loadingChoices, setLoadingChoices] = useState(true);
  const [loadingProfile, setLoadingProfile] = useState(false);
  const [error, setError] = useState("");
  const [profileError, setProfileError] = useState("");
  const [actionError, setActionError] = useState("");
  const [updatingRecommendationId, setUpdatingRecommendationId] = useState("");

  const choices = useMemo(() => buildProfileChoices(historyItems), [historyItems]);
  const selectedChoice = choices.find((choice) => choice.id === selectedProfileId) ?? choices[0];
  const selectedSessions = historyItems.filter((item) => item.profile_id === selectedChoice?.id);
  const completedSessions = selectedSessions.filter((item) => item.status === "completed").length;

  async function loadChoices() {
    setLoadingChoices(true);
    setError("");
    try {
      const items = await getInterviewHistory();
      setHistoryItems(items);
      const nextChoices = buildProfileChoices(items);
      const requestedId = typeof window === "undefined"
        ? ""
        : new URLSearchParams(window.location.search).get("profile_id") ?? "";
      setSelectedProfileId(nextChoices.find((choice) => choice.id === requestedId)?.id ?? nextChoices[0]?.id ?? "");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "读取记录失败，请稍后重试。");
    } finally {
      setLoadingChoices(false);
    }
  }

  useEffect(() => {
    void loadChoices();
  }, []);

  useEffect(() => {
    if (!selectedProfileId) {
      setSummary(null);
      setSnapshots([]);
      return;
    }
    let cancelled = false;
    setLoadingProfile(true);
    setProfileError("");
    void Promise.all([getProfileSummary(selectedProfileId), getProfileHistory(selectedProfileId)])
      .then(([nextSummary, nextSnapshots]) => {
        if (cancelled) return;
        setSummary(nextSummary);
        setSnapshots(nextSnapshots);
      })
      .catch((caught) => {
        if (!cancelled) setProfileError(caught instanceof Error ? caught.message : "读取记录失败，请稍后重试。");
      })
      .finally(() => {
        if (!cancelled) setLoadingProfile(false);
      });
    return () => {
      cancelled = true;
    };
  }, [selectedProfileId]);

  function selectProfile(profileId: string) {
    setSelectedProfileId(profileId);
    if (typeof window !== "undefined") {
      window.history.replaceState(null, "", `/profile?profile_id=${encodeURIComponent(profileId)}`);
    }
  }

  async function changeRecommendationStatus(recommendationId: string, status: RecommendationStatus) {
    setUpdatingRecommendationId(recommendationId);
    setActionError("");
    try {
      const updated = await updateRecommendationStatus(recommendationId, status);
      setSummary((current) => current
        ? {
          ...current,
          recommendations: current.recommendations.map((item) => item.id === updated.id
            ? {
              ...updated,
              source_session_id: updated.source_session_id,
              source_question_id: updated.source_question_id,
              source_question: updated.source_question,
              source_answer_excerpt: updated.source_answer_excerpt,
              source_level: updated.source_level,
            }
            : item),
        }
        : current);
    } catch (caught) {
      setActionError(caught instanceof Error ? caught.message : "更新练习状态失败，请稍后重试。");
    } finally {
      setUpdatingRecommendationId("");
    }
  }

  const weakRecommendations = summary?.recommendations.filter((recommendation) => recommendation.priority !== "low") ?? [];

  return (
    <main className="mint-page mint-page--profile">
      <div className="mint-shell">
        <header className="mint-header">
          <a className="mint-brand" href="/" aria-label="Agent Echo 首页">
            <span className="mint-brand-mark" aria-hidden="true">✦</span>
            <span className="mint-brand-name">Agent Echo</span>
          </a>
          <nav className="mint-nav" aria-label="页面导航">
            <a className="mint-nav-link" href="/">返回准备</a>
            <a className="mint-nav-link" href="/history">面试记录</a>
            <span className="mint-nav-current">我还要补什么</span>
            <a className="mint-nav-link" href="/console">模型设置</a>
          </nav>
        </header>

        <section className="mint-profile-intro" aria-labelledby="profile-title">
          <div>
            <p className="mint-overline">最近几场面试</p>
            <h1 id="profile-title" className="mint-profile-title">我还要补什么？</h1>
            <p className="mint-lead">根据最近几场面试，整理出最值得回看的地方。</p>
          </div>
          <div className="mint-profile-counter" aria-label={`${choices.length} 个求职方向`}>
            <span>已记录方向</span>
            <strong>{choices.length}</strong>
            <span>{choices.length === 1 ? "个" : "个"}</span>
          </div>
        </section>

        {error && (
          <div className="mint-profile-feedback">
            <p className="mint-alert" role="alert">{error}</p>
            <button type="button" className="mint-button mint-button--outline" onClick={() => void loadChoices()} disabled={loadingChoices}>再试一次</button>
          </div>
        )}

        {loadingChoices ? (
          <div className="mint-card mint-profile-empty"><p className="mint-note">正在读取你的面试记录…</p></div>
        ) : !choices.length && !error ? (
          <section className="mint-card mint-profile-empty" aria-label="空的薄弱项记录">
            <span className="mint-profile-empty-mark" aria-hidden="true">○</span>
            <h2>还没有可以查看的面试记录</h2>
            <p>完成一场面试后，这里会告诉你下一步先练什么。</p>
            <a className="mint-button mint-button--primary" href="/">开始第一场</a>
          </section>
        ) : (
          <div className="mint-profile-layout">
            <aside className="mint-card mint-profile-selector" aria-label="选择求职方向">
              <p className="mint-card-kicker">我的方向</p>
              <div className="mint-profile-choice-list">
                {choices.map((choice) => (
                  <button
                    type="button"
                    className={`mint-profile-choice ${choice.id === selectedChoice?.id ? "is-selected" : ""}`}
                    key={choice.id}
                    onClick={() => selectProfile(choice.id)}
                    aria-pressed={choice.id === selectedChoice?.id}
                  >
                    <span className="mint-profile-choice-label">{choice.label}</span>
                    <span className="mint-profile-choice-meta">{choice.direction} · {choice.sessionCount} 场</span>
                  </button>
                ))}
              </div>
              <p className="mint-profile-selector-note">不同方向的练习记录会分开保存。</p>
            </aside>

            <div className="mint-profile-content">
              {profileError && (
                <div className="mint-profile-feedback">
                  <p className="mint-alert" role="alert">{profileError}</p>
                  <button type="button" className="mint-button mint-button--outline" onClick={() => selectProfile(selectedProfileId)}>再试一次</button>
                </div>
              )}

              {loadingProfile ? (
                <div className="mint-card mint-profile-empty"><p className="mint-note">正在整理这一路的记录…</p></div>
              ) : summary ? (
                <>
                  <section className="mint-card mint-profile-overview" aria-labelledby="profile-overview-title">
                    <div className="mint-profile-overview-top">
                      <div>
                        <p className="mint-card-kicker">当前方向</p>
                        <h2 id="profile-overview-title" className="mint-profile-overview-title">{summary.target_title || selectedChoice?.targetTitle}</h2>
                        <p className="mint-profile-overview-meta">{summary.direction}</p>
                      </div>
                      <span className="mint-status-pill mint-status-pill--ready">已记录</span>
                    </div>
                    <p className="mint-profile-summary">{summary.summary || "再完成几次面试，这里的建议会更具体。"}</p>
                    <div className="mint-profile-overview-stats">
                      <div><span>参考面试</span><strong>{selectedSessions.length}</strong><small>场</small></div>
                      <div><span>已结束</span><strong>{completedSessions}</strong><small>场</small></div>
                      <div><span>最近更新</span><strong>{formatDate(summary.updated_at)}</strong></div>
                    </div>
                  </section>

                  <section className="mint-profile-section" aria-labelledby="profile-recommendations-title">
                    <div className="mint-profile-section-heading">
                      <div>
                        <p className="mint-overline">根据最近的回答</p>
                        <h2 id="profile-recommendations-title" className="mint-profile-section-title">优先处理的薄弱项</h2>
                      </div>
                    </div>
                    {actionError && <p className="mint-alert" role="alert">{actionError}</p>}
                    {!weakRecommendations.length ? (
                      <div className="mint-card mint-profile-subempty">
                        <p className="mint-note">目前没有需要优先补的地方，继续保持并积累新的回答。</p>
                      </div>
                    ) : (
                      <div className="mint-weak-point-list">
                        {weakPointSections.map((section) => {
                          const items = weakRecommendations.filter((recommendation) => recommendation.priority === section.priority);
                          return (
                            <section className="mint-card mint-profile-subempty" key={section.priority}>
                              <div className="mint-profile-section-heading">
                                <div>
                                  <p className="mint-overline">{section.title}</p>
                                  <h3 className="mint-profile-section-title">{section.description}</h3>
                                </div>
                              </div>
                              {!items.length ? (
                                <p className="mint-note">这一类暂时还没有需要处理的题目。</p>
                              ) : (
                                <div className="mint-weak-point-list">
                                  {items.map((recommendation) => {
                                    const action = statusAction(recommendation);
                                    const updating = updatingRecommendationId === recommendation.id;
                                    const sourceHref = recommendationSourceHref(recommendation);
                                    return (
                                      <article className={`mint-card mint-weak-point-card ${recommendation.status === "dismissed" ? "is-dismissed" : ""}`} key={recommendation.id}>
                                        <div className="mint-weak-point-heading">
                                          <span>{recommendation.skill_name}</span>
                                          <span>{section.title}</span>
                                        </div>
                                        <h3>{recommendation.source_question ?? "还没有足够的回答可以判断"}</h3>
                                        <p className="mint-weak-point-reason">{plainRecommendationReason(recommendation)}</p>
                                        {recommendation.source_answer_excerpt && (
                                          <blockquote className="mint-weak-point-source">
                                            你当时提到：{recommendation.source_answer_excerpt}
                                          </blockquote>
                                        )}
                                        {!!recommendation.actions.length && (
                                          <div className="mint-recommendation-block">
                                            <span>建议怎么练</span>
                                            <ul>
                                              {recommendation.actions.slice(0, 3).map((item) => <li key={item}>{item}</li>)}
                                            </ul>
                                          </div>
                                        )}
                                        {!!recommendation.success_criteria.length && (
                                          <div className="mint-recommendation-block">
                                            <span>练到什么程度算有感觉</span>
                                            <ul>
                                              {recommendation.success_criteria.slice(0, 3).map((item) => <li key={item}>{item}</li>)}
                                            </ul>
                                          </div>
                                        )}
                                        <div className="mint-weak-point-actions">
                                          {sourceHref && <a href={sourceHref}>查看这次回答</a>}
                                          <button type="button" className="mint-button mint-button--primary" onClick={() => void changeRecommendationStatus(recommendation.id, action.status)} disabled={updating}>
                                            {updating ? "正在更新…" : action.label}
                                          </button>
                                          {recommendation.status !== "dismissed" && recommendation.status !== "completed" && (
                                            <button type="button" className="mint-button mint-button--quiet" onClick={() => void changeRecommendationStatus(recommendation.id, "dismissed")} disabled={updating}>
                                              暂时放一放
                                            </button>
                                          )}
                                        </div>
                                        <p className="mint-note">{statusCopy(recommendation.status)}</p>
                                      </article>
                                    );
                                  })}
                                </div>
                              )}
                            </section>
                          );
                        })}
                      </div>
                    )}
                  </section>

                  <section className="mint-profile-section mint-profile-secondary" aria-labelledby="profile-skills-title">
                    <div className="mint-profile-section-heading">
                      <div>
                        <p className="mint-overline">长期记录</p>
                        <h2 id="profile-skills-title" className="mint-profile-section-title">查看完整记录</h2>
                      </div>
                    </div>
                    {!summary.skills.length ? (
                      <div className="mint-card mint-profile-subempty"><p className="mint-note">还没有足够的回答可以判断长期变化。</p></div>
                    ) : (
                      <div className="mint-profile-skill-list">
                        {summary.skills.map((skill) => {
                          const trend = trendCopy(skill.trend);
                          return (
                            <article className="mint-card mint-profile-skill" key={skill.skill_id}>
                              <div className="mint-profile-skill-top">
                                <div>
                                  <h3>{skill.skill_name}</h3>
                                  <span>{skill.category}</span>
                                </div>
                                <span className={`mint-profile-trend mint-profile-trend--${trend.tone}`}>{trend.label}</span>
                              </div>
                              <div className="mint-profile-skill-details">
                                <span>最近表现 <strong>{performanceCopy(skill.level)}</strong></span>
                                <span>相关回答 <strong>{skill.sample_count} 次</strong></span>
                                <span>最近变化 <strong>{trend.label}</strong></span>
                              </div>
                            </article>
                          );
                        })}
                      </div>
                    )}
                  </section>

                  <section className="mint-profile-section" aria-labelledby="profile-timeline-title">
                    <div className="mint-profile-section-heading">
                      <div>
                        <p className="mint-overline">每次面试都会留下一笔</p>
                        <h2 id="profile-timeline-title" className="mint-profile-section-title">以前的面试记录</h2>
                      </div>
                    </div>
                    {!snapshots.length ? (
                      <div className="mint-card mint-profile-subempty"><p className="mint-note">完成并生成第一份结果后，这里会出现变化记录。</p></div>
                    ) : (
                      <div className="mint-card mint-profile-timeline">
                        {snapshots.slice(0, 8).map((snapshot) => (
                          <div className="mint-profile-timeline-item" key={snapshot.id}>
                            <span className="mint-profile-timeline-dot" aria-hidden="true" />
                            <div><strong>第 {snapshot.version} 次记录</strong><span>{formatDate(snapshot.created_at)}</span></div>
                            <a href={`/report/${snapshot.source_session_id}`}>查看这场</a>
                          </div>
                        ))}
                      </div>
                    )}
                  </section>
                </>
              ) : null}
            </div>
          </div>
        )}

        <footer className="mint-footer">本地单用户模式 · 记录来自已完成的面试回答</footer>
      </div>
    </main>
  );
}
