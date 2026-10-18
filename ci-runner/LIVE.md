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

Release status is recorded after completion below. Until then, a dispatched or successful mirror push alone is not a claim of a healthy production application.

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

1. For hosted recovery qualification, an organization billing owner must resolve the payment/spending block in `arteamis-system` Settings → Billing & licensing → Budgets and alerts / payment information. Review the account's actual error and approved spending amount; the previous Actions budget was $0 with further use blocked. This is a financial decision, not something a runner can bypass.
2. In AWS Billing → Cost allocation tags, activate `ArteamisCiPool` when AWS publishes it. It was still absent from the API during setup; appearance and activation can each take up to 24 hours. The $20 SNS budget is an alert, not a hard cap; tag-filtered coverage is incomplete until activation and billing propagation.

AWS authentication, App creation/installation, repository selection, alert confirmation and infrastructure provisioning are already complete; do not repeat them. Administrator access is unnecessary for routine runner operations.

After hosted availability recovers, follow [QUALIFICATION.md](QUALIFICATION.md): create a fresh secretless canary-only automatic qualification window, preserve each previous routing value, require a correlated explicitly hosted successful probe, observe exact restoration (including deletion for an absent prior value), prove manual overrides are preserved, and drain. Original failed probes cannot establish recovery. Keep full-scope evidence false until the required live records exist. Then regenerate evidence against the committed source/AMI/bake, review the runtime change set with scope `all`, enable general automatic routing and retain independent cleanup. No application deployment is required for that remaining qualification.

The remaining application gates were explicitly waived. Provisioning now accepts that exception only with `--accept-untested-workflows` and a `workflows_verified` record containing `verified=false`, `waived=true`, a nonempty reason and dated owner-authorization references. It saves a local exception audit record. All other evidence remains mandatory, including actual hosted recovery. This additive provisioning change was inspected statically; new tests and CI were skipped at the user's direction. It does not change the deployed controller/runner bundle or the immutable application workflow pins.

Cost planning: approximately **$0.13815 per live VM-hour**, including public IPv4 and 100 GiB root allocation; budget **$8–12/month** for controller/state/snapshots/monitoring before jobs, and **$12–16/month** for an illustrative 100 ten-minute jobs plus two-minute overhead and 10 GiB paid egress. See [COSTS.md](COSTS.md) for official rates, measured controller timing, shared-allowance assumptions and retention. No dedicated NAT, Elastic IP, persistent runner disk or warm VM is provisioned. The $20 alert does not stop spending.
