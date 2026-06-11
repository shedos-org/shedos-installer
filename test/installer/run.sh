#!/usr/bin/env bash
# run.sh — runs the installer's pytest suite (Calamares modules +
# shedos_installer core). Lives here so CI's test/*/run.sh discovery
# picks it up; the suite itself is installer/tests/.

set -uo pipefail

here=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
repo_root=$(cd -- "$here/../.." && pwd)

if ! command -v pytest >/dev/null 2>&1 \
    && ! python3 -c 'import pytest' 2>/dev/null; then
    echo "SKIP: pytest not available" >&2
    exit 0
fi

cd "$repo_root/installer" || exit 2
exec python3 -m pytest tests/ -q
