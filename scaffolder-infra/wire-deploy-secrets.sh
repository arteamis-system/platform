#!/usr/bin/env bash
# =============================================================================
# wire-deploy-secrets.sh — the one handoff between infra and the app repos,
# automated. After `terraform apply` stands up a project's VMs, this reads the
# `vm_hosts` output and sets VM_HOST / VM_USER / VM_SSH_KEY on every component
# repo that deploys to a VM, per environment. That is the step the infra README
# calls "the only handoff" — the reason onboarding still felt manual.
#
# This is the reusable twin of arteamis-system/deploy/bootstrap.sh: same idea
# (set every repo secret so pushes just deploy), but discovered from the manifest
# instead of hardcoded per project.
#
#   ./wire-deploy-secrets.sh --project tasmil --key ~/.ssh/ci-deploy
#   ./wire-deploy-secrets.sh --project botanary --key ~/.ssh/ci-deploy --user ubuntu --dry-run
#
# Requires: gh (authenticated, repo admin scope), terraform, jq.
# =============================================================================
set -Eeuo pipefail

ORG="${ORG:-devsecops-playground-org}"
USER_DEFAULT="deploy"          # cloud-init creates the `deploy` user on every cloud (aws/gcp/do)
project="" key_path="" vm_user="$USER_DEFAULT" infra_dir="" dry_run=false

die() { echo "error: $*" >&2; exit 1; }

while [ $# -gt 0 ]; do
  case "$1" in
    --project) project="$2"; shift 2 ;;
    --key)     key_path="$2"; shift 2 ;;
    --user)    vm_user="$2"; shift 2 ;;
    --infra-dir) infra_dir="$2"; shift 2 ;;
    --org)     ORG="$2"; shift 2 ;;
    --dry-run) dry_run=true; shift ;;
    *) die "unknown argument: $1" ;;
  esac
done

[ -n "$project" ]  || die "pass --project <name>"
[ -n "$key_path" ] || die "pass --key <path to the deploy PRIVATE key> (its public half is deploy_public_key in tfvars)"
[ -f "$key_path" ] || die "private key not found: $key_path"
command -v gh  >/dev/null || die "gh CLI not found"
command -v jq  >/dev/null || die "jq not found"

# Locate the project's terraform directory. Default assumes this script is run
# from a checkout where infra sits beside platform, but --infra-dir overrides.
if [ -z "$infra_dir" ]; then
  for cand in \
    "./infra/projects/$project" \
    "../infra/projects/$project" \
    "../../infra/projects/$project"; do
    [ -d "$cand" ] && { infra_dir="$cand"; break; }
  done
fi
[ -d "$infra_dir" ] || die "could not find infra/projects/$project — pass --infra-dir <path>"

echo "▸ reading vm_hosts from $infra_dir"
hosts_json="$(terraform -chdir="$infra_dir" output -json vm_hosts 2>/dev/null)" \
  || die "terraform output vm_hosts failed — has this project been applied yet?"
[ "$hosts_json" != "null" ] && [ -n "$hosts_json" ] || die "vm_hosts is empty — nothing provisioned"

# environments this project actually has a VM for: {staging: ip, production: ip}
mapfile -t envs < <(echo "$hosts_json" | jq -r 'keys[]')
echo "  environments: ${envs[*]}"

# Discover the project's component repos and keep only those that deploy to a VM.
# The manifest is the source of truth: target: vm  → needs these secrets.
echo "▸ discovering $ORG/$project-* repos that deploy to a VM"
mapfile -t repos < <(gh repo list "$ORG" --limit 200 --json name -q \
  ".[].name | select(startswith(\"$project-\"))")
[ "${#repos[@]}" -gt 0 ] || die "no repos named $project-* under $ORG"

set_secret() { # repo env name value-or-file [--from-file]
  local repo="$1" env="$2" name="$3" val="$4" mode="${5:-}"
  if $dry_run; then
    echo "    DRY  gh secret set $name --env $env --repo $ORG/$repo"
    return
  fi
  # The environment must exist before an environment-scoped secret can be set.
  gh api --silent --method PUT "repos/$ORG/$repo/environments/$env" >/dev/null 2>&1 || true
  if [ "$mode" = "--from-file" ]; then
    gh secret set "$name" --env "$env" --repo "$ORG/$repo" < "$val"
  else
    gh secret set "$name" --env "$env" --repo "$ORG/$repo" --body "$val"
  fi
}

wired=0 skipped=0
for repo in "${repos[@]}"; do
  # Read this repo's manifest straight from GitHub (default branch).
  manifest="$(gh api "repos/$ORG/$repo/contents/.platform.yml" \
                -H 'Accept: application/vnd.github.raw' 2>/dev/null || true)"
  if [ -z "$manifest" ]; then
    echo "  – $repo: no .platform.yml, skipping"; ((skipped++)); continue
  fi
  if ! grep -qE '^[[:space:]]*target:[[:space:]]*vm[[:space:]]*$' <<<"$manifest"; then
    echo "  – $repo: not a vm target (frontend/contract), skipping"; ((skipped++)); continue
  fi

  echo "  ✓ $repo → vm"
  for env in "${envs[@]}"; do
    ip="$(echo "$hosts_json" | jq -r --arg e "$env" '.[$e]')"
    [ "$ip" != "null" ] && [ -n "$ip" ] || { echo "      $env: no ip, skip"; continue; }
    echo "      $env: VM_HOST=$ip VM_USER=$vm_user VM_SSH_KEY=<$key_path>"
    set_secret "$repo" "$env" VM_HOST    "$ip"
    set_secret "$repo" "$env" VM_USER    "$vm_user"
    set_secret "$repo" "$env" VM_SSH_KEY "$key_path" --from-file
  done
  ((wired++))
done

echo ""
echo "done: wired ${wired} repo(s), skipped ${skipped}.$( $dry_run && echo '  (dry-run — nothing was written)')"
echo "next: push a service repo to deploy/staging and the pipeline will deploy onto the VM."
