#!/usr/bin/env bash
set -eo pipefail

platform_root="$(cd -- "$(dirname -- "$0")" && pwd)"
exec node "$platform_root/dev-tools/git-ui/start.mjs" "$@"
