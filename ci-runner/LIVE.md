# Arteamis live runner operating record

2026-10-18, Singapore, account `779035457064`. This record supersedes the source-only status in older preparation notes. No GOL resources or operational authority were imported.

## Source integration

All changes were merged under the user's explicit review waiver. Existing branch protections were restored after the platform merges. Historical branches and worktrees remain preserved.

| Repository | Latest runner integration | Main revision |
| --- | --- | --- |
| platform | [component #20](https://github.com/arteamis-system/platform/pull/20), [nested assembly #21](https://github.com/arteamis-system/platform/pull/21) | `06fdff6b7669a3c31ecb83260dc4ed31c6ee6c23` |
| backend | [#22](https://github.com/arteamis-system/backend/pull/22) | `196c3993f11fac48739fbcdc0a76580a91307fed` |
| web | [#15](https://github.com/arteamis-system/web/pull/15) | `f9d3a2c975d70fd2e0231b5dedf342938a691b38` |
| landing | [#3](https://github.com/arteamis-system/landing/pull/3) | `370a13900be91d0577bd07e567ad0ab5b9c5c022` |
| product | [#7](https://github.com/arteamis-system/product/pull/7) | `d52e016902fa37b5814ca307b7bcd2eec356513e` |

Earlier implementation: platform #17/#18, bake reporting fix #19, backend #21, web #14, landing #2 and product #6. Assembly `06fdff6` pins its nested workflows to component `6e2ed6cac61699622e567531c89af40d83600244`. Desktop remains on macOS; the organization profile has no workflow.

Before the later waiver, 70 Python tests, workflow linting, four CloudFormation templates, shell checks, native Lambda imports/RSA, actual Cosign signing/tamper rejection, and the existing platform checks passed. [Component Linux checks](https://github.com/arteamis-system/platform/actions/runs/39095779240), [native runner checks](https://github.com/arteamis-system/platform/actions/runs/39095779225), and [assembly checks](https://github.com/arteamis-system/platform/actions/runs/39095958193) passed. Private consumer CI was rejected by GitHub billing before execution. It was not reported as successful.

## Provisioned resources and permissions

| Resource | Identity / configuration |
| --- | --- |
| CloudFormation | `arteamis-ci-access`, `arteamis-ci-foundation`, `arteamis-ci-alerts`, `arteamis-ci-runtime` |
| Routine operator | `arn:aws:iam::779035457064:role/arteamis-ci-operator`, local profile `arteamis-ci-operator` |
| GitHub App | `arteamis-ci-fallback`, App `5364580`, installation `172581147`; only backend, web, landing, product |
| Controller credential | SSM SecureString `/arteamis/ci/github-app`; controller role allowed, runner/reaper denied |
| AMI | `ami-07a511df2b588b737`, snapshot `snap-0394b01f0cd4d2165` |
| AMI provenance | Canonical base `ami-0080f2c6aa4e378b7`; bake SHA-256 `0d2c2c56390d54dab2b9df64e03156388bb3bdee1eb74d39668d7f88ba99a30e` |
| Lambda bundle | SHA-256 `623a33bb48ae9457c4cfebdd420b0356edcc9759d3ccd84b4263a2c6b3088801`, both controller and reaper verified |
| Current maintenance bundle | SHA-256 `879ec53d92efb965e9751f20b29e490727be4ed4ae668bf8e5c1945eeefc5b48`, source `62f812d3f299917b53e00d7a9b16f4fddbdf9904`; both Lambda hashes verified after rollout |
| State / artifact bucket | `arteamis-ci-state` / `arteamis-ci-artifacts-779035457064-ap-southeast-1` |
| Launch template | `lt-04335d9dabf46be5f`, version 1 |
| Network | Isolated subnet `subnet-0a7fa21362cb39323`, SG `sg-092c894a5bf906560`; no ingress, outbound 22/80/443 |
| Capacity | Zero warm VMs, maximum two On-Demand `m6i.large`, 100 GiB encrypted gp3 deletion-on-termination roots |
| Cleanup | One job per VM, 80-minute process limit, independent scheduled 90-minute reaper; reaper stays enabled |
| Alerts | `arn:aws:sns:ap-southeast-1:779035457064:arteamis-ci-alerts`; email confirmed and delivery observed; $20 monthly alert budget |

Temporary AWS browser authentication was used for administrator bootstrap. No root access keys were created. The temporary administrator CLI login was logged out after setup; the routine operator role remained functional. Already loaded short-lived access tokens can remain valid until expiry. Routine operations use the bounded CI operator role, which cannot terminate production or modify its own access/alert stacks. App private material is stored outside the workspace with mode 0600 and in SSM; never paste it into evidence or commands.

The initial bake failed only in inventory reporting and produced no approved image. The corrected bake succeeded; both builder instances terminated and their root disks were deleted. Keep the ignored `.build/` metadata for detailed audit; it contains local operational records and is not a substitute for retained AWS/GitHub evidence.

## Live evidence and its limits

- [Backend canary 39096081878](https://github.com/arteamis-system/backend/actions/runs/39096081878): attempt 1 had billing-only rejection without a runner. A single failed-job retry of the original ID reevaluated routing. Three isolation jobs succeeded on three distinct one-job VMs: `i-0a0c915c493648022`, `i-0dc13bd26c5e5bfa4`, `i-0f70e7d2deafc975d`. Each terminated normally and its root disk disappeared. Docker/Postgres/builds, Chromium, SBOM, Trivy, pinned Cosign signing/verification, artifact upload and denial of App-parameter access ran successfully. Maximum observed concurrent capacity was two. Modified-payload rejection was separately established by the hosted component check.
- The independent scheduled reaper terminated expired orphan `i-049473dcb9fdef21c` with controller routing disabled; root `vol-00e16563b3aca7631` disappeared. CloudTrail attributes termination to `arteamis-ci-reaper`. This was not a manual reaper invocation or the VM's secondary shutdown timer.
- Controller-only billing takeover changed routing and accepted exactly one failed-job retry on each original canary: [web 39096188264](https://github.com/arteamis-system/web/actions/runs/39096188264), [landing 39096191498](https://github.com/arteamis-system/landing/actions/runs/39096191498), [product 39096194438](https://github.com/arteamis-system/product/actions/runs/39096194438). Durable retry records retained original event, main SHA and run identity. These retries were observed, not inferred from a template.
- Hosted probes [39097378181](https://github.com/arteamis-system/web/actions/runs/39097378181), [39097389806](https://github.com/arteamis-system/landing/actions/runs/39097389806), [39097402428](https://github.com/arteamis-system/product/actions/runs/39097402428) were all rejected by billing before execution. The controller correctly kept AWS routing. **Successful hosted recovery and restoration remain unverified.**
- At the user's subsequent direction, the remaining backend application gate and queued web/landing/product gates were cancelled. These are waived checks, not passes. Remaining canary VMs were drained; any operator termination is distinguished from the normal-cleanup evidence above. No production deployment was used as a secretless canary.

## Authorized release operation

The user separately authorized backend and web production releases on current main, with tests and CI waived. Existing release workflows already omit application tests. Build/signature verification, production environment rules, concurrency, database preflight, backups and migration ordering remain in those workflows.

During these releases the existing runtime uses **manual routing mode**: `ROUTING_VERIFIED=false`, `QUALIFICATION_ONLY=false`, controller enabled. This supplies queued, trusted, source-compatible jobs with the exact AWS labels but cannot automatically retry a billing failure. Only backend/web routing was manually set; landing/product were restored to their previously absent variables. No evidence field was changed to pretend hosted recovery succeeded. Change set `arteamis-ci-review-1792299125` records this mode. Reaper remains enabled.

Backend's existing cutover preflight passed before dispatch; its bootstrap role is `postgres`. No new cluster cutover or private production-configuration change was performed for runner qualification.

[Backend release 39098617850](https://github.com/arteamis-system/backend/actions/runs/39098617850) succeeded on AWS runners. It deployed main `196c3993f11fac48739fbcdc0a76580a91307fed`, image `ghcr.io/arteamis-system/backend@sha256:310bc68dd24791e49440ac4dbe4a8b53bc132e8cf7670afa05dabda9ffe6cebb`. The running container's OCI revision matches that commit. Bootstrap, pre-migration backup, migration and finalization exited zero; API and worker started. Public `https://api.arteamis.space/health` and `/ready` returned HTTP 200 after the release. This release is deployment evidence, separate from the earlier secretless qualification.

[Web release 39099269643](https://github.com/arteamis-system/web/actions/runs/39099269643) succeeded on main `f9d3a2c975d70fd2e0231b5dedf342938a691b38`, after backend workflow success and health verification. It published mirror commit `6d6fa4b` to `the-morca-deployer/arteamis-frontend:main` and recorded release deployment `7150239127`. The public login page returned HTTP 200. The current CLI account cannot access the Vercel project, so exact provider build/revision/alias verification remains pending. A successful mirror push alone is not a claim of a completed Vercel build.

The web release exposed a queue race: a collected queued job could start before capacity was admitted, causing a bounded extra VM. [Platform #22](https://github.com/arteamis-system/platform/pull/22), merged as `62f812d`, now re-reads the job's current status/run/labels before claiming supply and reaps a positively non-busy runner whose original run has completed. Three regression cases were prepared but not executed under the user's waiver. The new bundle was installed with automatic routing and the controller schedule disabled. A manual reconciliation with the stop switch still set terminated spare `i-0298173ff175eae7b`; root `vol-03c5de3509697fbec` disappeared, and a subsequent reconciliation removed its registration/slot. Normal release jobs were not replayed.

At **2026-10-18 05:16 UTC**, verification found zero active/shutting-down pool instances, zero pool root volumes, zero pool registrations across all four repositories, and absent routing variables in all four. Controller stop is true, its schedule is disabled, `ROUTING_VERIFIED=false`, `QUALIFICATION_ONLY=true`; the independent reaper schedule remains enabled. Successful hosted recovery and full automatic activation remain pending.

## Repeatable manual release window

For a future **separately authorized** release while hosted billing remains blocked, use the bounded manual operating mode already used above. The new CLI flag reproduces that reviewed runtime configuration; it was statically inspected, with tests/CI waived. It changes no repository variable and dispatches no release itself:

```sh
ci-runner/.build/venv/bin/python ci-runner/provision.py deploy --ami ami-07a511df2b588b737 --manual-release-mode --alarm-topic arn:aws:sns:ap-southeast-1:779035457064:arteamis-ci-alerts
# Review the saved CloudFormation change set, then execute it (or repeat with --execute).
ci-runner/.build/venv/bin/python ci-runner/provision.py resume
# Save each variable's exact presence/value before deliberately setting the AWS template.
gh variable set ARTEAMIS_CI_RUNNERS --repo arteamis-system/backend --body '["self-hosted","linux","x64","arteamis-runner","arteamis-run-{0}"]'
gh workflow run release.yml --repo arteamis-system/backend --ref main
# Require backend release success and exact running revision/health before releasing web.
gh variable set ARTEAMIS_CI_RUNNERS --repo arteamis-system/web --body '["self-hosted","linux","x64","arteamis-runner","arteamis-run-{0}"]'
gh workflow run release.yml --repo arteamis-system/web --ref main
```

This is explicit operator routing, not automatic billing takeover. It retains the original workflows' permissions, gates and concurrency, and makes no automatic retry. After releases finish, stop supply, restore the exact variables, drain, and use `deploy` without manual/evidence/canary flags to return the controller schedule to disabled. Keep the reaper enabled. Never retry a deployment that started merely because a later record or verification failed.

## Disable and return to hosted defaults

From platform:

```sh
ci-runner/.build/venv/bin/python ci-runner/provision.py disable
ci-runner/.build/venv/bin/python ci-runner/provision.py restore-routing
```

Manual backend/web routing has no controller-owned saved value, so after releases finish remove those variables **only after checking they still equal the exact AWS template** and checking the saved pre-release values (both absent):

```sh
gh variable get ARTEAMIS_CI_RUNNERS --repo arteamis-system/backend
gh variable get ARTEAMIS_CI_RUNNERS --repo arteamis-system/web
gh variable delete ARTEAMIS_CI_RUNNERS --repo arteamis-system/backend
gh variable delete ARTEAMIS_CI_RUNNERS --repo arteamis-system/web
```

An absent variable returns future jobs to hosted Ubuntu. Never change routing during an active deployment, never automatically replay a deployment that started, and never clear retry/supply records to bypass limits. Verify zero pool instances, root disks and runner registrations after draining. Keep `arteamis-ci-reaper` enabled even when the controller is disabled.

## Remaining human dependencies, in order

1. In the Vercel workspace that owns `app.arteamis.space`, open project `arteamis-frontend` → Deployments → commit `6d6fa4b` (source parent `f9d3a2c`). Confirm **Ready**, production target, and the `app.arteamis.space` alias; retain the deployment URL. If it failed, inspect the provider's build error before making another release. The available CLI account belongs to a different workspace and cannot establish this result.
2. For hosted recovery qualification, wait for the next allowance reset, or have an organization billing owner resolve the payment/spending block in `arteamis-system` Settings → Billing & licensing → Budgets and alerts / payment information. Review the actual error and any approved spending amount; the previous Actions budget was $0 with further use blocked. No GitHub spending limit was raised by this setup.
3. In AWS Billing → Cost allocation tags, activate `ArteamisCiPool` when AWS publishes it. It was still absent from the API during setup; appearance and activation can each take up to 24 hours. The $20 SNS budget is an alert, not a hard cap; tag-filtered coverage is incomplete until activation and billing propagation.

AWS authentication, App creation/installation, repository selection, alert confirmation and infrastructure provisioning are already complete; do not repeat them. Administrator access is unnecessary for routine runner operations.

After hosted availability recovers, follow [QUALIFICATION.md](QUALIFICATION.md): create a fresh secretless canary-only automatic qualification window, preserve each previous routing value, require a correlated explicitly hosted successful probe, observe exact restoration (including deletion for an absent prior value), prove manual overrides are preserved, and drain. Original failed probes cannot establish recovery. Keep full-scope evidence false until the required live records exist. Then regenerate evidence against the committed source/AMI/bake, review the runtime change set with scope `all`, enable general automatic routing and retain independent cleanup. No application deployment is required for that remaining qualification.

The remaining application gates were explicitly waived. Provisioning accepts that exception only with `--accept-untested-workflows` and a `workflows_verified` record containing `verified=false`, `waived=true`, a nonempty reason and dated owner-authorization references. It saves a local exception audit record. All other evidence remains mandatory, including actual hosted recovery. The deployed `qualify-recovery` command prepares a recovery-only saved-value window when previous pilot modes were restored; it refuses existing routing ownership/overrides and requires stopped manual canary-only operation. It launches/retries no application job. These additive preparation changes were inspected statically; new tests and CI were skipped at the user's direction, and the recovery action has not been exercised live. The production releases used the earlier qualified bundle identified above. Application workflow pins and runner AMI are unchanged.

Cost planning: approximately **$0.13815 per live VM-hour**, including public IPv4 and 100 GiB root allocation; budget **$8–12/month** for controller/state/snapshots/monitoring before jobs, and **$12–16/month** for an illustrative 100 ten-minute jobs plus two-minute overhead and 10 GiB paid egress. See [COSTS.md](COSTS.md) for official rates, measured controller timing, shared-allowance assumptions and retention. No dedicated NAT, Elastic IP, persistent runner disk or warm VM is provisioned. The $20 alert does not stop spending.

## Update 2026-10-22

- The pending Vercel check for mirror commit `6d6fa4b` (step 1 above) is superseded for current production. Web release run [39105829004](https://github.com/arteamis-system/web/actions/runs/39105829004) for `c6fb203` was rejected by billing before execution. `c6fb203` was then deployed through the Vercel REST API outside the platform workflow, with CI skipped by explicit user request. GitHub deployment `7151238725` reached `success` at 2026-10-18 07:05 UTC: "Production ready; alias and source assets verified; CI skipped". The provider result for `6d6fa4b` itself remains unrecorded.
- A read-only check found zero pool instances, root volumes and runner registrations, and `ARTEAMIS_CI_RUNNERS` absent in backend, web, landing and product. The controller schedule is disabled and the reaper schedule is enabled. No hosted job has run since the 2026-10-18 billing rejections, so successful hosted recovery remains unverified. Steps 2 and 3 above are still open.
