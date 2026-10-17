# Arteamis automatic runner fallback

Prepared source only. AWS resources, App installation, AMI execution, billing takeover and hosted recovery are **not deployed or qualified** by this change. Default routing is GitHub-hosted Ubuntu 24.04. The runtime starts with its controller schedule and automatic routing disabled. The independent reaper stays enabled whenever the runtime exists.

This is adapted from GOL's Python/CloudFormation controller and two-slot JIT pool, including its ambiguous-request, queued-work, reusable-workflow, delayed-variable-readback and completed-work regressions. GOL's operational authority, credentials, resource IDs and acceptance records are not Arteamis evidence. See [costs](COSTS.md), [qualification](QUALIFICATION.md) and the [source validation record](VALIDATION.md).

## Execution and authority

The dedicated account is `779035457064`, from the Arteamis workspace inventory. Region is Singapore `ap-southeast-1`. All resources use the `arteamis-ci` prefix and `ArteamisCiPool=arteamis-ci` tag. The pool has no production VPC connection, zero idle VMs, at most two concurrent On-Demand `m6i.large` instances (2 vCPU, 8 GiB), and an encrypted, deletion-on-termination 100 GiB gp3 root disk per VM. This matches the memory class of hosted Linux sufficiently for an initial pilot; elapsed time and peak memory still require measurement. Containers, browser dependencies and builds need more disk than a minimal runner. Spot is deferred: it can interrupt a deployment, and is only worth a separate CI-only pilot after measured boot/retry overhead.

The public `platform` repository's own jobs stay hosted. Its reusable jobs run in the caller's repository context and honor that repository's routing. The private backend, web, landing and product repositories are admitted. Desktop stays on macOS and receives no Linux runner registration. `.github` has no workflow. All Linux definitions, including manifest, summary, administrative helper jobs and nested reusable workflows, have configurable selectors and timeouts; administrative key/configuration helper workflows are intentionally outside automatic admission. Their presence does not grant configuration authority. `cutover-rehearsal.yml` is not an automatic production action; it remains a deliberate hosted/manual operation.

Each repository variable `ARTEAMIS_CI_RUNNERS` is absent by default, or can explicitly contain `["ubuntu-24.04"]`. AWS routing is this exact template:

```json
["self-hosted","linux","x64","arteamis-runner","arteamis-run-{0}"]
```

The selector expands `{0}` to the **original** `github.run_id`, including on a failed-job retry. The JIT runner receives that run-specific label. There is no persistent registration or shared workspace, and a VM exits after one job. Repository runner labels cannot enforce a policy against a repository writer who intentionally changes workflow code. Repository writers remain the trust boundary. Fork workflows, fork write tokens and fork secrets must stay disabled in all four private repositories; `preflight.py` and each controller tick check this. Public repositories are refused by the pool. Reusable source is fetched only from immutable, allowlisted public platform workflow paths, cached by SHA, without sending App credentials to the raw-content host.

Every minute the controller examines current-main pushes, current same-repository PRs by write-authorized actors, and already dispatched current-main `release.yml` runs in the explicit release allowlist. It admits the exact source graph only when every potentially runnable Linux child has the selector. It does not trust a temporary skipped dependency to remain skipped on retry. Billing classification requires the exact payment/spending-limit annotation on **every** failed job, a hosted Linux label, and no assigned runner or steps. Mixed errors, test failures, cancellation, superseded work, forks and unavailable authority fail closed.

The only retry API is `rerun-failed-jobs` on the existing run ID. The tombstone retains its SHA, event, branch, workflow and original attempt. There is no release dispatch API in takeover. Successful jobs are not explicitly replayed. The original event, permissions, concurrency and environment gates remain in the source workflow. For manual releases, any historical deployment runner assignment or step evidence bars automatic retry, including a deployment that later failed, succeeded or was cancelled. A pre-execution rejection can have `started_at`; that timestamp alone is not execution evidence. A build that actually failed also prevents billing-only classification. Old workflow revisions with hosted-only children are intentionally not retrofitted or retried.

The controller persists retry intent before POST, reconciles an advanced attempt, and never resends an ambiguous retry. Conditional DynamoDB slot claims plus a 420-second controller lease bound concurrent launches. EC2 requests have persisted idempotency tokens. Missing instances do not release ambiguous launch slots. An unchanged repository queue has two launch attempts; new demand or positively verified completed work can create a new bounded supply revision. Jobs older than two hours receive no new supply. Orphans occupy capacity. Never clear retry tombstones or supply counters to bypass a limit; diagnose `status`, CloudTrail and GitHub job metadata.

The VM has an 80-minute runner process bound; Linux jobs time out within 45 minutes (canary 15). Its independent AWS-only reaper enforces a 90-minute launch deadline, plus schedule/API latency, even if GitHub, SSM App configuration or the controller fails. It also reaps expired image builders. Root disks and public IPv4 addresses disappear on termination. There is no NAT Gateway, Elastic IP, persistent runner disk or production instance role.

## Image and network

`bake.sh` installs checksum-verified runner 2.338.0, pinned AWS CLI 2.36.40, Docker/Compose v2, build tools, Python/venv/pipx, system Node/npm, GitHub CLI, SSH/rsync and Chromium system libraries. Existing workflow setup actions select their required Node/Python/uv versions; scanner, buildx, SBOM and cosign actions install their tools. No GOL-specific Foundry/production tools are assumed. The AMI validates the runner executable, records the package inventory, contains no registration/workspace, flushes writes and uses normal CreateImage reboot. Refresh before GitHub's supported-runner deadline and after security updates; verify the current [runner release](https://github.com/actions/runner/releases/tag/v2.338.0) before baking.

The isolated VPC has no ingress. Egress permits TCP 80/443 for package repositories, Actions, registries, Sigstore and SSM, and TCP 22 for existing Arteamis SSH deployments. DNS uses the VPC resolver. Docker-local services require no external PostgreSQL port. If an approved environment uses a nonstandard SSH port, review and change the security group explicitly before qualification; do not copy private environment values here. No SSH deployment or production firewall change is part of qualification. Changing a production source-IP allowlist, if one exists, requires separate production approval; this design has dynamic public IPs.

## Local preparation and validation

Run from platform:

```sh
python3.12 -m venv ci-runner/.build/venv
ci-runner/.build/venv/bin/python -m pip install -r ci-runner/requirements-dev.txt
ci-runner/.build/venv/bin/python -m unittest discover -s ci-runner -p 'test_*.py'
ci-runner/.build/venv/bin/python ci-runner/stack.py
ci-runner/.build/venv/bin/python ci-runner/setup_policy.py
ci-runner/.build/venv/bin/python ci-runner/alerts.py
ci-runner/.build/venv/bin/cfn-lint --region ap-southeast-1 --template ci-runner/generated/foundation.json ci-runner/generated/runtime-preview.json ci-runner/generated/admin-bootstrap.json ci-runner/generated/admin-alerts.json
bash -n ci-runner/bake.sh
shellcheck ci-runner/bake.sh
actionlint -shellcheck=
ci-runner/.build/venv/bin/python ci-runner/routing.py check
ci-runner/.build/venv/bin/python ci-runner/provision.py plan
ci-runner/.build/venv/bin/python ci-runner/provision.py package
python3.12 ci-runner/preflight.py
```

`generated/` and `.build/` are ignored, reproducible review artifacts. Neither contains App keys from these commands. Read `setup-identity.json`, `setup-network.json`, `setup-services.json`, `boundary.json`, `foundation.json` and `runtime-preview.json` before human bootstrap. Existing production policies are never changed. Platform integration is two changes: merge and verify components, then repin dispatcher/nested action references to that immutable source, then update consumers deliberately. Do not move tags or push `deploy/*`.

## Ordered human setup, after source preparation

All commands below run from platform. These are the deferred actions; none has been executed as part of source preparation.

1. **An AWS IAM administrator authenticates using the team's existing non-root administrative access**, in account `779035457064`. This preparation does not authorize root or modifying an existing production operator. Review the generated four templates and the `ArteamisCiBoundary` policy. In CloudFormation, region Singapore, create `arteamis-ci-access` by uploading `ci-runner/generated/admin-bootstrap.json`. Set `OperatorPrincipalArn` to the exact existing IAM user/role ARN that should assume `arn:aws:iam::779035457064:role/arteamis-ci-operator`; review that principal and acknowledge named IAM resources. The stack creates that CI-only operator role, four managed policies (boundary plus setup identity/network/services). Review its ability to create CI roles only with the boundary, pass only CI roles, write but not read the App parameter, build tagged images, manage tagged networking and CI services. It has no production instance/secret/deployment permissions. CloudFormation operations remain scoped to `arteamis-ci-*` and reviewed change sets. The administrator remains the boundary owner.

2. **Configure a refreshed base AWS session** using the team's SSO/federation method. Keep its credentials outside Git. Assuming that session is profile `arteamis-base`, configure the dedicated role profile:

   ```sh
   aws configure set role_arn arn:aws:iam::779035457064:role/arteamis-ci-operator --profile arteamis-ci-operator
   aws configure set source_profile arteamis-base --profile arteamis-ci-operator
   aws configure set region ap-southeast-1 --profile arteamis-ci-operator
   aws --profile arteamis-ci-operator sts get-caller-identity
   ```

   Review EC2 Standard On-Demand quota: at least 4 available vCPUs for two runners; the image builder runs before the pool and uses 2. Also ensure Lambda leaves at least 10 unreserved concurrency slots, and VPC/public IPv4 quotas permit this isolated VPC. No Lambda reserved concurrency is requested.

3. **A GitHub organization owner approves and installs a separate private App**. Run:

   ```sh
   ci-runner/.build/venv/bin/python ci-runner/app_setup.py --output "$HOME/.config/arteamis-ci/github-app.json" --port 8772
   ```

   Open `http://127.0.0.1:8772/`. Review the App manifest: Actions write (failed-job retry and hosted probe dispatch), Administration write (GitHub requires this for repository JIT configuration), Variables write, Checks/Contents/Pull requests/Metadata read, no webhook subscriptions. Install on **Only select repositories: backend, web, landing, product** in `arteamis-system`. Do not select all repositories or reuse GOL's App. GitHub's repository Administration permission is broader than registration; review that tradeoff. The callback writes the key/IDs only to the new mode-0600 external file and never prints them. Confirm all four private repositories still disable fork workflow execution, fork write tokens and fork secrets with `python3.12 ci-runner/preflight.py`. Also confirm Actions access to the public immutable platform workflows. No organization-level routing variable or paid runner group is needed.

4. **The AWS administrator creates alerts and confirms delivery.** In Singapore CloudFormation, upload `generated/admin-alerts.json` as stack `arteamis-ci-alerts`. Enter the private notification email only in its NoEcho `AlertEmail` parameter; keep `MonthlyUsd=20` unless the reviewed workload calls for more. This creates dedicated SNS topic `arn:aws:sns:ap-southeast-1:779035457064:arteamis-ci-alerts` and tag-filtered budget `arteamis-ci-monthly`. Confirm the subscription email. In Billing, activate cost allocation tag `ArteamisCiPool` after it appears; AWS can take up to 24 hours for appearance and another 24 hours for activation. Record delivery evidence. Budget alerts are not a hard spending cap. The operator intentionally cannot administer SNS or Budgets.

5. **Review the exact CI infrastructure change sets, then provision.** No application deployment is invoked:

   ```sh
   ci-runner/.build/venv/bin/python ci-runner/provision.py foundation
   # Review .build/arteamis-ci-foundation-changeset.json and the AWS change set.
   # Execute that named change set in CloudFormation; wait for CREATE_COMPLETE.
   # Alternatively, after reviewing the template, foundation --execute prepares and executes a new reviewed-template change set.
   ci-runner/.build/venv/bin/python ci-runner/provision.py install-app --app-file "$HOME/.config/arteamis-ci/github-app.json"
   ci-runner/.build/venv/bin/python ci-runner/provision.py bake
   ```

   Record `.build/ami.json`: AMI, Canonical base AMI, builder, bake hash; review `.build/ami-inventory.json`, captured from the compressed public SSM bake output before the builder terminates. Baking is billed and self-terminates in 30 minutes. Do not retry an ambiguous builder launch without reconciling its persisted idempotency token. Verify the builder disk is deleted. The App key is now controller-only SecureString `/arteamis/ci/github-app`. Do not print or paste it. Once the AMI is available:

   ```sh
   ARTEAMIS_AMI=$(python3.12 -c 'import json; print(json.load(open("ci-runner/.build/ami.json"))["image_id"])')
   ci-runner/.build/venv/bin/python ci-runner/provision.py deploy --ami "$ARTEAMIS_AMI" --alarm-topic arn:aws:sns:ap-southeast-1:779035457064:arteamis-ci-alerts
   # Review .build/arteamis-ci-runtime-changeset.json; execute that named change set in CloudFormation and wait for CREATE_COMPLETE.
   ```

   Without evidence or `--enable-canary`, both automatic routing and the controller schedule remain off; the reaper schedule is on. Initial deploy verifies the source tree and AMI tags/hash. `--execute` also verifies deployed Lambda archive hashes after execution. If executing a named change set in the console, rerun `deploy --ami "$ARTEAMIS_AMI" --execute --alarm-topic ...` afterward: no stack changes are required, and both Lambda hashes are checked. Never start the canary before recording those hashes.

After these actions, perform [secretless qualification and activation](QUALIFICATION.md). Application production runs and private configuration changes remain separately authorized manual operations.

## Disable, rollback and maintenance

```sh
ci-runner/.build/venv/bin/python ci-runner/provision.py status
ci-runner/.build/venv/bin/python ci-runner/provision.py disable
ci-runner/.build/venv/bin/python ci-runner/provision.py restore-routing
```

`disable` persists the stop switch; `restore-routing` also disables and restores saved values only where routing is still controller-owned. It preserves manual overrides. Existing jobs finish and the reaper continues. For an emergency without working App credentials, keep the reaper schedule enabled, disable only schedule `arteamis-ci-controller` in EventBridge Scheduler, and restore each affected repository variable from the saved sanitized record. Do not delete state or shut off the reaper. The runner role cannot read the App key or acquire production AWS authority. The reaper needs no GitHub token or DynamoDB table access.

To permit automatic takeover after a manual override, first review/set the intended hosted variable, then explicitly run `clear-override --repository arteamis-system/<repo>` and `resume`. Do not clear an override while the variable contains the AWS template: it would erase ownership and saved-value information. `resume` does not turn on automatic routing if the runtime evidence gate is still false. Normal recovery uses a unique, explicitly hosted `ci-hosted-probe.yml` every six hours per switched repository; a correlated successful hosted job restores that repository's exact saved value, including deleting a previously absent variable. Pending/billing-failed/spoofed probes do not restore it. See the live recovery procedure.

Logs expire after 14 days; canary artifacts after 3 days; existing browser artifacts retain their 7-day policy. Controller S3 artifacts expire after 90 days, older versions after 14 days. Retry tombstones have no TTL, so an old run cannot regain retry eligibility. Review AMIs monthly and retain two current images; snapshots cost money while retained:

```sh
ci-runner/.build/venv/bin/python ci-runner/maintenance.py
# Review .build/image-retention-plan.json, unused launch-template versions and rollback requirements.
# Only an explicitly approved cleanup uses maintenance.py --execute.
```

Retention protects all active instances, all CI launch-template version references, images under seven days old, the newest two images and shared snapshots. Remove obsolete template versions only after reviewing rollback consumers; otherwise their images remain protected and continue costing money. Foundation state and artifacts are retained on stack deletion. For complete decommissioning, disable/restore routing, drain, prove zero instances/root volumes/registrations, revoke the Arteamis App, then separately review retained table, artifacts, images and snapshots. Never touch GOL resources or production resources.
