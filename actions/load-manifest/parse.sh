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
service="$(q '.deploy.service' "$component")"
container_name="$(q '.deploy.container_name' "${project}-${component}")"
compose_file="$(q '.deploy.compose_file' 'docker-compose.prod.yml')"
# One directory per component. Components can share a VM without their compose
# files, env files or rollbacks ever colliding.
remote_path="$(q '.deploy.remote_path' "/opt/${project}/${component}")"
health_path="$(q '.deploy.health.path' '')"
health_port="$(q '.deploy.health.port' '')"

# Resolve which environment this ref deploys to. A pull request never deploys.
environment=""
url=""
if [[ "$EVENT_NAME" == "push" || "$EVENT_NAME" == "workflow_dispatch" ]]; then
  while IFS= read -r env; do
    if [[ -z "$env" ]]; then continue; fi
    branch="$(q ".deploy.environments.${env}.branch" '')"
    if [[ "$branch" == "$REF_NAME" ]]; then
      environment="$env"
      url="$(q ".deploy.environments.${env}.url" '')"
      break
    fi
  done < <(yq -r '.deploy.environments // {} | keys | .[]' "$MANIFEST")
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
emit service "$service"
emit container_name "$container_name"
emit compose_file "$compose_file"
emit remote_path "$remote_path"
emit health_path "$health_path"
emit health_port "$health_port"
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
