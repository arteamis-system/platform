import assert from "node:assert/strict";
import { mkdirSync, mkdtempSync, rmSync, symlinkSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

import { runChecks } from "./check-pstack.mjs";

function makeValidRepo() {
  const root = mkdtempSync(join(tmpdir(), "platform-pstack-test-"));
  mkdirSync(join(root, ".agents/skills/arteamis-method"), { recursive: true });
  mkdirSync(join(root, ".claude/skills"), { recursive: true });
  mkdirSync(join(root, "docs"), { recursive: true });
  mkdirSync(join(root, ".github/workflows"), { recursive: true });
  mkdirSync(join(root, "actions/sample"), { recursive: true });

  writeFileSync(join(root, "AGENTS.md"), "# platform\n");
  writeFileSync(join(root, "CLAUDE.md"), "@AGENTS.md\n");
  writeFileSync(join(root, "Makefile"), ".PHONY: check verify\n");
  writeFileSync(join(root, "docs/agent-workflow.md"), "# Agent workflow\n");
  writeFileSync(
    join(root, ".agents/skills/arteamis-method/SKILL.md"),
    "---\nname: arteamis-method\ndescription: test\n---\n",
  );
  symlinkSync(
    "../../.agents/skills/arteamis-method",
    join(root, ".claude/skills/arteamis-method"),
  );
  writeFileSync(
    join(root, ".github/workflows/_dispatch.yml"),
    "jobs:\n  test:\n    uses: arteamis-system/platform/.github/workflows/ci-test.yml@0123456789abcdef0123456789abcdef01234567\n",
  );
  return root;
}

test("current platform repository passes all pstack checks", () => {
  assert.deepEqual(runChecks(), []);
});

test("valid synthetic repository passes all pstack checks", () => {
  const root = makeValidRepo();
  try {
    assert.deepEqual(runChecks(root), []);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test("missing required harness files fail with actionable messages", () => {
  const root = makeValidRepo();
  try {
    rmSync(join(root, "docs/agent-workflow.md"));
    rmSync(join(root, ".claude/skills/arteamis-method"), { recursive: true, force: true });
    const failures = runChecks(root);
    assert.equal(failures.length, 2);
    assert.ok(failures.every((f) => f.rule === "pstack-harness-files"));
    assert.match(failures.map((f) => f.message).join("\n"), /docs\/agent-workflow\.md/);
    assert.match(
      failures.map((f) => f.message).join("\n"),
      /\.claude\/skills\/arteamis-method\/SKILL\.md/,
    );
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test("hooks key in JSON under .agents/ or .claude/ is rejected (PRD X-22)", () => {
  const root = makeValidRepo();
  try {
    writeFileSync(join(root, ".agents/clean.json"), '{"name": "ok"}\n');
    assert.deepEqual(runChecks(root), []);

    writeFileSync(join(root, ".claude/settings.json"), '{"hooks": {"PreToolUse": []}}\n');
    const failures = runChecks(root);
    assert.equal(failures.length, 1);
    assert.equal(failures[0].rule, "no-agent-hooks");
    assert.match(failures[0].message, /PRD X-22/);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test("internal workflow uses pointing at devsecops-playground-org/platform is rejected", () => {
  const root = makeValidRepo();
  try {
    writeFileSync(
      join(root, ".github/workflows/bad.yml"),
      "jobs:\n  bad:\n    uses: devsecops-playground-org/platform/.github/workflows/ci-test.yml@main\n",
    );
    writeFileSync(
      join(root, "actions/sample/action.yml"),
      "runs:\n  steps:\n    - uses: devsecops-playground-org/platform/actions/setup-runtime@v1\n",
    );
    const failures = runChecks(root);
    assert.equal(failures.length, 2);
    assert.ok(failures.every((f) => f.rule === "no-upstream-workflow-uses"));
    assert.match(failures.map((f) => f.message).join("\n"), /arteamis-system\/platform/);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});
