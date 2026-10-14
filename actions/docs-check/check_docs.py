#!/usr/bin/env python3
"""Check a documentation repository's structure. Standard library only.

Reads `.docscheck.json` from the repository root:

    {
      "exempt": ["README.md", "AGENTS.md", "CLAUDE.md"],     # names with no front matter
      "skip_dirs": ["templates"],                            # not checked at all
      "required": ["title", "status", "owner", "last_reviewed"],
      "statuses": ["draft", "in-review", "accepted", "superseded"],
      "decisions": {"dir": "decisions", "id_prefix": "PDR-",
                    "required": ["id", "date"],
                    "statuses": ["proposed", "accepted", "superseded", "rejected"]},
      "indexed": true,                                       # every document is linked from a README.md
      "requirement_index": {"file": "prd/README.md", "id_pattern": "F-\\\\d{2,}",
                            "statuses": ["Built", "Implemented", "Partial", "Planned",
                                         "Proposed", "Declined", "Superseded"]}
    }

Checks:
- every document (other than exempt names) starts with front matter carrying the
  required fields, a known status and ISO dates;
- decision records carry an id matching their file number, unique across the folder;
- relative links resolve to files inside the repository (links that leave the
  repository, such as a sibling repository, are not checkable here and are skipped);
- every document is linked from some README.md, so the index stays complete;
- requirement ids in the index are unique and their status is a known value.

Exit status 1 lists every problem found, one per line, as GitHub annotations.
"""

from __future__ import annotations

from datetime import date
import json
import re
import sys
from pathlib import Path

ROOT = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
CONFIG = json.loads((ROOT / ".docscheck.json").read_text())
EXEMPT = set(CONFIG.get("exempt", ["README.md", "AGENTS.md", "CLAUDE.md"]))
SKIP = set(CONFIG.get("skip_dirs", []))
DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
LINK = re.compile(r"(?<!!)\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
problems: list[str] = []


def problem(path: Path, message: str, line: int | None = None) -> None:
    where = f"file={path.relative_to(ROOT)}" + (f",line={line}" if line else "")
    problems.append(f"::error {where}::{message}")


def documents() -> list[Path]:
    found = []
    for path in sorted(ROOT.rglob("*.md")):
        rel = path.relative_to(ROOT)
        if rel.parts[0].startswith(".") or rel.parts[0] in SKIP or "node_modules" in rel.parts:
            continue
        found.append(path)
    return found


def front_matter(path: Path) -> dict[str, str] | None:
    text = path.read_text()
    if not text.startswith("---\n"):
        return None
    end = text.find("\n---\n", 4)
    if end < 0:
        return None
    fields = {}
    for line in text[4:end].splitlines():
        if not line.strip() or line.lstrip().startswith("#") or ":" not in line:
            continue
        key, _, value = line.partition(":")
        value = value.split(" #", 1)[0].strip().strip("'\"")
        fields[key.strip()] = value
    return fields


docs = documents()
decisions_cfg = CONFIG.get("decisions")
decision_ids: dict[str, Path] = {}

for path in docs:
    if path.name in EXEMPT:
        continue
    fields = front_matter(path)
    if fields is None:
        problem(path, "missing YAML front matter")
        continue
    in_decisions = decisions_cfg and path.relative_to(ROOT).parts[0] == decisions_cfg["dir"]
    required = list(CONFIG.get("required", []))
    statuses = CONFIG.get("statuses")
    if in_decisions and re.match(r"^\d{4}-", path.name):
        required += decisions_cfg.get("required", [])
        statuses = decisions_cfg.get("statuses", statuses)
        number = path.name[:4]
        expected = f"{decisions_cfg.get('id_prefix', '')}{number}"
        if fields.get("id") != expected:
            problem(path, f"decision id must be {expected}, found {fields.get('id')!r}")
        elif expected in decision_ids:
            problem(path, f"duplicate decision id {expected} (also {decision_ids[expected].relative_to(ROOT)})")
        else:
            decision_ids[expected] = path
    for key in required:
        if not fields.get(key):
            problem(path, f"front matter is missing '{key}'")
    if statuses and fields.get("status") and fields["status"] not in statuses:
        problem(path, f"status '{fields['status']}' is not one of {', '.join(statuses)}")
    for key in ("last_reviewed", "date"):
        if fields.get(key):
            try:
                if not DATE.fullmatch(fields[key]):
                    raise ValueError
                date.fromisoformat(fields[key])
            except ValueError:
                problem(path, f"'{key}' must be a valid YYYY-MM-DD date, found {fields[key]!r}")

linked: set[Path] = set()
for path in docs:
    for number, line in enumerate(path.read_text().splitlines(), 1):
        for target in LINK.findall(line):
            if re.match(r"^[a-z][a-z0-9+.-]*:", target) or target.startswith("#"):
                continue
            file_part = target.split("#", 1)[0]
            if not file_part:
                continue
            resolved = (path.parent / file_part).resolve()
            try:
                resolved.relative_to(ROOT)
            except ValueError:
                continue  # leaves this repository: not checkable here
            if not resolved.exists():
                problem(path, f"broken link: {target}", number)
            elif path.name == "README.md":
                linked.add(resolved)

if CONFIG.get("indexed"):
    for path in docs:
        if path.name in EXEMPT:
            continue
        if path not in linked:
            problem(path, "not linked from any README.md index")

req = CONFIG.get("requirement_index")
if req:
    index = ROOT / req["file"]
    seen: dict[str, int] = {}
    id_re = re.compile(rf"^\|\s*({req['id_pattern']})\s*\|")
    header: list[str] | None = None
    for number, line in enumerate(index.read_text().splitlines(), 1):
        if line.startswith("|") and not re.match(r"^\|\s*-", line):
            cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
            match = id_re.match(line)
            if not match:
                header = cells
                continue
            rid = match.group(1)
            if rid in seen:
                problem(index, f"requirement {rid} is listed twice (also line {seen[rid]})", number)
            seen[rid] = number
            if header and "Status" in header and len(cells) == len(header):
                status = re.sub(r"[*_`]", "", cells[header.index("Status")]).split(" ")[0].rstrip(",;.")
                if status and status not in req["statuses"]:
                    problem(index, f"requirement {rid} has unknown status '{status}'", number)
        else:
            header = None if not line.startswith("|") else header
    if not seen:
        problem(index, "requirement index contains no matching requirement ids; check id_pattern")

for line in problems:
    print(line)
print(f"docs-check: {len(docs)} documents, {len(problems)} problem(s)")
sys.exit(1 if problems else 0)
