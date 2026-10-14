#!/usr/bin/env python3
"""Check the normalized, secret-free production Compose release contract."""

import json
import sys

stack = json.load(open(sys.argv[1]))
services = stack["services"]
order = ["postgres", "db-bootstrap", "db-backup", "db-migrate", "db-finalize", "backend", "worker"]
for before, after in zip(order, order[1:]):
    condition = "service_healthy" if before in {"postgres", "backend"} else "service_completed_successfully"
    assert services[after]["depends_on"][before]["condition"] == condition, f"{after} must wait for {before}"
for name in ("backend", "db-migrate", "worker"):
    assert [value["path"] for value in services[name]["env_file"]] == [".env"], f"{name} may not receive infrastructure credentials"
for name in ("postgres", "db-bootstrap", "db-backup", "db-finalize"):
    assert ".env.infra" in [value["path"] for value in services[name]["env_file"]]
assert services["db-backup"]["environment"]["BACKUP_REQUIRED"] == "true"
assert "/ready" in str(services["backend"]["healthcheck"]["test"])
assert "start_ready_worker.py" in str(services["worker"]["command"])
assert stack["volumes"]["pgcluster"]["driver_opts"]["device"] == "/mnt/arteamis_data/pgcluster"
assert "pgdata" not in stack["volumes"], "the old cluster remains outside the new stack for rollback"
assert services["postgres"]["environment"]["POSTGRES_USER"] == "postgres"
images = {services[name]["image"] for name in order if name != "postgres"}
assert len(images) == 1, "every helper, API and worker must use the same release image"
print("Production assembly: phase order, backup gate, credential isolation, readiness and preserved old cluster pass")
