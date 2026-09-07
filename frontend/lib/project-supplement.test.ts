import { getMissingInformationPrompts } from "./ui-copy.ts";

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

console.log("project supplement prompt tests passed");
