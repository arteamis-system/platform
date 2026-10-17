"""Prepare/check routing without changing validation steps or publication guards."""

import argparse
from pathlib import Path

import yaml
from controller import SELECTOR

PROBE = """name: GitHub hosted availability
run-name: Arteamis hosted probe ${{ inputs.nonce }}

on:
  workflow_dispatch:
    inputs:
      nonce:
        description: Controller correlation identifier
        required: true
        type: string

permissions: {}

jobs:
  available:
    runs-on: ubuntu-24.04
    timeout-minutes: 2
    steps:
      - run: echo 'GitHub-hosted runner available'
"""


def prepare(path):
    original = path.read_text()
    parsed = yaml.safe_load(original)
    if not isinstance(parsed.get("jobs"), dict):
        raise ValueError(f"No jobs in {path}")
    lines = original.splitlines(keepends=True)
    replacements = 0
    for key, job in parsed["jobs"].items():
        if job.get("runs-on") == "macos-15":
            continue
        if "runs-on" not in job:
            continue
        if job["runs-on"] not in ("ubuntu-latest", "ubuntu-24.04", SELECTOR):
            raise ValueError(f"Unexpected runner selector in {path}: {key}")
        start = lines.index("  " + key + ":\n")
        end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("  ") and not lines[i].startswith("   ") and lines[i].strip()), len(lines))
        runner = next(i for i in range(start, end) if lines[i].startswith("    runs-on:"))
        if job["runs-on"] in ("ubuntu-latest", "ubuntu-24.04"):
            lines[runner] = "    runs-on: " + SELECTOR + "\n"
            replacements += 1
        if "timeout-minutes" not in job:
            lines.insert(runner + 1, "    timeout-minutes: 45\n")
    return "".join(lines), replacements


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("check", "apply"))
    parser.add_argument("--workspace-root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--repository", action="append")
    args = parser.parse_args()
    for name in ("platform", "backend", "web", "desktop", "landing", "product"):
        if args.repository and name not in args.repository:
            continue
        root = args.workspace_root / name
        for path in sorted((root / ".github/workflows").glob("*.yml")):
            if path.name == "ci-hosted-probe.yml":
                continue
            if not path.exists():
                raise ValueError(f"Missing workflow: {path}")
            replacement, _ = prepare(path)
            if args.command == "apply":
                path.write_text(replacement)
            else:
                parsed = yaml.safe_load(path.read_text())
                for key, job in parsed["jobs"].items():
                    if job.get("runs-on") == "macos-15":
                        continue
                    if "runs-on" in job and (job["runs-on"] != SELECTOR or int(job.get("timeout-minutes", 360)) > 45):
                        raise ValueError(f"Missing or unbounded routing: {path}:{key}")
        if name == "desktop":
            print(name + ": macOS selectors preserved")
            continue
        probe = root / ".github/workflows/ci-hosted-probe.yml"
        if args.command == "apply":
            if probe.exists() and probe.read_text() != PROBE:
                raise ValueError(f"Preserve existing probe: {probe}")
            probe.write_text(PROBE)
        elif probe.read_text() != PROBE:
            raise ValueError(f"Unexpected availability probe: {probe}")
        print(name + ": routing and fixed hosted probe " + args.command)


if __name__ == "__main__":
    main()
