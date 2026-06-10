"""Unit tests for the Calamares custom Python modules.

These modules import `libcalamares`, which only exists inside
Calamares' runtime — we stub it via sys.modules before the
import-under-test fires.
"""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
MODULES_SRC = REPO_ROOT / "installer/calamares/modules-src"


@pytest.fixture
def fake_libcalamares(monkeypatch):
    fake = types.ModuleType("libcalamares")
    fake.globalstorage = MagicMock()
    fake.globalstorage.value.return_value = None
    fake_utils = types.ModuleType("libcalamares.utils")
    fake_utils.debug = MagicMock()
    fake_utils.warning = MagicMock()
    # shedos_gitconfig imports this name directly from libcalamares.utils
    # (via `from libcalamares.utils import check_target_env_call`); the
    # binding has to exist before module load.
    fake_utils.check_target_env_call = MagicMock()
    fake.utils = fake_utils
    monkeypatch.setitem(sys.modules, "libcalamares", fake)
    monkeypatch.setitem(sys.modules, "libcalamares.utils", fake_utils)
    return fake


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader, f"could not load {path}"
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ─── copykernel ─────────────────────────────────────────────────────


def test_copykernel_copies_each_kernel_and_initramfs(
    fake_libcalamares, monkeypatch, tmp_path,
):
    """For each /usr/lib/modules/*/pkgbase entry on the live ISO, copy
    vmlinuz to /target/boot/vmlinuz-<pkgbase> and matching initramfs."""
    target = tmp_path / "target"
    target.mkdir()

    fake_libcalamares.globalstorage.value.side_effect = lambda key: {
        "rootMountPoint": str(target),
    }.get(key)

    # Stage two fake "live ISO" kernels (different pkgbases).
    live_modules = tmp_path / "live-modules"
    for kver, pkgbase in [("7.0.3-arch1-2", "linux"),
                          ("7.0.11-zen1-1-zen", "linux-zen")]:
        d = live_modules / kver
        d.mkdir(parents=True)
        (d / "pkgbase").write_text(pkgbase + "\n")
        (d / "vmlinuz").write_bytes(b"\x7fELFvmlinuz")

    live_boot = tmp_path / "bootmnt"
    live_boot.mkdir()
    (live_boot / "initramfs-linux-zen.img").write_bytes(b"initramfs1")
    (live_boot / "initramfs-linux-zen-fallback.img").write_bytes(b"initramfs2")

    mod = _load_module(
        "copykernel_main", MODULES_SRC / "copykernel/main.py",
    )
    monkeypatch.setattr(mod.glob, "glob",
                        lambda pat: [str(p) for p in
                                     sorted(live_modules.glob("*/pkgbase"))])
    monkeypatch.setattr(mod, "_LIVE_BOOT_DIRS", (str(live_boot),))

    assert mod.run() is None
    boot = target / "boot"
    assert (boot / "vmlinuz-linux").read_bytes().startswith(b"\x7fELF")
    assert (boot / "vmlinuz-linux-zen").read_bytes().startswith(b"\x7fELF")
    assert (boot / "initramfs-linux-zen.img").read_bytes() == b"initramfs1"
    assert (boot / "initramfs-linux-zen-fallback.img").read_bytes() == b"initramfs2"


def test_copykernel_no_kernels_returns_error(
    fake_libcalamares, monkeypatch, tmp_path,
):
    """Live ISO with no /usr/lib/modules/*/pkgbase → fail loudly."""
    fake_libcalamares.globalstorage.value.side_effect = lambda key: {
        "rootMountPoint": str(tmp_path),
    }.get(key)

    mod = _load_module(
        "copykernel_main_nokernels", MODULES_SRC / "copykernel/main.py",
    )
    monkeypatch.setattr(mod.glob, "glob", lambda pat: [])

    result = mod.run()
    assert result is not None
    title, _body = result
    assert "No kernels" in title


# ─── shedos_gitconfig ───────────────────────────────────────────────


def test_gitconfig_writes_with_fullname(fake_libcalamares, tmp_path):
    target = tmp_path / "target"
    user_home = target / "home" / "alice"
    user_home.mkdir(parents=True)

    fake_libcalamares.globalstorage.value.side_effect = lambda k: {
        "username": "alice",
        "fullName": "Alice Example",
        "rootMountPoint": str(target),
    }.get(k)

    mod = _load_module(
        "shedos_gitconfig_main", MODULES_SRC / "shedos_gitconfig/main.py",
    )
    assert mod.run() is None

    gitconfig = user_home / ".gitconfig"
    content = gitconfig.read_text()
    assert "name = Alice Example" in content
    assert "defaultBranch = main" in content
    assert "editor = nvim" in content


def test_gitconfig_falls_back_to_username(fake_libcalamares, tmp_path):
    """Missing fullName → username is used as the git user.name."""
    target = tmp_path / "target"
    (target / "home" / "bob").mkdir(parents=True)

    fake_libcalamares.globalstorage.value.side_effect = lambda k: {
        "username": "bob",
        "fullName": None,
        "rootMountPoint": str(target),
    }.get(k)

    mod = _load_module(
        "shedos_gitconfig_main_fallback",
        MODULES_SRC / "shedos_gitconfig/main.py",
    )
    assert mod.run() is None
    assert "name = bob" in (target / "home" / "bob" / ".gitconfig").read_text()


def test_gitconfig_returns_none_when_username_missing(fake_libcalamares):
    """No username → warn and return None. No file is written."""
    fake_libcalamares.globalstorage.value.side_effect = lambda k: None
    mod = _load_module(
        "shedos_gitconfig_main_nouser",
        MODULES_SRC / "shedos_gitconfig/main.py",
    )
    assert mod.run() is None
    fake_libcalamares.utils.warning.assert_called()


# ─── shedos_limine ──────────────────────────────────────────────────


def test_limine_returns_error_when_partitions_missing(fake_libcalamares):
    """No partitions in globalstorage → install can't proceed."""
    fake_libcalamares.globalstorage.value.side_effect = lambda k: {
        "rootMountPoint": "/tmp/anywhere",
        "partitions": None,
    }.get(k)
    mod = _load_module(
        "shedos_limine_main_nopart",
        MODULES_SRC / "shedos_limine/main.py",
    )
    result = mod.run()
    assert result is not None
    title, _ = result
    assert "partitions" in title.lower()


def test_limine_returns_error_when_root_uuid_missing(
    fake_libcalamares, monkeypatch,
):
    """Partitions present but no root partition → can't compose cmdline."""
    fake_libcalamares.globalstorage.value.side_effect = lambda k: {
        "rootMountPoint": "/tmp/anywhere",
        "partitions": [
            {"mountPoint": "/boot/efi", "device": "/dev/sda1", "uuid": "esp"},
        ],
    }.get(k)
    mod = _load_module(
        "shedos_limine_main_nouuid",
        MODULES_SRC / "shedos_limine/main.py",
    )
    # Don't actually mount anything; pretend UEFI is off so the ESP
    # branch is skipped and we land in the root-uuid check.
    monkeypatch.setattr(mod, "is_uefi", lambda: False)
    result = mod.run()
    assert result is not None
    title, _ = result
    assert "root" in title.lower()


def test_limine_install_cmdline_includes_ux_baseline_tokens():
    """Install-time cmdline must carry the four UX-critical tokens so
    a fresh install has no framebuffer console flash on first boot —
    they cannot wait for the user's first `shedman apply`."""
    sys.path.insert(0, str(REPO_ROOT / "installer"))
    try:
        from shedos_installer.core.bootloader import LimineInstaller
    finally:
        sys.path.pop(0)
    inst = LimineInstaller(
        root_uuid="11111111-1111-1111-1111-111111111111",
    )
    tokens = inst._build_cmdline().split()
    for required in (
        "loglevel=3",
        "rd.udev.log_level=3",
        "fbcon=nodefer",
    ):
        assert required in tokens, (
            f"{required!r} missing from install-time cmdline; a fresh "
            f"install will show a console flash on first boot."
        )
    # console=tty1 must NOT be present: it triggers Plymouth's serial-
    # console heuristic, force-falling-back to the text-only details
    # plugin and breaking the graphical shutdown brand.
    assert "console=tty1" not in tokens, (
        "console=tty1 must not be in install-time cmdline — it disables "
        "Plymouth's graphical splash at shutdown."
    )
    # fbcon=nodefer,map:99 must NOT be present: map:99 permanently
    # unmaps the FB console from every VT, silently breaking
    # Ctrl+Alt+F<N> TTY switching post-boot. The other flash
    # mitigations (clear-vt-text.sh, quiet/loglevel=3/journal
    # redirects) cover flash suppression without that side effect.
    assert "fbcon=nodefer,map:99" not in tokens, (
        "fbcon=nodefer,map:99 must not be in install-time cmdline — "
        "map:99 breaks VT switching."
    )


# ─── shedos_nvidia ──────────────────────────────────────────────────


def test_nvidia_skipped_when_globalstorage_false(fake_libcalamares):
    """shedos_install_nvidia=False → run() exits early with None."""
    fake_libcalamares.globalstorage.value.side_effect = lambda k: {
        "shedos_install_nvidia": False,
    }.get(k)
    mod = _load_module(
        "shedos_nvidia_main_skip", MODULES_SRC / "shedos_nvidia/main.py",
    )
    assert mod.run() is None
    # Should log a debug saying it was skipped, not invoke any commands.
    fake_libcalamares.utils.debug.assert_called()


def test_nvidia_uses_fallback_list_when_package_file_missing(
    fake_libcalamares, monkeypatch, tmp_path,
):
    """nvidia.txt missing → use the hardcoded fallback list and warn."""
    fake_libcalamares.globalstorage.value.side_effect = lambda k: {
        "shedos_install_nvidia": True,
        "rootMountPoint": str(tmp_path),
    }.get(k)

    mod = _load_module(
        "shedos_nvidia_main_fallback",
        MODULES_SRC / "shedos_nvidia/main.py",
    )
    monkeypatch.setattr(mod, "PACKAGE_DIR", tmp_path / "definitely-missing")
    monkeypatch.setattr(mod, "get_gpus", lambda: [])

    captured = []

    def fake_run_chroot(cmd, **kw):
        captured.append(cmd)
        from shedos_installer.utils.command import CommandResult
        return CommandResult(
            returncode=0, stdout="", stderr="", success=True,
        )

    monkeypatch.setattr(mod, "run_chroot", fake_run_chroot)

    assert mod.run() is None
    # Should warn about the missing nvidia.txt
    warned = any(
        "missing" in (c.args[0] if c.args else "")
        for c in fake_libcalamares.utils.warning.call_args_list
    )
    assert warned
    # First chroot call is the pacman install with the fallback set.
    pacman_cmd = next(
        c for c in captured if c[:3] == ["pacman", "-S", "--noconfirm"]
    )
    assert "nvidia-open-dkms" in pacman_cmd
    assert "nvidia-utils" in pacman_cmd


# ─── shedos_finalize ────────────────────────────────────────────────


def test_finalize_returns_error_when_rootmount_missing(fake_libcalamares):
    fake_libcalamares.globalstorage.value.side_effect = lambda k: None
    mod = _load_module(
        "shedos_finalize_main_noroot",
        MODULES_SRC / "shedos_finalize/main.py",
    )
    result = mod.run()
    assert result is not None
    title, _ = result
    assert "root mount point" in title.lower()


def test_finalize_returns_none_when_username_missing(
    fake_libcalamares, tmp_path,
):
    """rootMountPoint set but no username → warn and exit None."""
    fake_libcalamares.globalstorage.value.side_effect = lambda k: {
        "rootMountPoint": str(tmp_path),
        "username": None,
    }.get(k)
    mod = _load_module(
        "shedos_finalize_main_nouser",
        MODULES_SRC / "shedos_finalize/main.py",
    )
    assert mod.run() is None
    fake_libcalamares.utils.warning.assert_called()


def test_enable_one_service_first_strategy_succeeds(
    fake_libcalamares, monkeypatch, tmp_path,
):
    """The --root systemctl strategy reports rc=0 → return True without trying chroot."""
    mod = _load_module(
        "shedos_finalize_main_es",
        MODULES_SRC / "shedos_finalize/main.py",
    )

    calls = []

    def fake_run(cmd, *, capture=True):
        import subprocess as _sp
        calls.append(cmd)
        return _sp.CompletedProcess(
            args=cmd, returncode=0, stdout="", stderr="",
        )

    monkeypatch.setattr(mod, "_run", fake_run)
    result = mod._enable_one_service(str(tmp_path), tmp_path, "foo.service")
    assert result is True
    # Only the first (--root) strategy was attempted.
    assert len(calls) == 1
    assert any(arg.startswith("--root=") for arg in calls[0])


def test_enable_one_service_falls_back_to_chroot(
    fake_libcalamares, monkeypatch, tmp_path,
):
    """First strategy fails → second (chroot) is tried, succeeds → True."""
    mod = _load_module(
        "shedos_finalize_main_es_chroot",
        MODULES_SRC / "shedos_finalize/main.py",
    )

    calls = []

    def fake_run(cmd, *, capture=True):
        import subprocess as _sp
        calls.append(cmd)
        # First call (--root strategy) fails; second (chroot) succeeds.
        rc = 1 if len(calls) == 1 else 0
        return _sp.CompletedProcess(
            args=cmd, returncode=rc, stdout="", stderr="",
        )

    monkeypatch.setattr(mod, "_run", fake_run)
    result = mod._enable_one_service(str(tmp_path), tmp_path, "foo.service")
    assert result is True
    assert len(calls) == 2
    assert calls[1][0] == "arch-chroot"


# ─── shedos_configs ─────────────────────────────────────────────────


def test_configs_returns_error_when_rootmount_missing(fake_libcalamares):
    fake_libcalamares.globalstorage.value.side_effect = lambda k: None
    mod = _load_module(
        "shedos_configs_main_noroot",
        MODULES_SRC / "shedos_configs/main.py",
    )
    result = mod.run()
    assert result is not None
    title, _ = result
    assert "root mount point" in title.lower()


def test_configs_returns_none_when_username_missing(
    fake_libcalamares, tmp_path,
):
    fake_libcalamares.globalstorage.value.side_effect = lambda k: {
        "rootMountPoint": str(tmp_path),
        "username": None,
    }.get(k)
    mod = _load_module(
        "shedos_configs_main_nouser",
        MODULES_SRC / "shedos_configs/main.py",
    )
    assert mod.run() is None
    fake_libcalamares.utils.warning.assert_called()


def test_configs_seeds_sync_manifest_from_pkg_defaults(
    fake_libcalamares, monkeypatch, tmp_path,
):
    """Files under <target>/usr/share/shedos/<pkg>/defaults/ get sha256 entries
    written to <home>/.local/state/shedos/last-seen/<relpath>.sha256."""
    target = tmp_path / "target"
    user_home = target / "home" / "carol"
    user_home.mkdir(parents=True)
    pkg_defaults = target / "usr/share/shedos/example/defaults/.config/foo"
    pkg_defaults.mkdir(parents=True)
    (pkg_defaults / "settings.toml").write_text("hello=world\n")

    fake_libcalamares.globalstorage.value.side_effect = lambda k: {
        "rootMountPoint": str(target),
        "username": "carol",
    }.get(k)

    mod = _load_module(
        "shedos_configs_main_manifest",
        MODULES_SRC / "shedos_configs/main.py",
    )

    # Stub out the chroot subprocess calls (chown, pacman -Sy) so the
    # test doesn't shell out. We don't care about their effect here.
    import subprocess as _sp

    def fake_subprocess_run(*args, **kw):
        return _sp.CompletedProcess(
            args=args[0] if args else [],
            returncode=0, stdout="", stderr="",
        )

    monkeypatch.setattr(mod.subprocess, "run", fake_subprocess_run)

    assert mod.run() is None
    manifest = (
        user_home / ".local/state/shedos/last-seen/.config/foo/settings.toml.sha256"
    )
    assert manifest.exists(), f"manifest entry not written at {manifest}"
    # Hash matches the file content.
    import hashlib
    expected = hashlib.sha256(b"hello=world\n").hexdigest()
    assert manifest.read_text().strip() == expected
