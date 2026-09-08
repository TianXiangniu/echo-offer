import {
  interviewEntry,
  interviewEntryPath,
  interviewRecordTitle,
  interviewTypeLabel,
} from "./interview-type.ts";

if (interviewEntry("foundation").path !== "/") {
  throw new Error("foundation interviews should return to the mode chooser");
}

if (interviewEntry("project").path !== "/project") {
  throw new Error("project interviews should use the project preparation route");
}

if (!interviewEntry("foundation").title.includes("基础")) {
  throw new Error("foundation copy should be explicit");
}

if (interviewEntryPath("project") !== "/project") {
  throw new Error("project should return to project preparation");
}

if (interviewRecordTitle("foundation", null) !== "大模型基础面试") {
  throw new Error("foundation history must not show unnamed project");
}

if (interviewRecordTitle("project", "DeepResearch") !== "DeepResearch") {
  throw new Error("project history must prefer the project name");
}

if (interviewTypeLabel("project") !== "项目经历面试") {
  throw new Error("project mode label should be conversational");
}

console.log("interview type tests passed");
