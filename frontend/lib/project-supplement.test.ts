import { readFileSync } from "node:fs";
import * as uiCopy from "./ui-copy.ts";

const homePage = readFileSync(new URL("../app/page.tsx", import.meta.url), "utf8");

const getMissingInformationPrompts = (uiCopy as {
  getMissingInformationPrompts?: (items: string[]) => string[];
}).getMissingInformationPrompts;

if (typeof getMissingInformationPrompts !== "function") {
  throw new Error("missing_information prompt mapper is missing");
}

const supplementPrompts = getMissingInformationPrompts([
  "context.stage",
  "ownership.owned_modules",
  "evaluation.metrics",
  "engineering.output_safety",
  "可信边界模型",
]);

const expectedPrompts = [
  "项目做到什么阶段了？",
  "哪些部分是你亲自完成的？",
  "最后效果怎么样？有数据吗？",
];

if (JSON.stringify(supplementPrompts) !== JSON.stringify(expectedPrompts)) {
  throw new Error(`unexpected supplement prompts: ${JSON.stringify(supplementPrompts)}`);
}

const scalePrompt = getMissingInformationPrompts(["缺少明确的线上流量规模"]);
if (scalePrompt[0] !== "这个项目实际服务了多大规模？") {
  throw new Error(`missing_information fallback prompt is not natural: ${JSON.stringify(scalePrompt)}`);
}

if (!homePage.includes("getMissingInformationPrompts(")) {
  throw new Error("home page is not mapping missing_information through friendly supplement prompts");
}

if (homePage.includes('analysisResult.missing_information.join("；")')) {
  throw new Error("home page still renders raw missing_information text");
}
