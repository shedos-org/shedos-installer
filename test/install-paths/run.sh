#!/usr/bin/env bash
# The library is imported by absolute path: Calamares loads a module from
# /usr/lib/calamares/modules and nothing of the installer is on the import
# path, so each module that needs the library spells out where the package put
# it. That makes three places holding one answer — the PKGBUILD and the two
# modules — and this is what keeps them saying the same thing.
set -uo pipefail

here=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
repo_root=$(cd -- "$here/../.." && pwd)

pass=0; fail=0; failures=()
_ok()   { printf 'ok: %s\n' "$1"; pass=$((pass + 1)); }
_fail() { printf 'FAIL: %s — %s\n' "$1" "$2" >&2; failures+=("$1"); fail=$((fail + 1)); }

# Read from the PKGBUILD rather than restated here, so the build moving the
# library is what this suite notices.
libroot=$(
    bash -c 'source "$1" > /dev/null 2>&1; printf "/%s\n" "$_libroot"' \
        _ "$repo_root/PKGBUILD"
)

# P1: the build installs the library somewhere.
if [[ $libroot == /usr/* ]]; then
    _ok P1_library_root_is_absolute
else
    _fail P1_library_root_is_absolute "the PKGBUILD's _libroot reads '$libroot'"
fi

# P2: every module that imports the library names that same root. The list is
# the modules that insert a path, found rather than written down, so a third
# module joining them is held to it too.
mapfile -t importers < <(
    cd "$repo_root" && grep -rl 'sys\.path\.insert' calamares/modules-src | sort
)
if (( ${#importers[@]} == 0 )); then
    _fail P2_modules_name_the_root 'no module inserts an import path'
else
    mismatched=()
    for module in "${importers[@]}"; do
        root=$(sed -n 's/^INSTALLER_ROOT = Path("\(.*\)")$/\1/p' \
            "$repo_root/$module" | head -1)
        [[ $root == "$libroot" ]] || mismatched+=("$module names '${root:-nothing}'")
    done
    if (( ${#mismatched[@]} == 0 )); then
        _ok P2_modules_name_the_root
    else
        _fail P2_modules_name_the_root \
            "the package installs to $libroot but ${mismatched[*]}"
    fi
fi

# P3: the library the modules import is the one the build installs. Both sides
# read the same directory name, and an empty payload would satisfy P1 and P2
# without shipping a line of it, so the name the build reads is taken from it
# and looked for here.
libsrc=$(sed -n 's/.*find \([^ ]*\) -name .*\.py.*/\1/p' "$repo_root/PKGBUILD" | head -1)
if [[ -n $libsrc && -f $repo_root/$libsrc/__init__.py ]]; then
    _ok P3_the_build_installs_the_library
else
    _fail P3_the_build_installs_the_library \
        "the PKGBUILD collects the library from '${libsrc:-nothing}'"
fi

echo
echo "install-paths: $pass/$((pass + fail)) passed"
if (( fail > 0 )); then printf '  %s\n' "${failures[@]}" >&2; exit 1; fi
exit 0
