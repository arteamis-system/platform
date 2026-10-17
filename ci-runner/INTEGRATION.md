# Source integration gate

All autonomous source preparation is reviewable in the component, assembly and four consumer PRs. No source was merged using an administrator bypass. GitHub's existing platform main policy requires one code-owner approval, dismisses stale approvals and requires the `selftest` check with an up-to-date base. This is an unavoidable owner step, separate from AWS/App approval. The component's public hosted CI and native Lambda checks are green.

Keep the review branches. Use **merge commits** for the two platform PRs so the validated immutable pin targets become ancestors of main without changing their IDs. Squashing/rebasing requires a fresh deliberate pin update; do not silently substitute another commit.

1. A code owner reviews and approves [component PR #17](https://github.com/arteamis-system/platform/pull/17), whose validated head is `91ce65884dd0d01ac2668dc83b1d66586c64fd3d`. Once all required checks and approval pass:

   ```sh
   gh pr checks 17 --repo arteamis-system/platform
   gh pr merge 17 --repo arteamis-system/platform --merge
   ```

2. Retarget the assembly PR (`ci/aws-runner-pins`) from the component branch to main, and bring it up to date if required. Its internal workflow/action/policy pins point at the validated component above. Review the final assembly diff, wait for green selftest/native runner checks, then obtain its code-owner approval **after** any update that dismisses stale reviews:

   ```sh
   gh pr edit ci/aws-runner-pins --repo arteamis-system/platform --base main
   gh pr update-branch ci/aws-runner-pins --repo arteamis-system/platform
   gh pr checks ci/aws-runner-pins --repo arteamis-system/platform
   gh pr merge ci/aws-runner-pins --repo arteamis-system/platform --merge
   ```

   If `update-branch` reports the branch is already current, no update is needed. Review/approval is through GitHub's normal UI; do not use `--admin`, fake a check result, weaken protection or delete a branch.

3. Review and merge the `ci/aws-runner-routing` PR in each private repository: backend, web, landing, product. Each pins the tested assembly commit, adds an explicitly hosted recovery probe and a secretless manually dispatched canary wrapper. Linux selectors/timeouts are the only behavior change to existing direct jobs; existing triggers, permissions, environments, concurrency and steps are preserved. The backend SSH argument adapter is retained because the shared deployment still needs it. Application release workflows remain manual. These private repositories may show pre-run billing failures; record those as failures, not test passes. Local workflow/pin/admission validation is available in this preparation. Source acceptance does not establish live runner qualification.

   ```sh
   gh pr view ci/aws-runner-routing --repo arteamis-system/backend
   gh pr view ci/aws-runner-routing --repo arteamis-system/web
   gh pr view ci/aws-runner-routing --repo arteamis-system/landing
   gh pr view ci/aws-runner-routing --repo arteamis-system/product
   # After review and acceptance, use gh pr merge ci/aws-runner-routing --repo arteamis-system/<repo> --squash.
   ```

4. Fetch all seven workspace repositories and fast-forward primary main checkouts without resetting local work. Confirm clean working trees and identical `main`/`origin/main` IDs. `.github` and desktop have no source change for this task; macOS remains hosted. Existing branches and scratch worktrees remain intact. The prepared platform worktree is retained for review until the owner finishes integration.

Then follow the single ordered [AWS/App human setup list](README.md#ordered-human-setup-after-source-preparation), followed by [live qualification](QUALIFICATION.md). The initial runtime remains disabled/canary-only; a source merge never activates routing or runs a production release.
