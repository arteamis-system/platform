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
q() {
  local out
  out="$(yq -r "$1 // \"\"" "$MANIFEST")"
  [[ -z "$out" || "$out" == "null" ]] && out="$2"
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
    [[ -z "$env" ]] && continue
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
  [[ "$target" == "vm" ]] && should_build=true
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
