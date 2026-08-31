import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const projectRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const source = path.resolve(
  projectRoot,
  "../model_results/robust/annual_planning/presentation.json",
);
const destination = path.resolve(projectRoot, "src/data/ems-dashboard-data.json");
const requiredSections = [
  "meta",
  "executiveSummary",
  "strategyComparison",
  "monthlyComparison",
  "robustnessFrontier",
  "scenarioCoverage",
  "dailyDispatch",
  "billingBreakdown",
  "modelAssumptions",
];

if (!fs.existsSync(source)) {
  throw new Error(
    `Formal annual result is missing: ${source}. Run robust_ems.annual_plan before building the dashboard.`,
  );
}

const payload = JSON.parse(fs.readFileSync(source, "utf8"));
if (payload?.meta?.status !== "valid") {
  throw new Error(
    `Formal annual result is not valid (status: ${payload?.meta?.status ?? "missing"}). ` +
      "The dashboard will not substitute mock data.",
  );
}

for (const section of requiredSections) {
  if (!(section in payload)) {
    throw new Error(`Formal annual result is missing required section: ${section}`);
  }
}
if (payload.monthlyComparison.length !== 12) {
  throw new Error(`Expected 12 monthly results, received ${payload.monthlyComparison.length}.`);
}
for (let month = 1; month <= 12; month += 1) {
  if (!Array.isArray(payload.dailyDispatch[String(month)]) || !payload.dailyDispatch[String(month)].length) {
    throw new Error(`Representative dispatch days are missing for month ${month}.`);
  }
}

fs.mkdirSync(path.dirname(destination), { recursive: true });
fs.writeFileSync(destination, `${JSON.stringify(payload, null, 2)}\n`, "utf8");
console.log(`Dashboard data: ${path.relative(projectRoot, source)} -> ${path.relative(projectRoot, destination)}`);
