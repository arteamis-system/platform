"""Billing fallback controller. No workflow commands or production authority live here."""

import base64
import datetime as dt
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

VARIABLE = "ARTEAMIS_CI_RUNNERS"
HOSTED = '["ubuntu-24.04"]'
AWS = '["self-hosted","linux","x64","arteamis-runner","arteamis-run-{0}"]'
SELECTOR = '${{ fromJSON(format(github.repository == \'arteamis-system/platform\' && \'["ubuntu-24.04"]\' || github.event_name == \'pull_request\' && github.event.pull_request.head.repo.full_name != github.repository && \'["ubuntu-24.04"]\' || vars.ARTEAMIS_CI_RUNNERS || \'["ubuntu-24.04"]\', github.run_id)) }}'

def aws_labels(run_id):
    return json.loads(AWS.replace("{0}", str(int(run_id))))


BILLING = ("The job was not started because recent account payments have failed or your spending limit needs to be increased. "
           "Please check the 'Billing & plans' section in your settings")
PREFIX = "arteamis-ci-"


class ApiError(Exception):
    def __init__(self, status):
        super().__init__(f"GitHub HTTP {status}")
        self.status = status


def audit(event, **fields):
    # Deliberately omit exception bodies, user data, tokens, and App configuration.
    print(json.dumps({"event": event, **fields}, sort_keys=True))


def billing_only(jobs, annotations):
    """Missing evidence, actual execution, cancellations, and mixed errors fail closed."""
    failed = [j for j in jobs if j.get("conclusion") not in ("success", "skipped", "neutral")]
    if not failed:
        return False
    for job in failed:
        if job.get("status") != "completed" or job.get("conclusion") != "failure":
            return False
        if job.get("runner_id") or job.get("runner_name") or job.get("steps"):
            return False
        if job.get("labels") not in (["ubuntu-latest"], ["ubuntu-24.04"]):
            return False
        evidence = annotations.get(job.get("id"), [])
        failures = [a for a in evidence if a.get("annotation_level") == "failure"]
        if not failures or any(a.get("message", "").strip() != BILLING for a in failures):
            return False
    return True


def latest_skipped_job_names(jobs):
    latest = {}
    for job in jobs:
        name = job.get("name")
        if not isinstance(name, str) or not name:
            continue
        attempt = job.get("run_attempt", 0)
        attempt = attempt if isinstance(attempt, int) else 0
        if name not in latest or attempt > latest[name][0]:
            latest[name] = (attempt, {job.get("conclusion")})
        elif attempt == latest[name][0]:
            latest[name][1].add(job.get("conclusion"))
    return {name for name, (_, outcomes) in latest.items() if outcomes == {"skipped"}}


REUSABLES = {
    "_dispatch.yml", "security-gate.yml", "ci-test.yml", "build-scan-sign.yml",
    "deploy-vm.yml", "deploy-mirror.yml", "deploy-vercel.yml", "tester-agent.yml",
    "ci-browser.yml", "docs-check.yml", "ci-desktop.yml", "release-desktop.yml",
    "terraform-apply.yml", "ci-runner-canary.yml",
}


def compatible_workflow(content, fetch_reusable, skipped_job_names=(), ancestors=()):
    """Inspect the exact immutable graph, including optional children before skips exist."""
    import yaml
    try:
        jobs = yaml.safe_load(content)["jobs"]
        if not isinstance(jobs, dict) or not jobs or len(ancestors) > 8:
            return False
        for key, job in jobs.items():
            # A currently skipped dependency can become runnable on retry.
            # Inspect every child rather than treating that skip as authority.
            if "runs-on" in job:
                # macOS stays on GitHub; failed Linux-only classification below
                # prevents a billing-rejected macOS job entering a retry.
                if job["runs-on"] not in (SELECTOR, "macos-15"):
                    return False
            elif "uses" in job:
                match = re.fullmatch(r"arteamis-system/platform/(\.github/workflows/([a-z_-]+\.yml))@([0-9a-f]{40})", job["uses"])
                if not match or match[2] not in REUSABLES:
                    return False
                path, _, sha = match.groups()
                identity = (path, sha)
                if identity in ancestors or not compatible_workflow(
                        fetch_reusable(path, sha), fetch_reusable, ancestors=(*ancestors, identity)):
                    return False
            else:
                return False
        return True
    except (KeyError, TypeError, ValueError, yaml.YAMLError):
        return False


def execution_evidence(job):
    return bool(job.get("runner_id") or job.get("runner_name") or job.get("steps"))


def release_unstarted(jobs):
    """Any historical deployment execution bars automatic release retries.

    The release callers name their deployment 'deploy'; a shared dispatcher names
    each deployment 'deploy-*'. Missing or ambiguous job names fail closed.
    GitHub's started_at can be populated on a billing rejection, so use runner
    assignment and steps as the positive execution evidence instead.
    """
    if not jobs or any(not isinstance(j.get("name"), str) or not j["name"] for j in jobs):
        return False
    return not any(execution_evidence(j) and any(
        re.match(r"deploy(?:$|[ /-])", part.strip(), re.IGNORECASE)
        for part in j["name"].split(" / ")) for j in jobs)


class GitHub:
    def __init__(self, app):
        self.app = app
        self.tokens = {}

    def request(self, method, path, body=None, token=None):
        if not path.startswith("/") or path.startswith("//"):
            raise ValueError("GitHub path must be relative")
        request = urllib.request.Request(
            "https://api.github.com" + path,
            data=json.dumps(body).encode() if body is not None else None,
            method=method,
            headers={"Authorization": "Bearer " + token, "Accept": "application/vnd.github+json",
                     "X-GitHub-Api-Version": "2026-03-10", "Content-Type": "application/json",
                     "User-Agent": "arteamis-ci-controller/1"},
        )
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                raw = response.read()
                return json.loads(raw) if raw else None
        except urllib.error.HTTPError as error:
            raise ApiError(error.code) from None

    def token(self, repo):
        if repo in self.tokens:
            return self.tokens[repo]
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import padding

        def encode(value):
            return base64.urlsafe_b64encode(value).rstrip(b"=")

        now = int(time.time())
        header = encode(b'{"alg":"RS256","typ":"JWT"}')
        claims = encode(json.dumps({"iat": now - 60, "exp": now + 540, "iss": str(self.app["app_id"])}).encode())
        signing = header + b"." + claims
        key = serialization.load_pem_private_key(self.app["private_key"].encode(), password=None)
        jwt = (signing + b"." + encode(key.sign(signing, padding.PKCS1v15(), hashes.SHA256()))).decode()
        result = self.request("POST", f'/app/installations/{int(self.app["installation_id"])}/access_tokens',
                              {"repositories": [repo.split("/")[1]]}, jwt)
        self.tokens[repo] = result["token"]
        return result["token"]

    def call(self, repo, method, suffix, body=None):
        return self.request(method, "/repos/" + repo + suffix, body, self.token(repo))

    def pages(self, repo, suffix, key=None):
        result = []
        for page in range(1, 11):
            separator = "&" if "?" in suffix else "?"
            data = self.call(repo, "GET", f"{suffix}{separator}per_page=100&page={page}")
            values = data[key] if key else data
            result.extend(values)
            if len(values) < 100:
                return result
        raise RuntimeError("Pagination bound exceeded")

    def variable(self, repo):
        try:
            return self.call(repo, "GET", "/actions/variables/" + VARIABLE)["value"]
        except ApiError as error:
            if error.status == 404:
                return None
            raise

    def set_variable(self, repo, value):
        previous = self.variable(repo)
        if value is None:
            if previous is not None:
                self.call(repo, "DELETE", "/actions/variables/" + VARIABLE)
        else:
            method = "POST" if previous is None else "PATCH"
            path = "/actions/variables" if previous is None else "/actions/variables/" + VARIABLE
            self.call(repo, method, path, {"name": VARIABLE, "value": value})
        # GitHub can briefly return the previous value after a successful write.
        # Repeat only the read, never the mutation.
        for attempt in range(5):
            if self.variable(repo) == value:
                return
            if attempt < 4:
                time.sleep(2)
        raise RuntimeError("Routing readback mismatch")

    public_cache = {}

    def content(self, repo, path, sha):
        if repo == "arteamis-system/platform":
            if (not re.fullmatch(r"[0-9a-f]{40}", sha)
                    or not re.fullmatch(r"\.github/workflows/[a-z_-]+\.yml", path)):
                raise ValueError("Public reusable content must use a known path and immutable source")
            key = (path, sha)
            if key not in self.public_cache:
                with urllib.request.urlopen("https://raw.githubusercontent.com/" + repo + "/" + sha + "/" + path, timeout=10) as result:
                    content = result.read(1024 * 1024).decode()
                if len(self.public_cache) >= 256:
                    self.public_cache.clear()
                self.public_cache[key] = content
            return self.public_cache[key]
        item = self.call(repo, "GET", "/contents/" + path + "?ref=" + urllib.parse.quote(sha, safe=""))
        return base64.b64decode(item["content"]).decode()


class State:
    def __init__(self, table):
        self.table = table

    def get(self, key):
        return self.table.get_item(Key={"key": key}, ConsistentRead=True).get("Item", {})

    def put(self, key, value):
        self.table.put_item(Item={"key": key, **value})

    def claim(self, key, value):
        try:
            self.table.put_item(Item={"key": key, **value}, ConditionExpression="attribute_not_exists(#k)",
                                ExpressionAttributeNames={"#k": "key"})
            return True
        except self.table.meta.client.exceptions.ConditionalCheckFailedException:
            return False

    def delete(self, key):
        self.table.delete_item(Key={"key": key})

    def lock(self, now, owner):
        try:
            self.table.put_item(Item={"key": "controller-lock", "owner": owner, "expires": now + 420},
                                ConditionExpression="attribute_not_exists(#k) OR expires < :now",
                                ExpressionAttributeNames={"#k": "key"}, ExpressionAttributeValues={":now": now})
            return True
        except self.table.meta.client.exceptions.ConditionalCheckFailedException:
            return False

    def unlock(self, owner):
        self.table.delete_item(Key={"key": "controller-lock"}, ConditionExpression="#o = :o",
                               ExpressionAttributeNames={"#o": "owner"}, ExpressionAttributeValues={":o": owner})


class Controller:
    def __init__(self, gh, state, pool, config, now=None):
        self.gh, self.state, self.pool, self.config = gh, state, pool, config
        self.now = int(time.time()) if now is None else now

    def trusted(self, repo, run, canary=False):
        try:
            return self._trusted(repo, run, canary)
        except ApiError as error:
            if error.status != 404:
                raise
            # Deleted branches and unavailable actors cannot authorize a run.
            # Reject that run without preventing other jobs from being served.
            audit("unavailable-run-rejected", repo=repo, run_id=run["id"])
            return False

    def _trusted(self, repo, run, canary=False):
        actor = (run.get("actor") or {}).get("login")
        if not actor or not re.fullmatch(r"[a-zA-Z0-9_\[\]-]+", actor):
            return False
        permission = self.gh.call(repo, "GET", f"/collaborators/{actor}/permission").get("permission")
        if permission not in ("write", "maintain", "admin"):
            return False
        event = run.get("event")
        if event in ("workflow_dispatch", "push") and canary:
            if run.get("head_branch") != "main":
                return False
            branch = urllib.parse.quote(run["head_branch"], safe="")
            return self.gh.call(repo, "GET", "/git/ref/heads/" + branch)["object"]["sha"] == run["head_sha"]
        if event == "workflow_dispatch":
            if (repo not in self.config.get("manual_releases", [])
                    or run.get("path") != ".github/workflows/release.yml"
                    or run.get("head_branch") != "main"):
                return False
            return self.gh.call(repo, "GET", "/git/ref/heads/main")["object"]["sha"] == run["head_sha"]
        if event == "push":
            if run.get("head_branch") != "main":
                return False
            return self.gh.call(repo, "GET", "/git/ref/heads/main")["object"]["sha"] == run["head_sha"]
        if event == "pull_request" and len(run.get("pull_requests", [])) == 1:
            pull = self.gh.call(repo, "GET", "/pulls/" + str(run["pull_requests"][0]["number"]))
            return (pull.get("state") == "open" and pull["head"]["repo"]["full_name"] == repo
                    and pull["head"]["sha"] == run["head_sha"])
        return False

    def source_compatible(self, repo, run):
        path = run.get("path", "").split("@")[0]
        if path not in [".github/workflows/" + p for p in self.config["repositories"][repo]]:
            return False
        # A failed-job rerun omits unchanged skipped jobs from the latest-only
        # response. Preserve their latest outcome across attempts, never an old
        # skipped result that a newer active attempt superseded.
        jobs = self.gh.pages(repo, f"/actions/runs/{run['id']}/jobs?filter=all", "jobs")
        skipped = latest_skipped_job_names(jobs)
        return compatible_workflow(self.gh.content(repo, path, run["head_sha"]),
                                   lambda path, sha: self.gh.content("arteamis-system/platform", path, sha), skipped)

    def takeover(self, repo, run):
        existing = self.state.get(f"retry:{repo}:{run['id']}")
        if not self.config["routing_verified"]:
            return False
        if existing and existing.get("phase") != "prepared":
            if (existing.get("phase") in ("requested", "ambiguous")
                    and existing.get("sha") == run["head_sha"]
                    and run["run_attempt"] > existing["attempt"]):
                self.state.put(f"retry:{repo}:{run['id']}", {**existing, "phase": "accepted"})
            return False
        rejected_key = f"rejected:{repo}:{run['id']}:{run['run_attempt']}"
        if self.state.get(rejected_key).get("sha") == run["head_sha"]:
            return False
        if existing and (existing["sha"] != run["head_sha"] or existing["attempt"] != run["run_attempt"]):
            return False
        canary = repo in self.config.get("canary_repositories", [self.config.get("canary_repository", "arteamis-system/backend")]) and run.get("path") == ".github/workflows/ci-runner-canary.yml"
        if not self.trusted(repo, run, canary):
            return False
        if not self.source_compatible(repo, run):
            self.state.put(rejected_key, {"sha": run["head_sha"], "reason": "unsupported-source"})
            return False
        jobs = self.gh.pages(repo, f"/actions/runs/{run['id']}/attempts/{run['run_attempt']}/jobs", "jobs")
        annotations = {}
        for job in jobs:
            if job.get("conclusion") == "failure":
                match = re.fullmatch(r"https://api\.github\.com/repos/" + re.escape(repo) + r"/check-runs/(\d+)", job.get("check_run_url", ""))
                if not match:
                    return False
                annotations[job["id"]] = self.gh.pages(repo, f"/check-runs/{match[1]}/annotations")
        if run.get("event") == "workflow_dispatch" and run.get("path") == ".github/workflows/release.yml":
            history = self.gh.pages(repo, f"/actions/runs/{run['id']}/jobs?filter=all", "jobs")
            if not release_unstarted(history):
                return False
        if not billing_only(jobs, annotations):
            self.state.put(rejected_key, {"sha": run["head_sha"], "reason": "not-billing"})
            return False
        successful = [job for job in jobs if job.get("conclusion") == "success"]
        if successful:
            # GitHub also reruns dependents of failed jobs. Never replay a
            # previously successful always()/summary job. A release's known
            # manifest/build stages are upstream of its failed deploy stage.
            upstream_release = (run.get("event") == "workflow_dispatch"
                and run.get("path") == ".github/workflows/release.yml"
                and all(job.get("name") == "read manifest" or re.match(r"build(?:$| / )", job.get("name", ""))
                        for job in successful))
            if not upstream_release:
                return False
        current = self.gh.variable(repo)
        mode_key = "mode:" + repo
        mode = self.state.get(mode_key)
        if mode.get("phase") in ("manual", "restoring"):
            return False
        if mode.get("phase") == "aws" and current != AWS:
            self.state.put(mode_key, {**mode, "phase": "manual"})
            audit("manual-routing-preserved", repo=repo)
            return False
        if current not in (None, HOSTED, AWS) or (current == AWS and not mode):
            audit("manual-routing-preserved", repo=repo)
            return False
        retry_key = f"retry:{repo}:{run['id']}"
        # Keep retry tombstones without TTL. Old runs must never become eligible again.
        record = {"attempt": run["run_attempt"], "sha": run["head_sha"], "event": run.get("event"),
                  "branch": run.get("head_branch"), "path": run.get("path"), "phase": "prepared"}
        if not existing and not self.state.claim(retry_key, record):
            return False
        if not mode:
            mode = {"previous": current, "phase": "switching", "enabled_at": self.now}
            self.state.put(mode_key, mode)
        if not self.trusted(repo, run, canary):
            return False
        self.gh.set_variable(repo, AWS)
        self.state.put(mode_key, {**mode, "phase": "aws"})
        # Routing propagation can take seconds. Recheck current authority and,
        # for releases, all attempts immediately before requesting a retry.
        if not self.trusted(repo, run, canary):
            self.state.put(retry_key, {**record, "phase": "superseded"})
            return False
        if run.get("event") == "workflow_dispatch" and run.get("path") == ".github/workflows/release.yml":
            actual = self.gh.call(repo, "GET", f"/actions/runs/{run['id']}")
            if any(actual.get(key) != run.get(key) for key in ("head_sha", "event", "head_branch", "run_attempt")):
                self.state.put(retry_key, {**record, "phase": "superseded"})
                return False
            history = self.gh.pages(repo, f"/actions/runs/{run['id']}/jobs?filter=all", "jobs")
            if actual.get("conclusion") != "failure" or not release_unstarted(history):
                self.state.put(retry_key, {**record, "phase": "superseded"})
                return False
        # Persist intent before a non-idempotent API request. Ambiguous requests are
        # reconciled, never blindly repeated, including on a later Lambda invocation.
        self.state.put(retry_key, {**record, "phase": "requested"})
        try:
            self.gh.call(repo, "POST", f"/actions/runs/{run['id']}/rerun-failed-jobs")
            self.state.put(retry_key, {**record, "phase": "accepted"})
        except Exception:
            actual = self.gh.call(repo, "GET", f"/actions/runs/{run['id']}")
            phase = "accepted" if actual["run_attempt"] > run["run_attempt"] else "ambiguous"
            self.state.put(retry_key, {**record, "phase": phase})
            audit("retry-reconciled", repo=repo, run_id=run["id"], phase=phase)
            return False
        audit("fallback-retry", repo=repo, run_id=run["id"], attempt=run["run_attempt"])
        return True

    def recover(self, repo):
        key = "mode:" + repo
        mode = self.state.get(key)
        if not mode:
            return
        current = self.gh.variable(repo)
        if mode.get("phase") == "manual":
            return
        if mode.get("phase") == "restoring" and current == mode["previous"]:
            self.state.delete(key)
            audit("hosted-recovered", repo=repo, probe_run=mode["recovered_probe_run"])
            return
        if current != AWS:
            self.state.put(key, {**mode, "phase": "manual"})
            audit("manual-routing-preserved", repo=repo)
            return
        if mode.get("phase") == "restoring":
            self.gh.set_variable(repo, mode["previous"])
            self.state.delete(key)
            audit("hosted-recovered", repo=repo, probe_run=mode["recovered_probe_run"])
            return
        if mode.get("phase") == "switching":
            mode = {**mode, "phase": "aws"}
            self.state.put(key, mode)
        if mode.get("phase") != "aws":
            return
        probe = mode.get("probe")
        if probe:
            runs = self.gh.pages(repo, "/actions/workflows/ci-hosted-probe.yml/runs?event=workflow_dispatch", "workflow_runs")
            for run in runs:
                if run.get("display_title") != "Arteamis hosted probe " + probe["nonce"]:
                    continue
                if run.get("conclusion") == "success":
                    jobs = self.gh.pages(repo, f"/actions/runs/{run['id']}/jobs", "jobs")
                    if (run.get("event") == "workflow_dispatch" and run.get("head_branch") == "main"
                            and len(jobs) == 1 and jobs[0].get("conclusion") == "success"
                            and jobs[0].get("labels") == ["ubuntu-24.04"]
                            and jobs[0].get("runner_name", "").startswith("GitHub Actions")
                            and jobs[0].get("runner_id")) :
                        self.state.put(key, {**mode, "phase": "restoring", "recovered_probe_run": run["id"]})
                        self.gh.set_variable(repo, mode["previous"])
                        self.state.delete(key)
                        audit("hosted-recovered", repo=repo, probe_run=run["id"])
                        return
        last_probe = (probe or {}).get("time", mode["enabled_at"] - self.config["probe_interval_seconds"])
        if self.now - last_probe >= self.config["probe_interval_seconds"]:
            nonce = uuid.uuid4().hex
            self.state.put(key, {**mode, "probe": {"nonce": nonce, "time": self.now}})
            self.gh.call(repo, "POST", "/actions/workflows/ci-hosted-probe.yml/dispatches",
                         {"ref": "main", "inputs": {"nonce": nonce}})
            audit("hosted-probe", repo=repo)

    def tick(self):
        if not 1 <= self.config["max_instances"] <= 2:
            raise ValueError("Runner pool must be limited to one or two VMs")
        self.pool.reconcile(self.gh, self.state, self.now)
        if self.state.get("control").get("disabled"):
            audit("controller-disabled")
            return {"disabled": True}
        queued = []
        since = dt.datetime.fromtimestamp(self.now - 86400, dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        for repo, workflows in self.config["repositories"].items():
            if self.config.get("qualification_only"):
                if repo not in self.config.get("canary_repositories", [self.config.get("canary_repository", "arteamis-system/backend")]):
                    continue
                workflows = ["ci-runner-canary.yml"]
            try:
                if not self.gh.call(repo, "GET", "").get("private"):
                    continue
                if self.config.get("enforce_fork_policy", True):
                    forks = self.gh.call(repo, "GET", "/actions/permissions/fork-pr-workflows-private-repos")
                    if any(forks.get(key) is not False for key in (
                            "run_workflows_from_fork_pull_requests", "send_write_tokens_to_workflows", "send_secrets_and_variables")):
                        audit("unsafe-fork-policy", repo=repo)
                        continue
                recent = self.gh.pages(repo, "/actions/runs?created=%3E%3D" + since, "workflow_runs")
                latest_main = None
                if any(r.get("event") == "push" and r.get("head_branch") == "main" for r in recent):
                    latest_main = self.gh.call(repo, "GET", "/git/ref/heads/main")["object"]["sha"]
                for run in recent:
                    if (run.get("event") == "push" and run.get("head_branch") == "main"
                            and run.get("head_sha") != latest_main):
                        continue
                    if run.get("conclusion") == "failure" and run.get("path", "").split("/")[-1] in workflows:
                        self.takeover(repo, run)
                self.recover(repo)
                for run in recent:
                    if run.get("status") in ("queued", "in_progress", "waiting", "pending", "requested"):
                        if run.get("path", "").split("@")[0] not in [".github/workflows/" + p for p in workflows]:
                            continue
                        canary = repo in self.config.get("canary_repositories", [self.config.get("canary_repository", "arteamis-system/backend")]) and run.get("path") == ".github/workflows/ci-runner-canary.yml"
                        if not self.trusted(repo, run, canary) or not self.source_compatible(repo, run):
                            continue
                        for job in self.gh.pages(repo, f"/actions/runs/{run['id']}/jobs", "jobs"):
                            if job.get("status") == "queued" and set(job.get("labels", [])) == set(aws_labels(run["id"])):
                                created = job.get("created_at", run["created_at"])
                                age = self.now - dt.datetime.fromisoformat(created.replace("Z", "+00:00")).timestamp()
                                if 0 <= age <= self.config.get("max_queue_age_seconds", 7200):
                                    queued.append((created, repo, job["id"], run["id"]))
            except Exception as error:
                audit("repository-error", repo=repo, error=type(error).__name__)
        if queued:
            oldest = min(dt.datetime.fromisoformat(created.replace("Z", "+00:00")).timestamp() for created, _, _, _ in queued)
            if self.now - oldest >= 1800:
                audit("queue-delayed", queued_jobs=len(queued), oldest_age_seconds=int(self.now - oldest))
        return self.pool.fulfill(self.gh, self.state, sorted(set(queued)), self.config["max_instances"], self.now)


def lambda_handler(event, context):
    import boto3
    from pool import Pool

    state = State(boto3.resource("dynamodb").Table(os.environ["STATE_TABLE"]))
    if event.get("action") == "status":
        return Pool(boto3.client("ec2"), os.environ["LAUNCH_TEMPLATE"]).status(state)
    now, owner = int(time.time()), context.aws_request_id
    if not state.lock(now, owner):
        return {"leased": True}
    try:
        config = json.loads(Path(__file__).with_name("config.json").read_text())
        config["routing_verified"] = os.environ.get("ROUTING_VERIFIED") == "true"
        config["qualification_only"] = os.environ.get("QUALIFICATION_ONLY", "true") != "false"
        if event.get("action") in ("disable", "resume"):
            state.put("control", {"disabled": event["action"] == "disable"})
            return {"disabled": event["action"] == "disable"}
        if event.get("action") == "clear-override":
            repo = event.get("repository")
            if repo not in config["repositories"]:
                raise ValueError("Repository is not allowlisted")
            state.delete("mode:" + repo)
            return {"override_cleared": repo}
        secret = boto3.client("ssm").get_parameter(Name=os.environ["APP_PARAMETER"], WithDecryption=True)["Parameter"]["Value"]
        gh = GitHub(json.loads(secret))
        if event.get("action") == "restore-routing":
            state.put("control", {"disabled": True})
            restored = []
            for repo in config["repositories"]:
                record = state.get("mode:" + repo)
                if record and record.get("phase") != "manual" and gh.variable(repo) == AWS:
                    gh.set_variable(repo, record["previous"])
                    state.delete("mode:" + repo)
                    restored.append(repo)
            return {"disabled": True, "restored": restored}
        pool = Pool(boto3.client("ec2"), os.environ["LAUNCH_TEMPLATE"], os.environ["LAUNCH_TEMPLATE_VERSION"], config["repositories"])
        return Controller(gh, state, pool, config).tick()
    finally:
        state.unlock(owner)
