# Deployment handoff

The owner changed this continuation's scope on 2026-10-14: finish the code on
all six repositories' main branches. Deployment, provider access and production
acceptance are deferred to the teammate. No production release, cloud apply,
installer publication or branch deletion was performed. Source integration is
not a claim that the feature backlog is live.

## Source and checks

The feature inventory is [refactor-2026-10-14.json](refactor-2026-10-14.json).
Each accepted area keeps an explicit unresolved release disposition, configuration
needs and acceptance gaps. Product requirement statuses were not promoted to Built.
Desktop's standalone Task Threads stack is retired under PDR-0031; its archive tag
preserves the code. Existing Tasks/handoffs/runs remain the shared backend foundation.

Backend and web retain real development/production histories through consolidation
merges. Refactors are separate PRs on that source. Every branch is preserved.
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
snapshot and app-specific SQL/bootstrap/migrations. The dispatcher must be pinned
to the revision supporting the `platform:` compose selector before releasing it.

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
