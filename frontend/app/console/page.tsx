"use client";

import { FormEvent, useEffect, useState } from "react";

import {
  getModelSettings,
  ModelConnectionTestResponse,
  ModelSettingsResponse,
  ModelSettingsUpdate,
  testModelConnection,
  updateModelSettings,
} from "@/lib/api";

type ModelSettingsForm = Omit<ModelSettingsUpdate, "api_key"> & { api_key: string };

const DEFAULT_FORM: ModelSettingsForm = {
  base_url: "https://api.siliconflow.cn/v1",
  model: "deepseek-ai/DeepSeek-V4-Flash",
  assessment_model: "deepseek-ai/DeepSeek-V4-Flash",
  api_key: "",
  clear_api_key: false,
  temperature: 0.1,
  max_tokens: 3200,
  timeout_seconds: 90,
  assessment_batch_size: 3,
};

function settingsToForm(settings: ModelSettingsResponse): ModelSettingsForm {
  return {
    base_url: settings.base_url,
    model: settings.model,
    assessment_model: settings.assessment_model,
    api_key: "",
    clear_api_key: false,
    temperature: settings.temperature,
    max_tokens: settings.max_tokens,
    timeout_seconds: settings.timeout_seconds,
    assessment_batch_size: settings.assessment_batch_size,
  };
}

function describeConnection(result: ModelConnectionTestResponse) {
  if (!result.ok) return result.message;
  return `${result.message}（${Math.round(result.latency_ms)} ms）`;
}

export default function ModelConsolePage() {
  const [form, setForm] = useState<ModelSettingsForm>(DEFAULT_FORM);
  const [settings, setSettings] = useState<ModelSettingsResponse>();
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [error, setError] = useState("");
  const [feedback, setFeedback] = useState("");

  function setField<Key extends keyof ModelSettingsForm>(field: Key, value: ModelSettingsForm[Key]) {
    setForm((current) => ({ ...current, [field]: value }));
    setError("");
    setFeedback("");
  }

  useEffect(() => {
    let active = true;
    void getModelSettings()
      .then((loaded) => {
        if (!active) return;
        setSettings(loaded);
        setForm(settingsToForm(loaded));
      })
      .catch((caught) => {
        if (!active) return;
        setError(caught instanceof Error ? caught.message : "读取模型设置失败，请稍后重试。 ");
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, []);

  async function handleSave(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSaving(true);
    setError("");
    setFeedback("");
    try {
      const saved = await updateModelSettings({
        ...form,
        api_key: form.api_key.trim() || undefined,
      });
      setSettings(saved);
      setForm(settingsToForm(saved));
      setFeedback("设置已保存，并已应用到后续请求。");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "保存失败，请检查填写内容。 ");
    } finally {
      setSaving(false);
    }
  }

  async function handleTestConnection() {
    setTesting(true);
    setError("");
    setFeedback("");
    try {
      const result = await testModelConnection();
      if (result.ok) setFeedback(describeConnection(result));
      else setError(describeConnection(result));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "连接测试失败，请稍后重试。 ");
    } finally {
      setTesting(false);
    }
  }

  function handleReset() {
    setForm((current) => ({ ...DEFAULT_FORM, api_key: current.api_key }));
    setError("");
    setFeedback("已恢复页面默认参数；API Key 未改变，保存后才会生效。");
  }

  const busy = loading || saving || testing;

  return (
    <main className="mint-page mint-page--console">
      <div className="mint-shell">
        <header className="mint-header">
          <a className="mint-brand" href="/" aria-label="Agent Echo 首页">
            <span className="mint-brand-mark" aria-hidden="true">✦</span>
            <span className="mint-brand-name">Agent Echo</span>
          </a>
          <nav className="mint-nav" aria-label="页面导航">
            <a className="mint-nav-link" href="/">返回准备</a>
            <a className="mint-nav-link" href="/history">面试记录</a>
            <a className="mint-nav-link" href="/profile">能力概况</a>
            <span className="mint-nav-current">模型设置</span>
          </nav>
        </header>

        <section className="mint-console-intro" aria-labelledby="console-title">
          <div>
            <p className="mint-overline">LOCAL CONSOLE</p>
            <h1 id="console-title" className="mint-console-title">模型设置</h1>
            <p className="mint-lead">项目整理和面试评分都从这里读取配置。保存后，后续请求会立即使用新的参数。</p>
          </div>
          <div className="mint-console-status" aria-live="polite">
            <span className={`mint-status-pill ${settings?.api_key_configured ? "is-ready" : "is-empty"}`}>
              <span aria-hidden="true">●</span>{settings?.api_key_configured ? "API Key 已配置" : "API Key 未配置"}
            </span>
            <p className="mint-note">设置只保存在本机的单用户数据库中。</p>
          </div>
        </section>

        {error && <p className="mint-alert" role="alert">{error}</p>}
        {feedback && !error && <p className="mint-console-success" role="status">{feedback}</p>}

        <div className="mint-console-layout">
          <aside className="mint-card mint-console-aside">
            <p className="mint-card-kicker">这几个设置最常用</p>
            <div className="mint-console-aside-list">
              <div>
                <strong>最大输出长度</strong>
                <p>模型回答过长时，提高这个值可以减少内容被截断。</p>
              </div>
              <div>
                <strong>请求超时时间</strong>
                <p>网络慢或模型排队时，给请求多一点等待时间。</p>
              </div>
              <div>
                <strong>每批评分题目数量</strong>
                <p>一次评分的题目越多，请求次数越少，但单次内容会更长。</p>
              </div>
            </div>
            <p className="mint-console-security">API Key 不会出现在读取接口的返回值里。留空保存时，会保留现有密钥。</p>
          </aside>

          <form className="mint-card mint-console-form" onSubmit={handleSave}>
            <section className="mint-settings-section" aria-labelledby="provider-heading">
              <div className="mint-settings-heading">
                <div>
                  <p className="mint-section-eyebrow">服务</p>
                  <h2 id="provider-heading" className="mint-settings-title">连接哪个模型服务</h2>
                </div>
                <span className="mint-settings-number">01</span>
              </div>
              <div className="mint-settings-grid">
                <label className="mint-field mint-field--wide">
                  <span className="mint-field-label">服务地址</span>
                  <input className="mint-input" value={form.base_url} onChange={(event) => setField("base_url", event.target.value)} placeholder="https://api.siliconflow.cn/v1" required />
                  <span className="mint-field-help">填写兼容 OpenAI 接口的服务地址。</span>
                </label>
                <label className="mint-field">
                  <span className="mint-field-label">项目整理模型</span>
                  <input className="mint-input" value={form.model} onChange={(event) => setField("model", event.target.value)} required />
                  <span className="mint-field-help">上传简历后，用来整理项目和生成问题。</span>
                </label>
                <label className="mint-field">
                  <span className="mint-field-label">面试评分模型</span>
                  <input className="mint-input" value={form.assessment_model} onChange={(event) => setField("assessment_model", event.target.value)} required />
                  <span className="mint-field-help">整场面试结束后，用来批量分析回答。</span>
                </label>
                <label className="mint-field mint-field--wide">
                  <span className="mint-field-label">API Key</span>
                  <input className="mint-input" type="password" value={form.api_key} onChange={(event) => setField("api_key", event.target.value)} placeholder={settings?.api_key_configured ? "已配置，输入新 Key 可替换" : "粘贴你的 API Key"} autoComplete="new-password" />
                  <span className="mint-field-help">已配置时不会回填，留空表示保持不变。</span>
                </label>
                <label className="mint-checkbox">
                  <input type="checkbox" checked={form.clear_api_key} onChange={(event) => setField("clear_api_key", event.target.checked)} />
                  <span>清除已保存的 API Key</span>
                </label>
              </div>
            </section>

            <section className="mint-settings-section" aria-labelledby="runtime-heading">
              <div className="mint-settings-heading">
                <div>
                  <p className="mint-section-eyebrow">参数</p>
                  <h2 id="runtime-heading" className="mint-settings-title">控制回答方式</h2>
                </div>
                <span className="mint-settings-number">02</span>
              </div>
              <div className="mint-settings-grid">
                <label className="mint-field">
                  <span className="mint-field-label">温度（Temperature）</span>
                  <input className="mint-input" type="number" min="0" max="2" step="0.1" value={form.temperature} onChange={(event) => setField("temperature", Number(event.target.value))} required />
                  <span className="mint-field-help">越低越稳定，建议保持在 0.1–0.3。</span>
                </label>
                <label className="mint-field">
                  <span className="mint-field-label">最大输出长度</span>
                  <input className="mint-input" type="number" min="256" max="8192" step="128" value={form.max_tokens} onChange={(event) => setField("max_tokens", Number(event.target.value))} required />
                  <span className="mint-field-help">回答太长被截断时，可以适当调高。</span>
                </label>
                <label className="mint-field">
                  <span className="mint-field-label">请求超时时间</span>
                  <div className="mint-input-with-unit"><input className="mint-input" type="number" min="10" max="300" step="5" value={form.timeout_seconds} onChange={(event) => setField("timeout_seconds", Number(event.target.value))} required /><span>秒</span></div>
                  <span className="mint-field-help">模型响应较慢时，可调高到 120 秒。</span>
                </label>
                <label className="mint-field">
                  <span className="mint-field-label">每批评分题目数量</span>
                  <input className="mint-input" type="number" min="1" max="5" step="1" value={form.assessment_batch_size} onChange={(event) => setField("assessment_batch_size", Number(event.target.value))} required />
                  <span className="mint-field-help">整场面试结束后，按批次调用评分模型。</span>
                </label>
              </div>
            </section>

            <div className="mint-console-actions">
              <div>
                <button className="mint-button mint-button--primary" type="submit" disabled={busy}>{saving ? "正在保存…" : "保存并应用"}</button>
                <button className="mint-button mint-button--outline" type="button" onClick={handleTestConnection} disabled={busy}>{testing ? "测试中…" : "测试连接"}</button>
                <button className="mint-button mint-button--quiet" type="button" onClick={handleReset} disabled={busy}>恢复默认</button>
              </div>
              <p className="mint-note">测试连接使用当前已保存的设置。</p>
            </div>
          </form>
        </div>

        <footer className="mint-footer">本地单用户模式 · 设置只服务于当前电脑上的 Echo Offer</footer>
      </div>
    </main>
  );
}
