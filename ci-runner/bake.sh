#!/usr/bin/env bash
# Runs once on a clean Ubuntu 24.04 x86-64 builder, before CreateImage.
set -euo pipefail
# SSM returns only the first 24 KiB of stdout. Keep package-install chatter
# on disk and reserve stdout for the compressed inventory qualification record.
exec 3>&1 4>&2
exec > /var/log/arteamis-ci-bake.log 2>&1
archive=''
aws_work=''
cleanup() {
  local status=$1
  if [[ -n "$archive" ]]; then rm -f -- "$archive"; fi
  if [[ -n "$aws_work" ]]; then rm -rf -- "$aws_work"; fi
  if (( status != 0 )); then
    printf 'Arteamis CI bake failed; last diagnostic lines:\n' >&4
    tail -n 40 /var/log/arteamis-ci-bake.log >&4
  fi
  return "$status"
}
trap 'cleanup "$?"' EXIT
export DEBIAN_FRONTEND=noninteractive
runner_version=2.338.0
runner_sha256=af4b794c1bc41d73d40535e3fe092a39f9679cd8d965954c2aca25a05ca41d32
aws_version=2.36.40
aws_sha256=a904e314340ad4c4b62beb50e9259d4becb2acf3dffc86c96c553c834d7fdf7a
apt-get update
apt-get install -y ca-certificates curl git jq unzip python3 python3-pip python3-venv pipx docker.io docker-compose-v2 sudo \
  nodejs npm build-essential pkg-config libssl-dev openssh-client rsync zstd shellcheck \
  libnss3 libnspr4 libatk1.0-0t64 libatk-bridge2.0-0t64 libcups2t64 \
  libdrm2 libdbus-1-3 libxcb1 libxkbcommon0 libx11-6 libxcomposite1 \
  libxdamage1 libxext6 libxfixes3 libxrandr2 libgbm1 libpango-1.0-0 \
  libcairo2 libasound2t64 fonts-liberation
systemctl enable docker
docker compose version
# GitHub CLI used by release-record steps. Ubuntu provides a maintained package.
apt-get install -y gh
gh --version
install -d -o ubuntu -g ubuntu /opt/hostedtoolcache

usermod -aG docker ubuntu
install -d -o ubuntu -g ubuntu /opt/arteamis-runner
archive=$(mktemp)
aws_work=$(mktemp -d)
curl --fail --silent --show-error --location \
  "https://awscli.amazonaws.com/awscli-exe-linux-x86_64-${aws_version}.zip" --output "$aws_work/aws.zip"
printf '%s  %s\n' "$aws_sha256" "$aws_work/aws.zip" | sha256sum --check --status
unzip -q "$aws_work/aws.zip" -d "$aws_work"
"$aws_work/aws/install" --install-dir /opt/aws-cli --bin-dir /usr/local/bin
curl --fail --silent --show-error --location \
  "https://github.com/actions/runner/releases/download/v${runner_version}/actions-runner-linux-x64-${runner_version}.tar.gz" \
  --output "$archive"
printf '%s  %s\n' "$runner_sha256" "$archive" | sha256sum --check --status
tar -xzf "$archive" -C /opt/arteamis-runner
/opt/arteamis-runner/bin/installdependencies.sh
chown -R ubuntu:ubuntu /opt/arteamis-runner
test -s /opt/arteamis-runner/bin/Runner.Listener
test "$(cd /opt/arteamis-runner && runuser -u ubuntu -- ./bin/Runner.Listener --version)" = "$runner_version"
aws --version
python3 - <<'PY'
import json, platform, subprocess
from pathlib import Path
Path('/opt/arteamis-runner/ami-source.json').write_text(json.dumps({
    'runnerVersion': '2.338.0',
    'runnerSha256': 'af4b794c1bc41d73d40535e3fe092a39f9679cd8d965954c2aca25a05ca41d32',
    'awsCliVersion': '2.36.40',
    'architecture': platform.machine(),
    'packages': subprocess.check_output(['dpkg-query', '-W'], text=True).splitlines(),
}, indent=2) + '\n')
PY
# The AMI contains binaries only. No runner registration or job workspace is baked.
test ! -e /opt/arteamis-runner/.runner
test ! -e /opt/arteamis-runner/.credentials
test ! -e /opt/arteamis-runner/_work
# Let every cloned VM process its own user data and receive a fresh machine ID.
cloud-init clean --logs --machine-id
# Flush the installed binaries and ownership before the normal CreateImage reboot.
sync

# Only the inventory uses the original stdout descriptor.
{
  printf 'ARTEAMIS_INVENTORY='
  gzip -c /opt/arteamis-runner/ami-source.json | base64 -w0
  printf '\n'
} >&3
