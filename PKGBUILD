# Maintainer: ShedOS <https://github.com/Theshedman/shedos>
#
# What installs ShedOS: the job modules ShedOS adds to the Calamares sequence,
# the module configuration and branding they run with, and the Python library
# they import. Installer-only — the ISO carries it, and an installed system
# keeps the copy the squashfs left behind.

pkgname=shedos-installer
pkgver=2026.08.09.2
pkgrel=2
pkgdesc='ShedOS Calamares modules, their configuration and the library behind them'
arch=('any')
url='https://github.com/shedos-org/shedos-installer'
license=('GPL-3.0-or-later')
# The modules only ever run from the live ISO, and the tools they drive
# (pacman, mkinitcpio, limine, sbctl, cryptsetup) come from its package list.
# Naming them here would pin the whole installer toolchain onto every machine
# ShedOS installs, because this package rides the squashfs onto the target.
# What is named is what this code reads directly.
depends=(
    'python'           # the library and every module are python3
    'calamares'        # loads the modules and reads the configuration below
    'shedos-branding'  # /usr/share/shedos/wallpapers/shedos-default.png, the
                       # wallpaper shedos_configs deploys into the new home
    'shedos-system'    # /usr/share/shedos/nvidia-driver-stack, the package
                       # list shedos_nvidia installs and strips
)

# The descriptor ships saying DEVELOPMENT, because the package is built without
# knowing which release it rides, and the ISO build rewrites its four version
# fields during pacstrap. That makes the installed copy a local edit, and
# without this pacman would replace it on the next upgrade and leave no .pacnew
# to notice by. Nothing else under /etc/calamares is written to after install.
backup=(
    'etc/calamares/branding/shedos/branding.desc'
)

source=("git+https://github.com/shedos-org/shedos-installer.git#tag=$pkgver")
sha256sums=('SKIP')

# Where the library lands, and the path both modules that import it name. Not
# site-packages: a python minor-version bump moves that directory out from
# under an ISO built before it, and the installer is the one thing on the ISO
# that cannot answer an ImportError.
_libroot=usr/lib/shedos-installer

package() {
    cd "$srcdir/$pkgname"

    # The library. Sources only: a stale .pyc beside a fresh .py makes python
    # load the old bytecode on the read-only squashfs, where it cannot
    # recompile.
    local _py
    while IFS= read -r _py; do
        install -Dm644 "$_py" "$pkgdir/$_libroot/$_py"
    done < <(find shedos_installer -name '*.py' | LC_ALL=C sort)

    # The job modules, where settings.conf's modules-search looks for them.
    # Whole directories rather than main.py and module.desc by name, so a
    # module that grows a third file ships it. __pycache__ stays out: python
    # loads stale bytecode in preference to the fresh .py beside it, and the
    # squashfs it would load from is read-only.
    local _mod
    while IFS= read -r _mod; do
        install -Dm644 "$_mod" \
            "$pkgdir/usr/lib/calamares/modules/${_mod#calamares/modules-src/}"
    done < <(find calamares/modules-src -type f -not -path '*/__pycache__/*' \
        | LC_ALL=C sort)

    # The sequence and the per-module configuration, at the path Calamares
    # reads without being told where to look.
    install -Dm644 calamares/settings.conf "$pkgdir/etc/calamares/settings.conf"
    local _conf
    for _conf in calamares/modules/*.conf; do
        install -Dm644 "$_conf" \
            "$pkgdir/etc/calamares/modules/$(basename "$_conf")"
    done

    # Branding: the slide deck and the QML that shows it, whole rather than
    # file by file, because a slide added to the deck has to ship with it.
    local _asset
    while IFS= read -r _asset; do
        install -Dm644 "$_asset" \
            "$pkgdir/etc/calamares/branding/shedos/${_asset#calamares/branding/shedos/}"
    done < <(find calamares/branding/shedos -type f | LC_ALL=C sort)
}
