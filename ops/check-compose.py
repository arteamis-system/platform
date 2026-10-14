#!/usr/bin/env python3
"""Check the normalized, secret-free production Compose release contract."""

import json
from pathlib import PurePath
import sys

stack = json.load(open(sys.argv[1]))
services = stack["services"]
def env_files(service):
    return [PurePath(value["path"] if isinstance(value, dict) else value).name for value in service["env_file"]]


order = ["postgres", "db-bootstrap", "db-backup", "db-migrate", "db-finalize", "backend", "worker"]
for before, after in zip(order, order[1:]):
    condition = "service_healthy" if before in {"postgres", "backend"} else "service_completed_successfully"
    assert services[after]["depends_on"][before]["condition"] == condition, f"{after} must wait for {before}"
for name in ("backend", "db-migrate", "worker"):
    assert env_files(services[name]) == [".env"], f"{name} may not receive infrastructure credentials"
for name in ("postgres", "db-bootstrap", "db-backup", "db-finalize"):
    assert ".env.infra" in env_files(services[name])
assert services["db-backup"]["environment"]["BACKUP_REQUIRED"] == "true"
assert "/ready" in str(services["backend"]["healthcheck"]["test"])
assert "start_ready_worker.py" in str(services["worker"]["command"])
assert stack["volumes"]["pgcluster"]["driver_opts"]["device"] == "/mnt/arteamis_data/pgcluster"
assert "pgdata" not in stack["volumes"], "the old cluster remains outside the new stack for rollback"
assert services["postgres"]["environment"]["POSTGRES_USER"] == "postgres"
images = {services[name]["image"] for name in order if name != "postgres"}
assert len(images) == 1, "every helper, API and worker must use the same release image"
print("Production assembly: phase order, backup gate, credential isolation, readiness and preserved old cluster pass")
