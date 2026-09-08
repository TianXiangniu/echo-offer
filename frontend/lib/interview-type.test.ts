import { interviewEntry } from "./interview-type.ts";

if (interviewEntry("foundation").path !== "/interview") {
  throw new Error("foundation interviews should use the shared interview route");
}

if (interviewEntry("project").path !== "/project") {
  throw new Error("project interviews should use the project preparation route");
}

if (!interviewEntry("foundation").title.includes("基础")) {
  throw new Error("foundation copy should be explicit");
}

console.log("interview type tests passed");
