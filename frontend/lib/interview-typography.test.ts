import { readFileSync } from "node:fs";

const css = readFileSync(new URL("../app/globals.css", import.meta.url), "utf8");
const match = css.match(/\.mint-question-title\s*\{([^}]+)\}/);

if (!match) throw new Error("missing interview question title styles");
const declaration = match[1];
if (declaration.includes("58px")) throw new Error("interview question title is still oversized");
for (const token of ["clamp(27px, 3vw, 40px)", "line-height: 1.25", "letter-spacing: -0.04em"]) {
  if (!declaration.includes(token)) throw new Error(`missing typography token: ${token}`);
}
