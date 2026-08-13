#!/usr/bin/env bash
# Two files this code reads belong to other packages: the NVIDIA package list
# shedos-system publishes for everything that adds or strips the stack as a
# set, and the wallpaper shedos-branding ships. Neither is copied here, so what
# has to be checked is that they are where the code looks and that the package
# named in depends is what put them there.
set -uo pipefail

here=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
repo_root=$(cd -- "$here/../.." && pwd)

pass=0; fail=0; failures=()
_ok()   { printf 'ok: %s\n' "$1"; pass=$((pass + 1)); }
_fail() { printf 'FAIL: %s — %s\n' "$1" "$2" >&2; failures+=("$1"); fail=$((fail + 1)); }

# Both paths are read out of the code that uses them rather than restated, so
# a path that moves is a path this suite follows.
stack_file=$(sed -n 's/^STACK_FILE = "\(.*\)"$/\1/p' \
    "$repo_root/shedos_installer/driver_stack.py" | head -1)
wallpaper=$(sed -n 's/^WALLPAPER = Path("\(.*\)")$/\1/p' \
    "$repo_root/calamares/modules-src/shedos_configs/main.py" | head -1)

owner_of() { pacman -Qoq "$1" 2> /dev/null; }

# D1: shedos-system ships the list, at the path the library asks for.
if [[ -n $stack_file && -r $stack_file ]]; then
    owner=$(owner_of "$stack_file")
    if [[ $owner == shedos-system ]]; then
        _ok D1_shedos_system_ships_the_driver_stack
    else
        _fail D1_shedos_system_ships_the_driver_stack \
            "$stack_file is owned by '${owner:-no package}'"
    fi
else
    _fail D1_shedos_system_ships_the_driver_stack \
        "${stack_file:-no path in driver_stack.py} is not readable"
fi

# D2: and the library reads it as the packages it names. A file that exists but
# parses to nothing is the failure that would leave a fresh install carrying
# the whole NVIDIA stack on a machine with no NVIDIA card.
if got=$(cd "$repo_root" && python3 -c '
from shedos_installer.driver_stack import driver_stack
print("\n".join(driver_stack()))
' 2>&1); then
    want=$(grep -vE '^[[:space:]]*(#|$)' "$stack_file" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')
    if [[ -n $got && $got == "$want" ]]; then
        _ok D2_the_library_reads_the_whole_list
    else
        _fail D2_the_library_reads_the_whole_list \
            "the library reads $(wc -l <<< "$got") of $(wc -l <<< "$want") names"
    fi
else
    _fail D2_the_library_reads_the_whole_list "$got"
fi

# D3: shedos-branding ships the wallpaper shedos_configs copies into the new
# user's home. It used to be a second copy staged beside the installer.
if [[ -n $wallpaper && -r $wallpaper ]]; then
    owner=$(owner_of "$wallpaper")
    if [[ $owner == shedos-branding ]]; then
        _ok D3_shedos_branding_ships_the_wallpaper
    else
        _fail D3_shedos_branding_ships_the_wallpaper \
            "$wallpaper is owned by '${owner:-no package}'"
    fi
else
    _fail D3_shedos_branding_ships_the_wallpaper \
        "${wallpaper:-no path in shedos_configs} is not readable"
fi

echo
echo "shared-data: $pass/$((pass + fail)) passed"
if (( fail > 0 )); then printf '  %s\n' "${failures[@]}" >&2; exit 1; fi
exit 0
