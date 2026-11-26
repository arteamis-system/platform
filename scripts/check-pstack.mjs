#!/usr/bin/env node
// Mechanical checks for local pstack (arteamis-method) wiring, zero agent hooks (PRD X-22),
// and internal reusable workflow ownership (`arteamis-system/platform`, never upstream
// `devsecops-playground-org/platform`). Every failure message states the fix.
//
//   node scripts/check-pstack.mjs          # exits 1 and prints every failure
import { existsSync, lstatSync, readFileSync, readdirSync, realpathSync } from "node:fs";
import { join, relative } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = fileURLToPath(new URL("..", import.meta.url));

const REQUIRED_HARNESS_FILES = [
  "AGENTS.md",
  "CLAUDE.md",
  ".agents/skills/arteamis-method/SKILL.md",
  ".claude/skills/arteamis-method/SKILL.md",
  "docs/agent-workflow.md",
  "Makefile",
];

function walkFiles(dir, predicate, out = [], seenDirs = new Set()) {
  if (!existsSync(dir)) return out;
  const realDir = realpathSync(dir);
  if (seenDirs.has(realDir)) return out;
  seenDirs.add(realDir);

  for (const name of readdirSync(dir)) {
    const path = join(dir, name);
    const stat = lstatSync(path);
    if (stat.isSymbolicLink()) {
      if (!existsSync(path)) continue;
      const targetReal = realpathSync(path);
      const targetStat = lstatSync(targetReal);
      if (targetStat.isDirectory()) walkFiles(path, predicate, out, seenDirs);
      else if (predicate(name)) out.push(path);
    } else if (stat.isDirectory()) {
      walkFiles(path, predicate, out, seenDirs);
    } else if (predicate(name)) {
      out.push(path);
    }
  }
  return out;
}

function containsHooksKey(value) {
  if (Array.isArray(value)) return value.some(containsHooksKey);
  if (value && typeof value === "object") {
    if (Object.hasOwn(value, "hooks")) return true;
    return Object.values(value).some(containsHooksKey);
  }
  return false;
}

const UPSTREAM_USES_RE = /^\s*(?:-\s*)?uses:\s*['"]?devsecops-playground-org\/platform\b/i;

export const RULES = [
  {
    id: "pstack-harness-files",
    source: "PRD P1-43: arteamis-method is wired for Claude Code, Codex, and Antigravity discovery",
    check(root) {
      return REQUIRED_HARNESS_FILES.filter((rel) => !existsSync(join(root, rel))).map(
        (rel) =>
          `Missing ${rel}. Fix: restore the local pstack/arteamis-method harness file so Claude Code, Codex, and Antigravity discover the method.`,
      );
    },
  },
  {
    id: "no-agent-hooks",
    source: "PRD X-22: plugin and agent hooks stay off",
    check(root) {
      const failures = [];
      const seenFiles = new Set();
      for (const dirName of [".agents", ".claude"]) {
        for (const file of walkFiles(join(root, dirName), (name) => name.endsWith(".json"))) {
          const realFile = realpathSync(file);
          if (seenFiles.has(realFile)) continue;
          seenFiles.add(realFile);
          const rel = relative(root, file);
          const text = readFileSync(file, "utf8");
          let hasHooks = /"hooks"\s*:/.test(text);
          if (!hasHooks) {
            try {
              hasHooks = containsHooksKey(JSON.parse(text));
            } catch {
              hasHooks = false;
            }
          }
          if (hasHooks) {
            failures.push(
              `${rel} declares a "hooks" key. Fix: delete the hooks key; plugin/agent hooks stay off (PRD X-22).`,
            );
          }
        }
      }
      return failures;
    },
  },
  {
    id: "no-upstream-workflow-uses",
    source: "AGENTS.md Changing the platform: every internal uses: points at arteamis-system/platform",
    check(root) {
      const failures = [];
      const yamlPredicate = (name) => name.endsWith(".yml") || name.endsWith(".yaml");
      const targets = [
        ...walkFiles(join(root, ".github/workflows"), yamlPredicate),
        ...walkFiles(join(root, "actions"), yamlPredicate),
      ];
      for (const file of targets) {
        const rel = relative(root, file);
        const lines = readFileSync(file, "utf8").split("\n");
        for (let i = 0; i < lines.length; i += 1) {
          const line = lines[i];
          if (line.trimStart().startsWith("#")) continue;
          if (UPSTREAM_USES_RE.test(line)) {
            failures.push(
              `${rel}:${i + 1} references upstream devsecops-playground-org/platform in uses:. Fix: rewrite to arteamis-system/platform pinned to a full 40-char commit SHA.`,
            );
          }
        }
      }
      return failures;
    },
  },
];

export function runChecks(root = ROOT) {
  return RULES.flatMap((rule) =>
    rule.check(root).map((message) => ({ rule: rule.id, message })),
  );
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  const failures = runChecks();
  for (const f of failures) console.error(`check-pstack [${f.rule}] ${f.message}`);
  console.log(`check-pstack: ${RULES.length} rules, ${failures.length} failure(s)`);
  process.exit(failures.length ? 1 : 0);
}
