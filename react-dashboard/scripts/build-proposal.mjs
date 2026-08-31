import { execFileSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const vite = path.resolve(root, "node_modules/.bin/vite");
const dist = path.resolve(root, ".proposal-dist");
const outputDir = path.resolve(root, "exports");
const output = path.resolve(outputDir, "ems-robust-client-proposal.html");

execFileSync(vite, ["build", "--config", "vite.proposal.config.js"], {
  cwd: root,
  stdio: "inherit",
});

let html = fs.readFileSync(path.resolve(dist, "proposal.html"), "utf8");
const stylesheet = html.match(/<link[^>]+href="([^"]+\.css)"[^>]*>/);
const script = html.match(/<script[^>]+src="([^"]+\.js)"[^>]*><\/script>/);
if (!stylesheet || !script) throw new Error("Vite proposal assets were not found in generated HTML.");

const assetPath = (reference) => path.resolve(dist, reference.replace(/^\//, ""));
const css = fs.readFileSync(assetPath(stylesheet[1]), "utf8");
const js = fs.readFileSync(assetPath(script[1]), "utf8");
const inlineJs = js.replace(/<\/script/gi, "<\\/script");
const originalHtml = html;
html = html.replace(stylesheet[0], () => `<style>${css}</style>`);
html = html.replace(script[0], () => `<script type="module">${inlineJs}</script>`);

const dependencyChecks = {
  assetsWereNotInlined: html === originalHtml,
  unsafeInlineScriptClosingTag: /<\/script/i.test(inlineJs),
  remoteCss: /@import\s+url\([^)]*https?:\/\/|url\(\s*["']?https?:\/\//i.test(css),
};
if (Object.values(dependencyChecks).some(Boolean)) {
  throw new Error(`Proposal export still contains an external runtime dependency: ${JSON.stringify(dependencyChecks)}`);
}

fs.mkdirSync(outputDir, { recursive: true });
fs.writeFileSync(output, html, "utf8");
fs.rmSync(dist, { recursive: true, force: true });
console.log(`Offline proposal: ${path.relative(root, output)}`);
