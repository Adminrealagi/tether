#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SPEC="${ROOT}/agent[telegram,slack,discord,ssh,litellm,mcp]"

if ! command -v pipx >/dev/null 2>&1; then
  echo "pipx is required to install Tether on the user PATH." >&2
  exit 1
fi

echo "Installing editable Tether from ${ROOT} via pipx ..."
pipx install --force --editable "$SPEC"
echo "Editable install refreshed. Re-run this script after rebuilding local changes."
