#!/usr/bin/env python3
"""Resolve internal action/workflow pins before callers discover broken hashes."""

from pathlib import Path
import re
import subprocess
import sys

root = Path(__file__).resolve().parents[1]
pattern = re.compile(r"uses:\s*arteamis-system/platform/([^\s@]+)@([^\s#]+)")
errors = []
checked = 0
for path in sorted((root / ".github/workflows").glob("*.yml")):
    for number, line in enumerate(path.read_text().splitlines(), 1):
        match = pattern.search(line)
        if not match:
            continue
        target, revision = match.groups()
        if not re.fullmatch(r"[0-9a-f]{40}", revision):
            errors.append(f"{path.name}:{number}: internal reference must pin a full commit: {revision}")
            continue
        if not target.endswith((".yml", ".yaml")):
            target += "/action.yml"
        result = subprocess.run(["git", "cat-file", "-e", f"{revision}:{target}"],
                                cwd=root, capture_output=True)
        if result.returncode:
            errors.append(f"{path.name}:{number}: missing {target} at {revision}")
        checked += 1
print("\n".join(errors) if errors else f"Verified {checked} internal action/workflow pins")
sys.exit(bool(errors))
