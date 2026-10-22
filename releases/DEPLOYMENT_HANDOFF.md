# Deployment handoff

The owner changed this continuation's scope on 2026-10-14: finish the code on
all six repositories' main branches. Deployment, provider access and production
acceptance are deferred to the teammate. No production release, cloud apply,
installer publication or branch deletion was performed. Source integration is
not a claim that the feature backlog is live.

## Status update (2026-10-22)

The sections after this one record the 2026-10-14 handoff unchanged. Since then
the user separately authorized production work, with tests and CI waived:

- 2026-10-15: the production cluster cutover ran and exited 0. Volume
  `arteamis_pgcluster` is live, and the old `arteamis_pgdata` volume holds the
  rollback data; do not remove it. Rehearsal container
  `arteamis-release-rehearsal-b0aa37f41c` (pgvector pg16), started that day, is
  still running on the host. Leave it unless the owner approves removal.
- 2026-10-17: backend `b4fcdf7` was released manually as a source layer with CI
  skipped, after release run 39015059923 was blocked. Its pre-migration dump was
  recorded as uploaded offsite.
- 2026-10-18: [backend release 39098617850](https://github.com/arteamis-system/backend/actions/runs/39098617850)
  deployed main `196c399` on the AWS fallback runners; `/health` and `/ready`
  return 200 and the worker is running. [Web release 39099269643](https://github.com/arteamis-system/web/actions/runs/39099269643)
  deployed `f9d3a2c`. Web `c6fb203` followed through the Vercel REST API
  (GitHub deployment 7151238725, CI skipped by explicit user request) after
  release run 39105829004 was blocked by billing.
- Desktop pre-release `desktop-v0.1.0-internal.4` (`96c93d6`) was built
  locally and ad-hoc signed. Landing's release is still deferred.

Both production services now run current main, so the earlier statement that
readiness and worker availability fail on the old release is superseded. Backup
freshness, private configuration reconciliation (step 2 below) and Hatchet
setup (step 3) were not re-verified here. The newest release tag is still
`release/prod-2026-09-20`. GitHub-hosted CI has been blocked by billing since
2026-10-17; see [the live runner record](../ci-runner/LIVE.md). A deployment is
not dated production verification, so no product requirement was promoted to
Built.

## Source and checks

Source consolidation is complete on all six main branches. The
[source integration record](source-integration-2026-10-14.json) pins the reviewed
commits, successful CI runs and source-tree comparisons. Backend's final gate
passed 5,301 tests with 20 skips, zero failures/errors and 82% rounded coverage
across its fast and migrated database profiles. Web's gates include critical
browser journeys; desktop, landing, product and platform checks also passed.
The recorded platform implementation revision precedes this documentation-only
handoff update. These checks establish the source baseline; release packaging and
production acceptance remain deferred.

The feature inventory is [refactor-2026-10-14.json](refactor-2026-10-14.json).
Each accepted area keeps an explicit unresolved release disposition, configuration
needs and acceptance gaps. Product requirement statuses were not promoted to Built.
Desktop's standalone Task Threads stack is retired under PDR-0031; its archive tag
preserves the code. Existing Tasks/handoffs/runs remain the shared backend foundation.

Backend and web retain real development/production histories through consolidation
merges. Refactors are separate PRs on that source. Every branch is preserved.
[The branch inventory](branches-2026-10-14.json) records tips and ancestry at the
earlier review snapshot, before the final backend merges; it does not treat an
unmerged tip as disposable.
The five application/product repositories and local folders use their new names.

## Before the backend release

1. Record the selected final main commits and rerun their required gates. The
   backend gate uses both fast fixtures and migrated non-owner RLS profiles;
   web includes critical browser journeys as well as build/unit/coverage gates.
2. Reconcile runtime configuration privately. The live VM has provider and offsite
   backup keys that are absent from GitHub's production-environment secret names.
   The platform writes a replacement app `.env`; releasing without migrating
   those values would lose working configuration. Never copy infrastructure
   credentials into API/worker env files. Configure `VM_ENV_INFRA` separately.
3. Configure and verify the Hatchet worker/scheduler (`HATCHET_CLIENT_TOKEN` is
   currently absent). The new worker entrypoint waits for API readiness and then
   starts Hatchet; adding its container without setup is not working job delivery.
4. Use the backend's `scripts/cutover_cluster_superuser.sh` and
   `docs/rls-test-provisioning.md`. PostgreSQL 16 cannot demote its bootstrap
   `arteamis` superuser. Restore to the new `postgres`-initialized `pgcluster`
   directory; preserve the old `pgdata` and exact rollback compose/image files.
5. Take a fresh production backup and repeat the upgrade rehearsal. A production
   copy restored 88 tables/1,589 rows at x8convrefused; earlier upgrade rehearsal
   reached gr06blockoverride without losing existing rows. Rehearse final main
   against a fresh copy before release; these are dated checks, not live rollout.
6. The required phases are bootstrap, backup, migrate, helper finalization, then
   API and worker from one immutable image. `BACKUP_REQUIRED=true` fails closed.
   Once migration starts, a failed rollout requires operator recovery; swapping
   the API container is not a schema rollback.

The canonical assembly is platform
`environments/production/backend.compose.yml`. Backend retains its local rehearsal
snapshot and app-specific SQL/bootstrap/migrations. The current application entry points retain their previously verified platform
pin and local rehearsal assembly for compatibility. To adopt platform assembly
at release time, deliberately bump both backend workflow dispatcher pins to the
reviewed platform main and set backend `.platform.yml` `deploy.compose_file` to
`platform:environments/production/backend.compose.yml`. Both assembly copies
currently carry the same commands and safety phases; review any later differences.

## Backup and infrastructure evidence

[production-inventory.json](../ops/production-inventory.json) records read-only
host/resource checks. The existing external S3-compatible backup store is reachable.
Its latest object is from September 20; it was downloaded and restored into a
new disposable container on October 14: 88 tables/1,452 rows at x8convrefused.
This verifies that old offsite object, not current backup freshness. A fresh local
production-copy drill separately restored 88 tables/1,589 rows. Both scratch
containers were removed; production data and old volumes were preserved.

`ops/restore-backup.sh` accepts a private local dump or S3 URI and supports both
legacy gzip SQL and custom-format dumps. It cannot target a deployment database.
`ops/check-production.py` checks readiness, worker, disk, TLS and local backup age
without printing environment values or private product data. Readiness, worker
availability and backup freshness currently fail on the old production release.

The production Terraform root imports the five existing AWS resources with
**five imports and zero creates, updates or destroys** in the read-only adoption
plan. Both volumes and the instance have destruction protection in configuration.
The separate bootstrap root proposes only a protected, versioned remote-state
bucket; it has not been applied. Existing backup storage is retained. No staging
root/host was provisioned, per the owner. GCP ownership/status remains unverified
because the existing login cannot refresh.

## Client releases and acceptance

- Backend and web main merges run gates only. Their manual `release.yml` workflows
  select main and release through pinned platform stages. Release backend first.
- Landing has no provider function: `/api/subscribe` rewrites to the backend
  newsletter route. Configure Brevo only on backend and platform Vercel access
  for landing. Its `git.deploymentEnabled: false` prevents Git-triggered automatic
  deployments ([Vercel reference](https://vercel.com/docs/project-configuration/git-configuration)).
  Its markup/assets/JSX checks and three stubbed browser form journeys pass;
  actual provider delivery remains to be verified after deployment.
- Desktop is the existing bounded macOS shell at the repository root. Its manual
  packaging workflow defaults to an unsigned/ad-hoc internal build and saves an
  installer for review. Publishing an internal pre-release is a separate explicit
  `publish` choice. Apple signing/notarization and APNs remain unconfigured; APNs
  must stay disabled. Build/bridge tests do not establish installed notification
  delivery/click behavior or Quit acceptance.
- Configure document-conflict rollout explicitly; the default shadow mode is not
  activation. Preserve the actual runtime setup/conformance status in the backend
  evidence. Do not claim all six adapters verified because binaries exist.

After deployment, record artifact digests, compatible client commits, configuration
version, platform revision and dated production journey verification. Only then
update applicable product requirements to Built.
