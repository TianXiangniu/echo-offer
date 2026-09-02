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

function formatPercent(value: number) {
  return `${Math.round(Math.max(0, Math.min(1, value)) * 100)}%`;
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

function priorityCopy(priority: string) {
  if (priority === "high") return "优先补上";
  if (priority === "medium") return "接着练";
  if (priority === "insufficient_data") return "再答几次看看";
  return "有空再练";
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
      setError(caught instanceof Error ? caught.message : "读取能力概况失败，请稍后重试。");
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
        if (!cancelled) setProfileError(caught instanceof Error ? caught.message : "读取能力概况失败，请稍后重试。");
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
        ? { ...current, recommendations: current.recommendations.map((item) => item.id === updated.id ? updated : item) }
        : current);
    } catch (caught) {
      setActionError(caught instanceof Error ? caught.message : "更新练习状态失败，请稍后重试。");
    } finally {
      setUpdatingRecommendationId("");
    }
  }

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
            <span className="mint-nav-current">能力概况</span>
            <a className="mint-nav-link" href="/console">模型设置</a>
          </nav>
        </header>

        <section className="mint-profile-intro" aria-labelledby="profile-title">
          <div>
            <p className="mint-overline">能力概况</p>
            <h1 id="profile-title" className="mint-profile-title">看看自己，正在往哪儿变强。</h1>
            <p className="mint-lead">这里记录每次有效回答留下的变化，也把下一步要练的内容列清楚。</p>
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
          <div className="mint-card mint-profile-empty"><p className="mint-note">正在读取你的能力记录…</p></div>
        ) : !choices.length && !error ? (
          <section className="mint-card mint-profile-empty" aria-label="空的能力概况">
            <span className="mint-profile-empty-mark" aria-hidden="true">○</span>
            <h2>还没有可以查看的能力记录</h2>
            <p>完成一场面试后，这里会把你的回答变化和练习方向整理出来。</p>
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
                        <p className="mint-profile-overview-meta">{summary.direction} · {summary.level}</p>
                      </div>
                      <span className="mint-status-pill mint-status-pill--ready">已记录</span>
                    </div>
                    <p className="mint-profile-summary">{summary.summary || "完成更多有效回答后，这里会逐渐形成更清晰的能力概况。"}</p>
                    <div className="mint-profile-overview-stats">
                      <div><span>相关面试</span><strong>{selectedSessions.length}</strong><small>场</small></div>
                      <div><span>已完成</span><strong>{completedSessions}</strong><small>场</small></div>
                      <div><span>最近更新</span><strong>{formatDate(summary.updated_at)}</strong></div>
                    </div>
                  </section>

                  <section className="mint-profile-section" aria-labelledby="profile-skills-title">
                    <div className="mint-profile-section-heading">
                      <div>
                        <p className="mint-overline">回答留下的线索</p>
                        <h2 id="profile-skills-title" className="mint-profile-section-title">能力</h2>
                      </div>
                      <span className="mint-note">等级 0–4 · 不是总分</span>
                    </div>
                    {!summary.skills.length ? (
                      <div className="mint-card mint-profile-subempty"><p className="mint-note">目前还没有足够的有效回答来判断能力变化。</p></div>
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
                              <div className="mint-level-dots" aria-label={`${skill.skill_name} 当前等级 ${skill.level}，共 4 级`}>
                                {[0, 1, 2, 3, 4].map((level) => <span className={level <= skill.level ? "is-filled" : ""} key={level} />)}
                              </div>
                              <div className="mint-profile-skill-details">
                                <span>当前 <strong>{skill.level} / 4</strong></span>
                                <span>目标 <strong>{skill.target_level == null ? "未设置" : `${skill.target_level} / 4`}</strong></span>
                                <span>有效回答 <strong>{skill.sample_count} 次</strong></span>
                                <span>稳定程度 <strong>{formatPercent(skill.confidence)}</strong></span>
                              </div>
                            </article>
                          );
                        })}
                      </div>
                    )}
                  </section>

                  <section className="mint-profile-section" aria-labelledby="profile-recommendations-title">
                    <div className="mint-profile-section-heading">
                      <div>
                        <p className="mint-overline">根据最近的回答</p>
                        <h2 id="profile-recommendations-title" className="mint-profile-section-title">接下来练什么</h2>
                      </div>
                      <span className="mint-note">先做最有用的一件</span>
                    </div>
                    {actionError && <p className="mint-alert" role="alert">{actionError}</p>}
                    {!summary.recommendations.length ? (
                      <div className="mint-card mint-profile-subempty"><p className="mint-note">目前没有新的练习建议，继续完成面试就好。</p></div>
                    ) : (
                      <div className="mint-recommendation-list">
                        {summary.recommendations.map((recommendation) => {
                          const action = statusAction(recommendation);
                          const updating = updatingRecommendationId === recommendation.id;
                          return (
                            <article className={`mint-card mint-recommendation ${recommendation.status === "dismissed" ? "is-dismissed" : ""}`} key={recommendation.id}>
                              <div className="mint-recommendation-top">
                                <div>
                                  <span className="mint-recommendation-priority">{priorityCopy(recommendation.priority)}</span>
                                  <h3>{recommendation.skill_name}</h3>
                                </div>
                                <span className="mint-recommendation-status">{statusCopy(recommendation.status)}</span>
                              </div>
                              <p className="mint-recommendation-reason">{recommendation.reason}</p>
                              {!!recommendation.actions.length && (
                                <div className="mint-recommendation-block"><span>可以这样练</span><ul>{recommendation.actions.map((item) => <li key={item}>{item}</li>)}</ul></div>
                              )}
                              {!!recommendation.success_criteria.length && (
                                <div className="mint-recommendation-block"><span>练到这里就算有收获</span><ul>{recommendation.success_criteria.map((item) => <li key={item}>{item}</li>)}</ul></div>
                              )}
                              <div className="mint-recommendation-actions">
                                <button type="button" className="mint-button mint-button--primary" onClick={() => void changeRecommendationStatus(recommendation.id, action.status)} disabled={updating}>{updating ? "正在更新…" : action.label}</button>
                                {recommendation.status !== "dismissed" && recommendation.status !== "completed" && <button type="button" className="mint-button mint-button--quiet" onClick={() => void changeRecommendationStatus(recommendation.id, "dismissed")} disabled={updating}>暂时放一放</button>}
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
                        <p className="mint-overline">每次有效面试都会留下一笔</p>
                        <h2 id="profile-timeline-title" className="mint-profile-section-title">变化记录</h2>
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

        <footer className="mint-footer">本地单用户模式 · 能力概况来自已完成的有效回答</footer>
      </div>
    </main>
  );
}
