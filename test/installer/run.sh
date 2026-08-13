#!/usr/bin/env bash
# run.sh — runs the installer's pytest suite (Calamares modules +
# shedos_installer core). Lives here so CI's test/*/run.sh discovery
# picks it up; the suite itself is tests/.

set -uo pipefail

here=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
repo_root=$(cd -- "$here/../.." && pwd)

# No skip lane. The pipeline installs python-pytest for this suite, and a
# missing interpreter here means the suite the package's behaviour rests on
# did not run at all.
if ! command -v pytest > /dev/null 2>&1 \
    && ! python3 -c 'import pytest' 2> /dev/null; then
    echo "pytest is not installed — the installer suite cannot run" >&2
    exit 2
fi

cd "$repo_root" || exit 2
exec python3 -m pytest tests/ -q
