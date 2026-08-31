import { parseSseBlock } from "./api";

const parsed = parseSseBlock(
  'event: stage\ndata: {"stage":"analyzing","message":"正在分析项目"}\n\n',
);

if (!parsed) {
  throw new Error("SSE stage block was empty");
}
const data = parsed.data as { stage?: string; message?: string };

if (parsed.event !== "stage" || data.stage !== "analyzing") {
  throw new Error("SSE stage block was not parsed");
}
