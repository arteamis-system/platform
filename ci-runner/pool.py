"""Two-slot ephemeral EC2 pool. Instances receive only their one-use JIT config."""

import collections
import datetime as dt
import hashlib
import json
import shlex
import uuid

from controller import PREFIX, ApiError, audit, aws_labels

FILTERS = [{"Name": "tag:ArteamisCiPool", "Values": ["arteamis-ci"]},
           {"Name": "tag:ArteamisCiRole", "Values": ["runner"]}]
ACTIVE = {"pending", "running", "stopping", "stopped"}
LIFETIME = 5400


def supply_key(repo, queued, progress=None):
    # Repository JIT registration supplies capacity, not a binding to one job.
    # Progress in any queued job must allow capacity for the remaining queue.
    job_ids = sorted({job_id for _, repository, job_id, _ in queued if repository == repo})
    revision = hashlib.sha256(json.dumps(job_ids if progress is None else {"jobs": job_ids, "served": progress}).encode()).hexdigest()
    return f"supply-queue:{repo}:{revision}"


def completed_progress(gh, repo, history, since, now):
    # Repo-level JIT runners can serve a superseded job outside this queue.
    # Only a completed GitHub job on a positively identified terminated VM
    # renews the two-attempt bound; missing instances or failed boots do not.
    names = {tags(item).get("ArteamisCiRunner"): item for item in history
             if item["State"]["Name"] == "terminated" and tags(item).get("ArteamisCiRepository") == repo
             and tags(item).get("ArteamisCiRunner", "").startswith(PREFIX)
             and item["LaunchTime"].timestamp() >= now - LIFETIME}
    if not names:
        return None
    created = dt.datetime.fromtimestamp(now - 86400, dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    proofs = []
    def timestamp(value):
        try:
            return dt.datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
        except (AttributeError, TypeError, ValueError):
            return 0
    for run in gh.pages(repo, "/actions/runs?status=completed&created=%3E%3D" + created, "workflow_runs"):
        if timestamp(run.get("updated_at")) <= since:
            continue
        for job in gh.pages(repo, f"/actions/runs/{run['id']}/jobs?filter=all", "jobs"):
            name = job.get("runner_name")
            if (name in names and job.get("status") == "completed" and job.get("runner_id")
                    and job.get("steps") and isinstance(job.get("id"), int)
                    and timestamp(job.get("completed_at")) > since
                    and timestamp(job.get("started_at")) >= names[name]["LaunchTime"].timestamp()):
                proofs.append({"runner": name, "job_id": job["id"], "run_id": run["id"],
                               "completed_at": job["completed_at"], "instance_id": names[name]["InstanceId"]})
    return max(proofs, key=lambda row: (timestamp(row["completed_at"]), row["job_id"])) if proofs else None


def tags(instance):
    return {t["Key"]: t["Value"] for t in instance.get("Tags", [])}


def instances(ec2, filters=None):
    result = []
    for page in ec2.get_paginator("describe_instances").paginate(Filters=FILTERS if filters is None else filters):
        result.extend(i for r in page["Reservations"] for i in r["Instances"])
    return result


def expired(instance, now):
    if instance["State"]["Name"] not in ACTIVE:
        return False
    launch = int(instance["LaunchTime"].timestamp())
    try:
        deadline = min(int(tags(instance)["ArteamisCiExpires"]), launch + LIFETIME)
    except (KeyError, ValueError):
        deadline = launch + LIFETIME
    return now >= deadline or instance["State"]["Name"] in ("stopping", "stopped")


def user_data(jit):
    # Never use shell tracing. A job cannot retrieve the controller App key.
    script = """#!/usr/bin/env bash
set -euo pipefail
trap '/sbin/shutdown -h now' EXIT
test -x /opt/arteamis-runner/run.sh
cd /opt/arteamis-runner
timeout --signal=TERM --kill-after=30s 4800s runuser -u ubuntu -- ./run.sh --jitconfig """ + shlex.quote(jit) + "\n"
    # boto3 encodes UserData itself; give it the shell script directly.
    return script


class Pool:
    def __init__(self, ec2, launch_template, version="1", repositories=()):
        self.ec2, self.launch_template = ec2, launch_template
        self.version, self.repositories = str(version), set(repositories)

    def status(self, state):
        # Operator diagnostics expose only public CI capacity, never JIT/App data.
        fields = {"repo", "created_at", "phase", "name", "instance_id", "runner_id", "launch_error_code"}
        return {"slots": [{"slot": slot, **{key: value for key, value in state.get(f"slot:{slot}").items() if key in fields}}
                          for slot in range(2)],
                "instances": [{"id": item["InstanceId"], "state": item["State"]["Name"]}
                              for item in instances(self.ec2) if item["State"]["Name"] in ACTIVE | {"shutting-down"}]}

    def remove_runner(self, gh, repo, runner_id):
        try:
            gh.call(repo, "DELETE", f"/actions/runners/{runner_id}")
        except ApiError as error:
            if error.status != 404:
                raise

    def reconcile(self, gh, state, now):
        observed = instances(self.ec2)
        recorded_repos = {state.get(f"slot:{slot}").get("repo") for slot in range(2)} - {None}
        active = [i for i in observed if i["State"]["Name"] in ACTIVE]
        registered, runs = {}, {}
        for instance in active:
            if expired(instance, now):
                self.ec2.terminate_instances(InstanceIds=[instance["InstanceId"]])
                audit("expired-vm-terminated", instance_id=instance["InstanceId"])
                continue
            info = tags(instance)
            repo, run_id = info.get("ArteamisCiRepository", ""), info.get("ArteamisCiRun", "")
            if (not repo.startswith("arteamis-system/") or not run_id.isdigit()
                    or (self.repositories and repo not in self.repositories)):
                continue
            if repo not in registered:
                registered[repo] = {r["name"]: r for r in gh.pages(repo, "/actions/runners", "runners")}
            runner = registered[repo].get(info.get("ArteamisCiRunner"))
            # Queue snapshots can race assignment. Never retain a spare VM for
            # a terminal run, but require positive non-busy registration before
            # terminating early; missing registration alone proves nothing.
            if runner is not None and runner.get("busy") is False:
                key = (repo, int(run_id))
                if key not in runs:
                    try:
                        runs[key] = gh.call(repo, "GET", f"/actions/runs/{run_id}")
                    except ApiError as error:
                        if error.status != 404:
                            raise
                        runs[key] = {}
                if runs[key].get("id") == int(run_id) and runs[key].get("status") == "completed":
                    self.ec2.terminate_instances(InstanceIds=[instance["InstanceId"]])
                    audit("completed-run-idle-vm-terminated", repo=repo, run_id=int(run_id), instance_id=instance["InstanceId"])
        for slot in range(2):
            key = f"slot:{slot}"
            record = state.get(key)
            if not record:
                continue
            matches = [i for i in observed if i.get("ClientToken") == record["client_token"]]
            running = [i for i in matches if i["State"]["Name"] in ACTIVE | {"shutting-down"}]
            if running:
                # Reconcile a response lost after EC2 accepted RunInstances.
                if record.get("instance_id") != running[0]["InstanceId"]:
                    state.put(key, {**record, "instance_id": running[0]["InstanceId"], "phase": "active"})
                continue
            # A missing DescribeInstances result cannot prove rejection of a
            # timed-out launch. Hold that slot until positive evidence arrives.
            if not matches:
                if record.get("phase") in ("launching", "ambiguous") or now - record["created_at"] < 600:
                    continue
            if record.get("runner_id"):
                self.remove_runner(gh, record["repo"], record["runner_id"])
            state.delete(key)
            audit("slot-cleaned", slot=slot)
        # Clean offline registrations left by a failed boot or a lost slot write.
        active_names = {tags(i).get("ArteamisCiRunner") for i in active}
        reserved_names = {state.get(f"slot:{slot}").get("name") for slot in range(2)}
        for repo in recorded_repos | ({tags(i).get("ArteamisCiRepository") for i in observed} - {None}):
            if not repo.startswith("arteamis-system/"):
                continue
            if self.repositories and repo not in self.repositories:
                continue
            for runner in gh.pages(repo, "/actions/runners", "runners"):
                if (runner["name"].startswith(PREFIX) and runner["name"] not in active_names | reserved_names
                        and runner["status"] == "offline" and not runner.get("busy")):
                    self.remove_runner(gh, repo, runner["id"])

    def fulfill(self, gh, state, queued, maximum, now):
        history = instances(self.ec2)
        observed = [i for i in history if i["State"]["Name"] in ACTIVE | {"shutting-down"}]
        reserved = {slot: state.get(f"slot:{slot}") for slot in range(maximum)}
        occupied = {slot for slot, record in reserved.items() if record}
        # An orphan occupies capacity too. Never assume a missing state item
        # means an EC2 instance does not exist.
        live_tokens = {i.get("ClientToken") for i in observed}
        reserved_only = sum(1 for r in reserved.values() if r and r["client_token"] not in live_tokens)
        capacity = maximum - len(observed) - reserved_only
        idle = collections.Counter()
        for repo in {repo for _, repo, _, _ in queued}:
            runners = {r["name"]: r for r in gh.pages(repo, "/actions/runners", "runners")}
            for instance in observed:
                info = tags(instance)
                if info.get("ArteamisCiRepository") != repo:
                    continue
                runner = runners.get(info.get("ArteamisCiRunner"))
                if runner is None or not runner.get("busy"):
                    idle[(repo, tags(instance).get("ArteamisCiRun"))] += 1
        launched = 0
        checked_progress = set()
        for _, repo, job_id, run_id in queued:
            if idle[(repo, str(run_id))]:
                idle[(repo, str(run_id))] -= 1
                continue
            if capacity <= 0:
                break
            # Re-read immediately before admitting supply. A runner may have
            # started/completed this job since Controller collected its queue.
            current = gh.call(repo, "GET", f"/actions/jobs/{job_id}")
            if (current.get("status") != "queued" or current.get("run_id") != run_id
                    or set(current.get("labels", [])) != set(aws_labels(run_id))):
                continue
            progress = state.get("pool-progress:" + repo).get("runner")
            demand_key = supply_key(repo, queued, progress)
            supply = state.get(demand_key)
            attempts = int(supply.get("attempts", 0))
            if attempts >= 2 and repo not in checked_progress:
                checked_progress.add(repo)
                proof = completed_progress(gh, repo, history, supply.get("last_attempt_at", now), now)
                if proof and proof["runner"] != progress:
                    state.put("pool-progress:" + repo, proof)
                    audit("vm-queue-progress", repo=repo, **proof)
                    demand_key = supply_key(repo, queued, proof["runner"])
                    supply = state.get(demand_key)
                    attempts = int(supply.get("attempts", 0))
            if attempts >= 2:
                audit("vm-launch-limit", repo=repo, job_id=job_id, attempts=attempts)
                continue
            free = next((s for s in range(maximum) if s not in occupied
                         and not any(tags(i).get("ArteamisCiSlot") == str(s) for i in observed)), None)
            if free is None:
                break
            token = uuid.uuid4().hex
            name = PREFIX + token
            record = {"repo": repo, "created_at": now, "client_token": token, "name": name, "phase": "registering"}
            if not state.claim(f"slot:{free}", record):
                continue
            occupied.add(free)
            capacity -= 1
            # A failed boot must not cause an endless chain of replacements.
            # Persist before registration or EC2; ambiguous outcomes count too.
            state.put(demand_key, {"attempts": attempts + 1, "last_attempt_at": now})
            launch_sent = False
            try:
                jit = gh.call(repo, "POST", "/actions/runners/generate-jitconfig",
                              {"name": name, "runner_group_id": 1,
                               "labels": aws_labels(run_id), "work_folder": "_work"})
                record = {**record, "runner_id": jit["runner"]["id"], "phase": "launching"}
                state.put(f"slot:{free}", record)
                info = {"Name": name, "ArteamisCiPool": "arteamis-ci", "ArteamisCiRole": "runner", "ArteamisCiSlot": str(free),
                        "ArteamisCiRepository": repo, "ArteamisCiRun": str(run_id), "ArteamisCiRunner": name, "ArteamisCiRunnerId": str(record["runner_id"]),
                        "ArteamisCiExpires": str(now + LIFETIME)}
                launch_sent = True
                result = self.ec2.run_instances(
                    LaunchTemplate={"LaunchTemplateId": self.launch_template, "Version": self.version},
                    MinCount=1, MaxCount=1, ClientToken=token, UserData=user_data(jit["encoded_jit_config"]),
                    TagSpecifications=[{"ResourceType": kind, "Tags": [{"Key": k, "Value": v} for k, v in info.items()]}
                                       for kind in ("instance", "volume")],
                )
                state.put(f"slot:{free}", {**record, "phase": "active", "instance_id": result["Instances"][0]["InstanceId"]})
                launched += 1
                audit("vm-launched", repo=repo, job_id=job_id, slot=free, instance_id=result["Instances"][0]["InstanceId"])
            except Exception as error:
                # Definite pre-launch errors are safe to clean. Unknown launch
                # outcomes keep capacity reserved, including after ten minutes.
                code = getattr(error, "response", {}).get("Error", {}).get("Code")
                rejected = code in ("UnauthorizedOperation", "AuthFailure", "InvalidParameterValue",
                                    "InvalidAMIID.NotFound", "InsufficientInstanceCapacity", "InstanceLimitExceeded")
                phase = "launch-rejected" if not launch_sent or rejected else "ambiguous"
                state.put(f"slot:{free}", {**record, "phase": phase, "launch_error_code": code})
                audit("vm-launch-error", repo=repo, slot=free, error=type(error).__name__, code=code)
        if queued and capacity <= 0:
            audit("queue-at-capacity", queued_jobs=len(queued), maximum=maximum)
        return {"launched": launched, "queued": len(queued), "instances": len(observed)}
