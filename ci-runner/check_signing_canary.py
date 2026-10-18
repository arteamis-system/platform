"""Run the reusable canary's real signing commands before spending on a VM.

The pinned CLI version must match the canary. A temporary throwaway key and a
hosted-runner environment exercise its offline signing proof without requesting
the controller parameter or any application credentials.
"""

import json
import os
from pathlib import Path
import subprocess
import tempfile

import yaml


def main():
    workflow = Path(__file__).resolve().parents[1] / ".github/workflows/ci-runner-canary.yml"
    steps = yaml.safe_load(workflow.read_text())["jobs"]["isolated"]["steps"]
    installer = next(step for step in steps if step.get("uses", "").startswith("sigstore/cosign-installer@"))
    version = json.loads(subprocess.check_output(["cosign", "version", "--json"], text=True))
    if version["gitVersion"] != installer["with"]["cosign-release"]:
        raise RuntimeError("Install the same pinned Cosign version as the reusable canary")
    script = next(step["run"] for step in steps if step.get("name") == "Throwaway signing and controller-secret denial")
    with tempfile.TemporaryDirectory(prefix="arteamis-signing-check-") as work:
        env = {**os.environ, "RUNNER_TEMP": work, "RUNNER_ENVIRONMENT": "github-hosted", "COSIGN_PASSWORD": ""}
        subprocess.run(["bash", "-euo", "pipefail", "-c", script], env=env, cwd=work, check=True)
        Path(work, "payload").write_text("modified payload")
        verify = next(line.strip() for line in script.splitlines() if line.strip().startswith("cosign verify-blob "))
        rejected = subprocess.run(["bash", "-euo", "pipefail", "-c", verify], env=env, cwd=work, capture_output=True)
        if rejected.returncode == 0:
            raise RuntimeError("Canary signature verification accepted a modified payload")
    print("Exact reusable-canary signing proof passed; modified payload rejected.")


if __name__ == "__main__":
    main()
