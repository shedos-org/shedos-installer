# shedos-installer

What installs ShedOS: the nine Calamares job modules under
`calamares/modules-src/`, the module configuration and branding they run with,
and the `shedos_installer` Python library they import for hardware detection,
bootloader assembly and Secure Boot enrolment.

Until this package existed the library was never packaged at all — the ISO
build copied `installer/shedos_installer` into `/opt/shedos-installer` and the
modules reached it with a `sys.path.insert` naming that directory. The package
installs it at `/usr/lib/shedos-installer` and the two modules that import it
name that path instead. `test/install-paths` holds the three of them together:
the PKGBUILD's install root and both modules' `INSTALLER_ROOT` have to agree,
and the suite reddens when one of them moves.

Two files this code reads belong to other packages, and neither is copied here:

- `/usr/share/shedos/nvidia-driver-stack`, which shedos-system ships and
  `/usr/lib/shedos/nvidia-reap` reads. `shedos_nvidia` reads the same file, so
  the list of NVIDIA packages a fresh install adds or strips exists once.
- `/usr/share/shedos/wallpapers/shedos-default.png`, which shedos-branding
  ships and `shedos_configs` copies into the new user's home.

`test/shared-data` asks the installed packages for both, so a file that moves
or a package that stops shipping it fails here rather than during someone's
install.

The pytest suite is `tests/`, run in CI through `test/installer/run.sh` like
every other suite in the fleet. It covers the library and loads each Calamares
module by path with a stubbed `libcalamares`, which is the only way to exercise
them outside a running installer.

The package is installer-only: the ISO carries it, an installed system keeps
the copy the squashfs left behind, and nothing about it reaches the public
repository or the meta package.
