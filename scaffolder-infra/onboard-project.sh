#!/usr/bin/env bash
# =============================================================================
# onboard-project.sh — stand up a whole project in one run.
#
# Ties the platform's pieces into one ordered flow: generate the infra
# declaration → provision (VM + DNS) → wire deploy secrets → bring up the edge
# (Traefik + Postgres) → tell you the one push per component that finishes it.
#
# Each phase is idempotent and guarded; re-running resumes rather than duplicates.
#
#   ./onboard-project.sh \
#     --project tasmil --domain tasmil.finance --cloud aws \
#     --components api,mcp,ai \
#     --cf-token-file <(sops -d --extract '["cf_api_token_tasmil"]' vault.enc.yaml) \
#     --acme-email ops@tasmil.finance
#
# Requires: terraform, gh (repo admin), jq, ssh, and either copier or a
# pre-existing infra/projects/<project>. Cloud creds come from your own session
# (AWS SSO / gcloud ADC) — never a static key.
# =============================================================================
set -Eeuo pipefail

ORG="${ORG:-devsecops-playground-org}"
project="" domain="" cloud="aws" components="api" cf_token_file="" acme_email="" infra_dir="" key_path="" gcp_project=""

die() { echo "error: $*" >&2; exit 1; }
step() { printf '\n\033[1m━━ %s\033[0m\n' "$*"; }

while [ $# -gt 0 ]; do
  case "$1" in
    --project) project="$2"; shift 2 ;;
    --domain) domain="$2"; shift 2 ;;
    --cloud) cloud="$2"; shift 2 ;;              # aws | gcp
    --components) components="$2"; shift 2 ;;    # comma list, e.g. api,mcp,ai
    --cf-token-file) cf_token_file="$2"; shift 2 ;;
    --acme-email) acme_email="$2"; shift 2 ;;
    --key) key_path="$2"; shift 2 ;;             # deploy private key (generated if absent)
    --gcp-project) gcp_project="$2"; shift 2 ;;
    --infra-dir) infra_dir="$2"; shift 2 ;;
    --org) ORG="$2"; shift 2 ;;
    *) die "unknown arg: $1" ;;
  esac
done
[ -n "$project" ] || die "pass --project"
[ -n "$domain" ]  || die "pass --domain"
infra_dir="${infra_dir:-infra/projects/$project}"
key_path="${key_path:-$HOME/.ssh/${project}-deploy}"
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ---------------------------------------------------------------------------
step "1/6  Deploy keypair"
if [ ! -f "$key_path" ]; then
  ssh-keygen -t ed25519 -f "$key_path" -N '' -C "ci-deploy@$project" -q
  echo "generated $key_path"
else
  echo "reusing $key_path"
fi
pubkey="$(cat "${key_path}.pub")"

# ---------------------------------------------------------------------------
step "2/6  Generate infra declaration (infra/projects/$project)"
if [ -d "$infra_dir" ]; then
  echo "$infra_dir exists — skipping generation"
else
  command -v copier >/dev/null || die "copier not installed and $infra_dir absent"
  vmcomp_json="$(printf '%s' "$components" | jq -R 'split(",")')"
  copier copy --trust --defaults \
    "gh:$ORG/platform//scaffolder-infra" "$infra_dir" \
    --data project="$project" --data domain="$domain" \
    --data vm_cloud="$cloud" --data "vm_components=$vmcomp_json" \
    ${gcp_project:+--data gcp_project_id="$gcp_project"}
  echo "generated $infra_dir — set dns_zone_id + deploy_public_key in terraform.tfvars, and add '$project' to the terraform.yml matrix."
  echo "::note:: review the generated files, then re-run to continue."
  exit 0
fi

# ---------------------------------------------------------------------------
step "3/6  Provision (terraform apply)"
echo "In the real flow this is a reviewed PR → gated apply. Locally:"
echo "  terraform -chdir=$infra_dir apply"
read -rp "Run terraform apply now? [y/N] " ans
[ "$ans" = "y" ] && terraform -chdir="$infra_dir" apply || echo "skipped — assuming already applied."

# ---------------------------------------------------------------------------
step "4/6  Wire deploy secrets (VM_HOST/USER/SSH_KEY per component repo)"
"$here/wire-deploy-secrets.sh" --project "$project" --key "$key_path" --org "$ORG" --infra-dir "$infra_dir"

# ---------------------------------------------------------------------------
step "5/6  Bring up the edge (Traefik + Postgres) on the VM"
vm_ip="$(terraform -chdir="$infra_dir" output -json vm_hosts 2>/dev/null | jq -r '.production // .staging // empty')"
[ -n "$vm_ip" ] || die "no vm_hosts output — is the project applied?"
[ -n "$cf_token_file" ] || die "pass --cf-token-file (Cloudflare token for $domain) to bring up auto-TLS edge"
[ -n "$acme_email" ] || die "pass --acme-email for Let's Encrypt"
cf_token="$(cat "$cf_token_file")"
pg_pass="$(openssl rand -hex 24)"
ssh -i "$key_path" -o StrictHostKeyChecking=accept-new "deploy@$vm_ip" \
  "mkdir -p /opt/$project/edge"
scp -i "$key_path" "$here/../shared-services/docker-compose.yml" "deploy@$vm_ip:/opt/$project/edge/docker-compose.yml"
ssh -i "$key_path" -o StrictHostKeyChecking=accept-new "deploy@$vm_ip" bash -se <<REMOTE
set -euo pipefail
cd /opt/$project/edge
PROJECT=$project DOMAIN=$domain ACME_EMAIL=$acme_email \
CF_DNS_API_TOKEN='$cf_token' POSTGRES_USER=app POSTGRES_PASSWORD='$pg_pass' POSTGRES_DB=$project \
docker compose -p ${project}-edge up -d
docker compose -p ${project}-edge ps
REMOTE
echo "Edge up. Store DATABASE_URL in your secrets manager:"
echo "  postgres://app:${pg_pass}@postgres:5432/$project"

# ---------------------------------------------------------------------------
step "6/6  Ship the components"
echo "For each component repo, push its deploy branch:"
IFS=',' read -ra comps <<<"$components"
for c in "${comps[@]}"; do
  echo "  git -C $project-$c push origin HEAD:deploy/prod   # → $c.$domain (auto-TLS via Traefik)"
done
echo ""
echo "Done. Frontend deploys to Vercel on its own push; env for all comes from the secrets manager."
