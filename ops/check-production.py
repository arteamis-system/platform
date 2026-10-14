#!/usr/bin/env python3
"""Read-only release checks; report metadata, never environment or message contents."""

import argparse
import json
import socket
import ssl
import subprocess
import time
import urllib.error
import urllib.request

REMOTE = r'''
import json, shutil, subprocess, time
result = {}
for name in ["arteamis-backend", "arteamis-worker", "arteamis-postgres"]:
    proc = subprocess.run(["docker", "inspect", name, "--format", "{{json .State}}"], capture_output=True, text=True)
    result[name] = json.loads(proc.stdout) if proc.returncode == 0 else {"Running": False}
disk = shutil.disk_usage("/mnt/arteamis_data")
result["disk_used_percent"] = round(100 * disk.used / disk.total, 1)
proc = subprocess.run(["sudo", "-n", "find", "/mnt/arteamis_data/backups", "-maxdepth", "1", "-type", "f", "-name", "pre-migrate-*", "-printf", "%T@\n"], capture_output=True, text=True)
times = [float(value) for value in proc.stdout.splitlines() if value.strip()]
result["backup_age_hours"] = round((time.time() - max(times)) / 3600, 1) if times else None
proc = subprocess.run(["docker", "ps", "--format", "{{.Names}} {{.Image}}"], capture_output=True, text=True)
result["standalone_plane_running"] = any("plane" in line.lower() for line in proc.stdout.splitlines())
print(json.dumps(result))
'''


def http_status(url):
    try:
        with urllib.request.urlopen(url, timeout=15) as response:
            return response.status
    except urllib.error.HTTPError as exc:
        return exc.code
    except (OSError, urllib.error.URLError):
        return None


def assess(remote, ready_status, tls_days):
    return {
        "api_ready": ready_status == 200,
        "api_container": remote.get("arteamis-backend", {}).get("Running", False),
        "worker_running": remote.get("arteamis-worker", {}).get("Running", False),
        "postgres_healthy": remote.get("arteamis-postgres", {}).get("Health", {}).get("Status") == "healthy",
        "data_disk_below_85_percent": remote.get("disk_used_percent", 100) < 85,
        "backup_within_24_hours": remote.get("backup_age_hours") is not None and remote["backup_age_hours"] <= 24,
        "tls_valid_for_14_days": tls_days is not None and tls_days >= 14,
        "standalone_plane_stopped": remote.get("standalone_plane_running") is False,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="arteamis-production")
    parser.add_argument("--api-host", default="api.arteamis.space")
    args = parser.parse_args()
    proc = subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10",
                           args.host, "python3", "-"], input=REMOTE, capture_output=True,
                          text=True, timeout=40)
    if proc.returncode:
        raise SystemExit("Could not obtain production metadata over SSH")
    remote = json.loads(proc.stdout)
    tls_days = None
    try:
        with socket.create_connection((args.api_host, 443), timeout=10) as connection:
            with ssl.create_default_context().wrap_socket(connection, server_hostname=args.api_host) as secured:
                expires = ssl.cert_time_to_seconds(secured.getpeercert()["notAfter"])
                tls_days = round((expires - time.time()) / 86400, 1)
    except (OSError, ssl.SSLError):
        pass
    ready_status = http_status(f"https://{args.api_host}/ready")
    checks = assess(remote, ready_status, tls_days)
    print(json.dumps({"checked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                      "checks": checks, "ready_status": ready_status, "tls_days": tls_days,
                      "disk_used_percent": remote["disk_used_percent"],
                      "backup_age_hours": remote["backup_age_hours"]}, indent=2))
    raise SystemExit(0 if all(checks.values()) else 1)


if __name__ == "__main__":
    main()
