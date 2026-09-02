import { readFileSync } from "node:fs";

const api = readFileSync(new URL("./api.ts", import.meta.url), "utf8");
const consolePage = readFileSync(new URL("../app/console/page.tsx", import.meta.url), "utf8");
const homePage = readFileSync(new URL("../app/page.tsx", import.meta.url), "utf8");
const css = readFileSync(new URL("../app/globals.css", import.meta.url), "utf8");

for (const token of [
  "ModelSettingsResponse",
  "ModelSettingsUpdate",
  "ModelConnectionTestResponse",
  "getModelSettings",
  "updateModelSettings",
  "testModelConnection",
  "/api/settings/model",
]) {
  if (!api.includes(token)) throw new Error(`model settings API contract is missing: ${token}`);
}

const responseStart = api.indexOf("export type ModelSettingsResponse");
const responseEnd = api.indexOf("export type ModelSettingsUpdate");
const responseType = api.slice(responseStart, responseEnd);
if (!responseType.includes("api_key_configured")) throw new Error("response must expose API key configured state");
if (/api_key\s*[:?]/.test(responseType)) throw new Error("response must never expose the API key");

for (const token of [
  "模型设置",
  "保存并应用",
  "测试连接",
  "恢复默认",
  "API Key",
  "最大输出长度",
  "请求超时时间",
  "每批评分题目数量",
  "已配置时不会回填，留空表示保持不变",
  "clear_api_key",
]) {
  if (!consolePage.includes(token)) throw new Error(`console copy/markup is missing: ${token}`);
}

for (const token of ["/console", "模型设置"]) {
  if (!homePage.includes(token)) throw new Error(`home page is missing console entry point: ${token}`);
}

for (const token of ["mint-console", "mint-settings-grid", "mint-status-pill", "mint-console-actions"]) {
  if (!css.includes(token)) throw new Error(`console styles are missing: ${token}`);
}

console.log("model console contract tests passed");
