#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [[ ! -x "${repo_root}/.venv/bin/go-daddy-skill" ]]; then
  printf '%s\n' "Missing ${repo_root}/.venv. Run: uv venv .venv && source .venv/bin/activate && uv pip install -e '.[dev]'" >&2
  exit 2
fi

exec "${repo_root}/.venv/bin/go-daddy-skill" "$@"
