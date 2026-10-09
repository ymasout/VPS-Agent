// Inspect the actual standalone image, including pnpm symlink targets.
// This guard does not waive source dependency vulnerability findings.
import { readdirSync, readFileSync, realpathSync, statSync } from "node:fs";
import { join } from "node:path";

const root = process.argv[2] || "/app";
const forbidden = new Set([
  "braces", "micromatch", "fast-glob", "eslint", "@next/eslint-plugin-next",
]);
const visited = new Set();
const findings = [];
let manifests = 0;

function inspect(path) {
  const resolved = realpathSync(path);
  if (visited.has(resolved)) return;
  visited.add(resolved);
  if (!statSync(resolved).isDirectory()) return;
  for (const entry of readdirSync(resolved, { withFileTypes: true })) {
    const child = join(resolved, entry.name);
    if (entry.name === "package.json" && entry.isFile()) {
      const pkg = JSON.parse(readFileSync(child, "utf8"));
      manifests += 1;
      if (forbidden.has(pkg.name)) findings.push(`${pkg.name}@${pkg.version}: ${child}`);
    } else if (entry.isDirectory() || entry.isSymbolicLink()) {
      inspect(child);
    }
  }
}

// Fail closed for a wrong/empty target or an unreadable/broken package tree.
if (!statSync(join(root, "apps/web/server.js")).isFile()) {
  throw new Error("Standalone server entry is missing");
}
inspect(root);
if (manifests === 0) throw new Error("No package manifests inspected");
if (findings.length) {
  throw new Error(`Development dependency found in runtime:\n${findings.join("\n")}`);
}
console.log(`WEB_RUNTIME_DEV_DEPENDENCIES_ABSENT: ${manifests} package manifests inspected`);
