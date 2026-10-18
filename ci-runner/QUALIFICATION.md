# Live qualification and activation

See [LIVE.md](LIVE.md) for completed 2026-10-18 baseline, independent cleanup and automatic canary takeover evidence. Successful hosted recovery remains pending. The user subsequently waived remaining application tests and CI; do not repeat those checks without a new instruction or report them as verified. The procedures below retain the original qualification requirements for reference. Use only the secretless private-repository `ci-runner-canary.yml` wrappers around platform's immutable reusable canary. Never dispatch an application release or a production configuration helper to qualify the pool. Record the exact platform/caller SHA, source event/ref, run ID, every attempt, AMI/bake hash, Lambda archive/hash, schedule settings, variable saved value, runner/instance/volume IDs, timestamps and evidence links. Preserve failed checks as failures.

## Baseline, with automatic takeover disabled

After completing the human setup in [README](README.md), use a clean merged platform checkout and the AMI recorded by `provision.py bake`. Verify `preflight.py`, the App's selected four repositories, Lambda code hashes, boundary, no-ingress security group, disk encryption/deletion and connected alarms. Check SSM `/arteamis/ci/github-app` exists by metadata only; never retrieve its plaintext. The runner role should have only the SSM agent's connectivity permissions, and the reaper only CI termination/logging.

1. Deploy with the controller schedule enabled for **canary-only capacity**, still with `ROUTING_VERIFIED=false` and `QUALIFICATION_ONLY=true`:

   ```sh
   ARTEAMIS_AMI=$(python3.12 -c 'import json; print(json.load(open("ci-runner/.build/ami.json"))["image_id"])')
   ci-runner/.build/venv/bin/python ci-runner/provision.py deploy --ami "$ARTEAMIS_AMI" --enable-canary --alarm-topic arn:aws:sns:ap-southeast-1:779035457064:arteamis-ci-alerts
   # Review and execute the named change set; or use --execute after reviewing the offline template.
   ci-runner/.build/venv/bin/python ci-runner/provision.py resume
   ```

2. Save the backend variable's prior **presence and exact value** privately in the operating record. `gh variable list --repo arteamis-system/backend` lists routing metadata, not secrets. Leave it absent/hosted initially. Dispatch only this canary:

   ```sh
   gh workflow run ci-runner-canary.yml --repo arteamis-system/backend --ref main -f nonce=baseline-20261017
   gh run list --repo arteamis-system/backend --workflow ci-runner-canary.yml --limit 3
   ```

   Assign the selected original ID to `ARTEAMIS_RUN_ID`. If GitHub rejects it, capture all attempts/jobs and verify the exact billing annotation with no runner/steps. If hosted is already available, a second controlled canary may use `-f fail_hosted=true`; its deliberate step failure is **not billing evidence** and must never trigger automatic takeover.

3. Set the variable to the exact run-label template and request one **manual failed-job retry of the same ID**:

   ```sh
   gh variable set ARTEAMIS_CI_RUNNERS --repo arteamis-system/backend --body '["self-hosted","linux","x64","arteamis-runner","arteamis-run-{0}"]'
   gh run rerun "$ARTEAMIS_RUN_ID" --repo arteamis-system/backend --failed
   ci-runner/.build/venv/bin/python ci-runner/qualification.py --run "$ARTEAMIS_RUN_ID" --output ci-runner/.build/baseline-run.json --minutes 20
   ```

   Keep observation running through cleanup. It only reads GitHub metadata and tagged EC2 instances/volumes; it does not retrieve logs, user data or secrets. It records all attempts and capacity samples. An observer can separately watch `provision.py status`. Because automatic takeover is still gated, this manually owned variable must be restored by the operator after the baseline; the controller has not saved it.

4. Require the retried attempt to preserve the original run ID, SHA, event and branch; its three jobs must expand `arteamis-run-<original ID>`. Require three distinct ephemeral runner names and instance IDs, fresh filesystem markers, Docker/Compose/Postgres/image build, browser launch, SBOM, scan and throwaway signing success. Require controller-secret access denied, not a networking or missing-credentials error. Two jobs should occupy two VMs while the third queues, then use a third fresh VM. Maximum observed capacity must never exceed two. Sampling supports the evidence; also review EC2 launch/termination timestamps and CloudTrail to exclude short overlaps. Each runner must execute exactly one job, unregister and terminate; every recorded root volume must disappear. Keep image-builder cleanup separate. Capture GitHub runner listing after draining and a zero-volume AWS query. A timeout, boot error or exhausted queue budget is a failed qualification, not permission to increase capacity or clear records.

5. Prove **independent cleanup** while the controller stop switch is set. With zero active runners:

   ```sh
   aws --profile arteamis-ci-operator --region ap-southeast-1 cloudformation describe-stacks --stack-name arteamis-ci-runtime --query 'Stacks[0].Outputs'
   # From LaunchTemplateId, record the actual latest version:
   aws --profile arteamis-ci-operator --region ap-southeast-1 ec2 describe-launch-template-versions --launch-template-id "$ARTEAMIS_LT" --versions '$Latest' --query 'LaunchTemplateVersions[].VersionNumber'
   ci-runner/.build/venv/bin/python ci-runner/orphan_canary.py --launch-template "$ARTEAMIS_LT" --version "$ARTEAMIS_LT_VERSION"
   ```

   This explicit billed canary creates one already-expired VM with no slot, JIT registration or job credentials. Its persisted request token must be reconciled after an ambiguous response; never repeat with a new token. Require the **scheduled** reaper log and instance termination within schedule/API latency, and deleted root volume. Its ten-minute self-shutdown is a secondary bound, not proof of independent reaping. Reaper alarm delivery should be confirmed. Then `provision.py resume`. Do not disable the reaper schedule. Archive the orphan request/evidence rather than overwriting it.

6. Restore backend routing to its exact saved value (delete it if previously absent), and confirm zero active CI instances/root volumes/registrations. Copy `acceptance.example.json` to `.build/acceptance-canary.json`; set `scope=canary`, the exact current merged platform source, AMI and bake hash. For each baseline field, mark verified **only after** dated GitHub/AWS references establish it. Include the artifact hash and sanitized raw observation file in the operating record. Do not turn a local test into a live assertion. JSON validation checks shape and source identity, not the truth of external evidence.

## Automatic billing takeover, isolated to the canary

Deploy the reviewed baseline evidence with `scope=canary`:

```sh
ci-runner/.build/venv/bin/python ci-runner/provision.py deploy --ami "$ARTEAMIS_AMI" --evidence ci-runner/.build/acceptance-canary.json --alarm-topic arn:aws:sns:ap-southeast-1:779035457064:arteamis-ci-alerts
# Review/execute the named change set. ROUTING_VERIFIED=true, QUALIFICATION_ONLY=true.
ci-runner/.build/venv/bin/python ci-runner/provision.py resume
gh workflow run ci-runner-canary.yml --repo arteamis-system/backend --ref main -f nonce=automatic-20261017
```

The canary-only scope permits only the named canary wrappers in backend, web, landing and product. Only an **actual hosted billing rejection before execution** qualifies. The minute controller must save the previous variable, write/read back AWS routing, persist one retry intent and POST `rerun-failed-jobs` once on that original ID. Require attempt 2 to run on fresh VMs and clean up. Continue observing for several ticks to prove no second retry. Confirm queue counters/conditional claims, runner role denial, stop-switch behavior and capacity without deleting any durable records. Application jobs are still outside the canary-only scope. If hosted is available, record automatic billing takeover as pending; do not simulate a GitHub annotation or classify the controlled step failure as a billing failure.

## Explicit hosted-recovery qualification

GOL has local tests and live takeover/cleanup evidence, but no successful live hosted recovery proof to borrow. Arteamis must establish its own:

1. Keep the canary's controller-owned AWS mode and saved value after automatic takeover. Record the DynamoDB mode metadata without reading App configuration. The controller dispatches `ci-hosted-probe.yml` on backend main every six hours using a unique nonce; the workflow has no secrets, empty permissions, literal `ubuntu-24.04` and a two-minute timeout. Do not edit the probe to use configurable routing.
2. While billing remains blocked, verify a failed probe does **not** restore routing or trigger a retry/runner VM. In a separate controlled test, set a manual hosted/custom override and prove the controller records manual ownership and leaves it untouched; restore the intended hosted baseline and explicitly clear that override before another takeover. Do not erase retry tombstones.
3. After an owner restores hosted availability through GitHub billing/allowance, wait for the next scheduled probe (up to six hours). Observe the matching nonce/title, `workflow_dispatch`, main branch, one successful job, literal hosted label, a GitHub Actions runner identity and assigned runner ID. A successful unrelated or AWS job is insufficient.
4. Require automatic restoration of the exact saved value, including variable deletion when it was absent. Record the probe/run/job, `hosted-recovered` log and final routing metadata. Then dispatch a **new secretless canary**, with `fail_hosted=false`, and prove it executes on GitHub-hosted runners with no EC2 launch. Record zero pool instances and root volumes afterward.
5. If the probe does not succeed, keep `hosted_recovery_verified=false`. Do not advertise recovered service or pass full activation. Local restored-value and interrupted-restoration tests are necessary but are not successful live recovery.

## Application readiness and full activation

Validate the final immutable caller/child pin graph in each private repository. With automatic scope still canary-only, dispatch the prepared secretless wrapper in each repository with `application_checks=true`. Each wrapper grants only contents read, inherits no secrets and selects no environment. The shared application job runs the existing backend Docker gate, web build/coverage/critical browser journeys, landing browser suite or product documentation action. For example:

```sh
gh workflow run ci-runner-canary.yml --repo arteamis-system/backend --ref main -f nonce=backend-gates -f application_checks=true
gh workflow run ci-runner-canary.yml --repo arteamis-system/web --ref main -f nonce=web-gates -f application_checks=true
gh workflow run ci-runner-canary.yml --repo arteamis-system/landing --ref main -f nonce=landing-gates -f application_checks=true
gh workflow run ci-runner-canary.yml --repo arteamis-system/product --ref main -f nonce=product-gates -f application_checks=true
```

Set AWS routing explicitly for manual qualification only after saving each prior variable; restore it afterward. If routing is controller-owned, preserve its saved state instead. Observe capacity/cleanup for all runs. Never broaden scope just to run release.yml. Record backend Docker test memory/duration, web/browser build limits, landing checks and product documentation checks before `workflows_verified=true`. No successful production deployment claim follows from these tests. SSH deployment reachability and real release-specific behavior remain unqualified until a separately authorized release; do not use a real deployment to qualify the runner.

The full evidence file uses `scope=all`, exact current platform source/AMI/bake hash and all baseline plus `automatic_takeover_verified`, `hosted_recovery_verified`, `workflows_verified` fields with dated references. Both staged and full activation require the dedicated connected alert topic. Then, and only then:

Owner application-test waiver: the 2026-10-18 direction waived remaining application tests and CI. Preserve `workflows_verified.verified=false`; set `waived=true`, a nonempty `reason` and an HTTPS reference to the recorded owner authorization. Pass `--accept-untested-workflows` explicitly to `deploy` when accepting this exception. Without that flag the default validator remains strict. The flag cannot waive hosted recovery, takeover, permissions, tools, capacity or cleanup, and is invalid for canary scope. Never manufacture successful checks to satisfy evidence. Do not rerun the waived application checks for this continuation.

```sh
ci-runner/.build/venv/bin/python ci-runner/provision.py deploy --ami "$ARTEAMIS_AMI" --evidence ci-runner/.build/acceptance-all.json --alarm-topic arn:aws:sns:ap-southeast-1:779035457064:arteamis-ci-alerts
# Review/execute the named change set; verify both Lambda archive hashes.
ci-runner/.build/venv/bin/python ci-runner/provision.py resume
```

This makes `QUALIFICATION_ONLY=false` for the four approved private Linux repositories. Their default remains hosted. The controller can then rescue a future, already-authorized manual release only under its billing/no-deployment-execution rules. It still never initiates a release, substitutes a source/ref/event, clears environment gates or pushes deploy branches.
