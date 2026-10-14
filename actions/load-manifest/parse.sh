#!/usr/bin/env bash
# Turn .platform.yml into workflow outputs. Everything the pipeline decides
# downstream is decided here, so this file is the schema.
set -euo pipefail

if [[ ! -f "$MANIFEST" ]]; then
  echo "::error::No manifest at '$MANIFEST'. Every repo onboarded to the platform needs one." >&2
  echo "::error::See https://github.com/devsecops-playground-org/platform#the-manifest" >&2
  exit 1
fi

# q <yaml-path> <default> — read a scalar, falling back when null/missing/empty.
# Written with explicit `if` rather than `[[ ]] && assign`: under `set -e` the
# latter exits the script when the test is false on bash 5 (the CI runner), even
# though bash 3.2 tolerates it. That discrepancy is exactly the kind of drift a
# platform must not ship.
q() {
  local out
  out="$(yq -r "$1 // \"\"" "$MANIFEST")"
  if [[ -z "$out" || "$out" == "null" ]]; then
    out="$2"
  fi
  printf '%s' "$out"
}

emit() { printf '%s=%s\n' "$1" "$2" >>"$GITHUB_OUTPUT"; }

project="$(q '.project' '')"
component="$(q '.component' '')"
type="$(q '.type' 'service')"
runtime="$(q '.runtime' 'node')"
package_manager="$(q '.package_manager' '')"

for required in project component; do
  if [[ -z "${!required}" ]]; then
    echo "::error::manifest is missing required field '$required'" >&2
    exit 1
  fi
done

case "$type" in
  service|frontend|contract) ;;
  *) echo "::error::type must be service|frontend|contract, got '$type'" >&2; exit 1 ;;
esac
case "$runtime" in
  node|python|go|rust|solidity) ;;
  *) echo "::error::runtime must be node|python|go|rust|solidity, got '$runtime'" >&2; exit 1 ;;
esac

# Sensible package manager per runtime so most manifests can omit it.
if [[ -z "$package_manager" ]]; then
  case "$runtime" in
    node|solidity) package_manager=npm ;;
    python)        package_manager=uv ;;
    go)            package_manager=gomod ;;
    rust)          package_manager=cargo ;;
  esac
fi

test_command="$(q '.test.command' '')"
lint_command="$(q '.test.lint' '')"
coverage_min="$(q '.test.coverage_min' '0')"
ai_review="$(q '.test.ai_review' 'false')"

# --- tester agent (TRD §3.2). Everything is opt-in and bounded by default. ----
tester_enabled="$(q '.test.tester_agent.enabled' 'false')"
tester_base_url_secret="$(q '.test.tester_agent.scope.base_url_secret' 'TESTER_BASE_URL')"
tester_openapi="$(q '.test.tester_agent.scope.openapi' '')"
tester_mutating="$(q '.test.tester_agent.scope.mutating' 'false')"
tester_model="$(q '.test.tester_agent.model' 'deepseek-deepseek-v4-flash')"

slo_p95_ms="$(q '.test.tester_agent.slo.latency_p95_ms' '0')"
slo_p99_ms="$(q '.test.tester_agent.slo.latency_p99_ms' '0')"
slo_error_pct="$(q '.test.tester_agent.slo.error_rate_pct' '0')"

soak_enabled="$(q '.test.tester_agent.soak.enabled' 'false')"
soak_iterations="$(q '.test.tester_agent.soak.iterations' '20')"
soak_budget_minutes="$(q '.test.tester_agent.soak.budget_minutes' '10')"
soak_budget_usd="$(q '.test.tester_agent.soak.token_budget_usd' '3')"
soak_gate_on="$(yq -r '.test.tester_agent.soak.gate_on // ["functional_high","latency_p95_slo"] | join(",")' "$MANIFEST")"

monitor_enabled="$(q '.test.tester_agent.monitor.enabled' 'false')"
monitor_schedule="$(q '.test.tester_agent.monitor.schedule' '0 */6 * * *')"
monitor_target="$(q '.test.tester_agent.monitor.target' 'staging')"

# --- findings routing (TRD §8) ------------------------------------------------
issues_repo="$(q '.report.issues.repo' 'self')"
auto_close_after_runs="$(q '.report.issues.auto_close_after_runs' '3')"
lark_notify_on="$(yq -r '.report.lark.notify_on // ["gate_block","new_high","auto_resolved"] | join(",")' "$MANIFEST")"
baseline_metric="$(q '.report.baselines.metric' 'p95')"
baseline_drift_pct="$(q '.report.baselines.drift_pct' '30')"
baseline_sustained_runs="$(q '.report.baselines.sustained_runs' '2')"

dockerfile="$(q '.build.dockerfile' 'Dockerfile')"
context="$(q '.build.context' '.')"
image="$(q '.build.image' "ghcr.io/${REPO}")"
image="$(printf '%s' "$image" | tr '[:upper:]' '[:lower:]')"

target="$(q '.deploy.target' 'none')"
registry_user="$(q '.deploy.registry_user' '')"
service="$(q '.deploy.service' "$component")"
container_name="$(q '.deploy.container_name' "${project}-${component}")"
compose_file="$(q '.deploy.compose_file' 'docker-compose.prod.yml')"
# One directory per component. Components can share a VM without their compose
# files, env files or rollbacks ever colliding.
remote_path="$(q '.deploy.remote_path' "/opt/${project}/${component}")"
health_path="$(q '.deploy.health.path' '')"
health_port="$(q '.deploy.health.port' '')"
# A phased VM release: one-shot compose services (bootstrap, backup, migrate...)
# that run in order before the long-running services. Empty keeps the original
# single-service `--no-deps` roll.
phases="$(yq -r '.deploy.phases // [] | join(" ")' "$MANIFEST")"
services="$(yq -r '.deploy.services // [] | join(" ")' "$MANIFEST")"
if [[ -z "$services" ]]; then
  services="$service"
fi
# Once this phase has started, the schema may have changed, so a failed release
# is left stopped for a person instead of being rolled back to the previous image.
migration_phase="$(q '.deploy.migration_phase' '')"
# Extra paths shipped beside the compose file (for example the SQL the database
# container mounts at first initialisation).
ship="$(yq -r '.deploy.ship // [] | join(" ")' "$MANIFEST")"
# A command run on the VM, in the component's directory, before the release
# changes anything there. Non-zero aborts the release with the box untouched.
preflight="$(q '.deploy.preflight' '')"
# target: mirror pushes the validated commit to a repository a hosting provider
# builds from (a Vercel project owned by a machine account, for example).
mirror_repo="$(q '.deploy.mirror.repo' '')"
mirror_user="$(q '.deploy.mirror.user' '')"
if [[ "$target" == "mirror" && -z "$mirror_repo" ]]; then
  echo "::error::deploy.target is mirror but deploy.mirror.repo is missing" >&2
  exit 1
fi
if [[ -n "$migration_phase" && " $phases " != *" $migration_phase "* ]]; then
  echo "::error::deploy.migration_phase '$migration_phase' is not one of deploy.phases" >&2
  exit 1
fi

# Resolve which environment this ref deploys to. A pull request never deploys.
#
# An environment's trigger is `push` (every push to its branch deploys: the
# original deploy-branch model) or `dispatch` (only a manual run on its branch
# that names it). `dispatch` lets main carry reviewed source without every merge
# reaching production: a release is a deliberate run of the same pipeline, gates
# included, on a main commit.
requested="${DISPATCH_ENVIRONMENT:-}"
environment=""
url=""
mirror_branch=""
if [[ "$EVENT_NAME" == "push" || "$EVENT_NAME" == "workflow_dispatch" ]]; then
  while IFS= read -r env; do
    if [[ -z "$env" ]]; then continue; fi
    branch="$(q ".deploy.environments.${env}.branch" '')"
    trigger="$(q ".deploy.environments.${env}.trigger" 'push')"
    if [[ "$branch" != "$REF_NAME" ]]; then continue; fi
    case "$trigger" in
      push)
        if [[ -n "$requested" && "$requested" != "$env" ]]; then continue; fi
        ;;
      dispatch)
        if [[ "$EVENT_NAME" != "workflow_dispatch" || "$requested" != "$env" ]]; then continue; fi
        ;;
      *)
        echo "::error::deploy.environments.${env}.trigger must be push|dispatch, got '$trigger'" >&2
        exit 1
        ;;
    esac
    environment="$env"
    url="$(q ".deploy.environments.${env}.url" '')"
    mirror_branch="$(q ".deploy.environments.${env}.mirror_branch" "$env")"
    break
  done < <(yq -r '.deploy.environments // {} | keys | .[]' "$MANIFEST")
fi
if [[ -n "$requested" && -z "$environment" ]]; then
  echo "::error::A deploy to '$requested' was requested, but '$REF_NAME' is not its branch." >&2
  exit 1
fi

should_build=false
should_deploy=false
if [[ -n "$environment" && "$target" != "none" ]]; then
  should_deploy=true
  # Frontends deploy from source via the Vercel CLI; everything else ships an image.
  if [[ "$target" == "vm" ]]; then
    should_build=true
  fi
fi

# Soak runs only against staging, only when both the agent and soak are enabled,
# and only when this ref actually deployed something to test.
should_soak=false
if [[ "$tester_enabled" == "true" && "$soak_enabled" == "true" && "$should_deploy" == "true" && "$environment" == "staging" ]]; then
  should_soak=true
fi

emit project "$project"
emit component "$component"
emit type "$type"
emit runtime "$runtime"
emit package_manager "$package_manager"
emit test_command "$test_command"
emit lint_command "$lint_command"
emit coverage_min "$coverage_min"
emit ai_review "$ai_review"
emit dockerfile "$dockerfile"
emit context "$context"
emit image "$image"
emit target "$target"
emit registry_user "$registry_user"
emit service "$service"
emit container_name "$container_name"
emit compose_file "$compose_file"
emit remote_path "$remote_path"
emit health_path "$health_path"
emit health_port "$health_port"
emit phases "$phases"
emit services "$services"
emit migration_phase "$migration_phase"
emit ship "$ship"
emit preflight "$preflight"
emit mirror_repo "$mirror_repo"
emit mirror_user "$mirror_user"
emit mirror_branch "$mirror_branch"
emit environment "$environment"
emit url "$url"
emit should_build "$should_build"
emit should_deploy "$should_deploy"

emit tester_enabled "$tester_enabled"
emit tester_base_url_secret "$tester_base_url_secret"
emit tester_openapi "$tester_openapi"
emit tester_mutating "$tester_mutating"
emit tester_model "$tester_model"
emit slo_p95_ms "$slo_p95_ms"
emit slo_p99_ms "$slo_p99_ms"
emit slo_error_pct "$slo_error_pct"
emit soak_enabled "$soak_enabled"
emit soak_iterations "$soak_iterations"
emit soak_budget_minutes "$soak_budget_minutes"
emit soak_budget_usd "$soak_budget_usd"
emit soak_gate_on "$soak_gate_on"
emit monitor_enabled "$monitor_enabled"
emit monitor_schedule "$monitor_schedule"
emit monitor_target "$monitor_target"
emit should_soak "$should_soak"
emit issues_repo "$issues_repo"
emit auto_close_after_runs "$auto_close_after_runs"
emit lark_notify_on "$lark_notify_on"
emit baseline_metric "$baseline_metric"
emit baseline_drift_pct "$baseline_drift_pct"
emit baseline_sustained_runs "$baseline_sustained_runs"

{
  echo "### Manifest — \`${project}/${component}\`"
  echo ""
  echo "| field | value |"
  echo "|---|---|"
  echo "| type / runtime | \`${type}\` / \`${runtime}\` (${package_manager}) |"
  echo "| test command | \`${test_command:-–}\` |"
  echo "| coverage floor | ${coverage_min}% |"
  echo "| deploy target | \`${target}\` |"
  echo "| environment | \`${environment:-none (no deploy for this ref)}\` |"
  echo "| image | \`${image}\` |"
} >>"$GITHUB_STEP_SUMMARY"
