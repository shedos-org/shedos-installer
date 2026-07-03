"""Unit tests for the Calamares custom Python modules.

These modules import `libcalamares`, which only exists inside
Calamares' runtime — we stub it via sys.modules before the
import-under-test fires.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import types
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
MODULES_SRC = REPO_ROOT / "installer/calamares/modules-src"


@pytest.fixture
def fake_libcalamares(monkeypatch):
    fake: Any = types.ModuleType("libcalamares")
    fake.globalstorage = MagicMock()
    fake.globalstorage.value.return_value = None
    fake_utils: Any = types.ModuleType("libcalamares.utils")
    fake_utils.debug = MagicMock()
    fake_utils.warning = MagicMock()
    # shedos_gitconfig imports these names directly from libcalamares.utils
    # (`from libcalamares.utils import check_target_env_call, target_env_call`),
    # so the bindings have to exist before module load. target_env_call
    # returns a shell exit code; default it to 0 (success).
    fake_utils.check_target_env_call = MagicMock()
    fake_utils.target_env_call = MagicMock(return_value=0)
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
                        lambda _: [str(p) for p in
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
    monkeypatch.setattr(mod.glob, "glob", lambda _: [])

    result = mod.run()
    assert result is not None
    title, _ = result
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
    fake_libcalamares.globalstorage.value.side_effect = lambda _: None
    mod = _load_module(
        "shedos_gitconfig_main_nouser",
        MODULES_SRC / "shedos_gitconfig/main.py",
    )
    assert mod.run() is None
    fake_libcalamares.utils.warning.assert_called()


# ─── shedos_recovery_stash ──────────────────────────────────────────


def test_recovery_stash_writes_key_for_the_tour(fake_libcalamares, tmp_path):
    """The install-time key lands at the target stash, wheel-readable (0660) in a
    wheel-writable (0770) dir, so the first-login tour can read it, shred it, and
    unlink it."""
    target = tmp_path / "target"
    target.mkdir()
    fake_libcalamares.globalstorage.value.side_effect = lambda k: {
        "shedos_recovery_key": "PRNDW-EWGMR-AAAAA",
        "rootMountPoint": str(target),
    }.get(k)

    mod = _load_module(
        "shedos_recovery_stash_main",
        MODULES_SRC / "shedos_recovery_stash/main.py",
    )
    assert mod.run() is None

    stash = target / "var/lib/shedos/encrypt/recovery-key"
    assert stash.read_text() == "PRNDW-EWGMR-AAAAA\n"
    assert (stash.stat().st_mode & 0o777) == 0o660
    assert (stash.parent.stat().st_mode & 0o777) == 0o770
    # chgrp (dir + stash) runs in the target chroot (mocked here), so the group is
    # not asserted — only that the module sets it on both.
    fake_libcalamares.utils.target_env_call.assert_called_once_with(
        ["chgrp", "wheel", "/var/lib/shedos/encrypt",
         "/var/lib/shedos/encrypt/recovery-key"]
    )


def test_recovery_stash_noop_without_key(fake_libcalamares, tmp_path):
    """Encryption opted out → no key in globalstorage → return None, write nothing."""
    target = tmp_path / "target"
    target.mkdir()
    fake_libcalamares.globalstorage.value.side_effect = lambda k: {
        "rootMountPoint": str(target),
    }.get(k)
    mod = _load_module(
        "shedos_recovery_stash_main_noop",
        MODULES_SRC / "shedos_recovery_stash/main.py",
    )
    assert mod.run() is None
    assert not (target / "var/lib/shedos/encrypt/recovery-key").exists()


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


def _nv_gpu():
    from shedos_installer.utils.hardware import GpuInfo
    return GpuInfo(
        vendor="NVIDIA", model="RTX", pci_id="10de:2860", driver="nvidia",
        is_nvidia=True, nvidia_series="Turing",
    )


def test_nvidia_skipped_when_no_supported_gpu(fake_libcalamares, monkeypatch):
    """No NVIDIA GPU the open modules can drive → run() exits early with None.
    The gate is the GPU itself now, not a globalstorage key set by another
    module that runs later."""
    mod = _load_module(
        "shedos_nvidia_main_skip", MODULES_SRC / "shedos_nvidia/main.py",
    )
    monkeypatch.setattr(mod, "get_gpus", lambda: [])
    assert mod.run() is None
    # Should log a debug saying it was skipped, not invoke any commands.
    fake_libcalamares.utils.debug.assert_called()


def test_nvidia_uses_fallback_list_when_package_file_missing(
    fake_libcalamares, monkeypatch, tmp_path,
):
    """nvidia.txt missing → use the hardcoded fallback list and warn."""
    fake_libcalamares.globalstorage.value.side_effect = lambda k: {
        "rootMountPoint": str(tmp_path),
    }.get(k)

    mod = _load_module(
        "shedos_nvidia_main_fallback",
        MODULES_SRC / "shedos_nvidia/main.py",
    )
    monkeypatch.setattr(mod, "PACKAGE_DIR", tmp_path / "definitely-missing")
    monkeypatch.setattr(mod, "get_gpus", lambda: [_nv_gpu()])

    captured = []

    def fake_run_chroot(cmd, **_kw):
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


def test_nvidia_enables_suspend_services_when_supported(
    fake_libcalamares, monkeypatch, tmp_path,
):
    """A supported NVIDIA GPU → the suspend/hibernate/resume services get
    enabled. They were dead before because the install gate never fired."""
    fake_libcalamares.globalstorage.value.side_effect = lambda k: {
        "rootMountPoint": str(tmp_path),
    }.get(k)

    mod = _load_module(
        "shedos_nvidia_main_services",
        MODULES_SRC / "shedos_nvidia/main.py",
    )
    monkeypatch.setattr(mod, "PACKAGE_DIR", tmp_path / "definitely-missing")
    monkeypatch.setattr(mod, "get_gpus", lambda: [_nv_gpu()])

    enabled = []

    def fake_run_chroot(cmd, **_kw):
        from shedos_installer.utils.command import CommandResult
        if cmd[:2] == ["systemctl", "enable"]:
            enabled.append(cmd[2])
        return CommandResult(returncode=0, stdout="", stderr="", success=True)

    monkeypatch.setattr(mod, "run_chroot", fake_run_chroot)
    assert mod.run() is None
    assert enabled == [
        "nvidia-suspend.service",
        "nvidia-hibernate.service",
        "nvidia-resume.service",
    ]


def test_nvidia_writes_hybrid_gpu_env(fake_libcalamares, monkeypatch, tmp_path):
    """A hybrid Optimus box gets /etc/uwsm/env with an Intel-primary
    AQ_DRM_DEVICES and no global nvidia block (which would break iGPU VAAPI)."""
    from shedos_installer.utils.hardware import GpuInfo
    fake_libcalamares.globalstorage.value.side_effect = lambda k: {
        "rootMountPoint": str(tmp_path),
    }.get(k)

    mod = _load_module(
        "shedos_nvidia_main_gpuenv", MODULES_SRC / "shedos_nvidia/main.py",
    )
    igpu = GpuInfo(vendor="Intel", model="UHD", pci_id="8086:9bc4",
                   driver="i915", is_nvidia=False, nvidia_series=None,
                   pci_addr="0000:00:02.0")
    dgpu = GpuInfo(vendor="NVIDIA", model="RTX", pci_id="10de:2860",
                   driver="nvidia", is_nvidia=True, nvidia_series="Turing",
                   pci_addr="0000:01:00.0")
    monkeypatch.setattr(mod, "get_gpus", lambda: [igpu, dgpu])
    monkeypatch.setattr(mod, "PACKAGE_DIR", tmp_path / "missing")

    def fake_run_chroot(cmd, **_kw):
        from shedos_installer.utils.command import CommandResult
        return CommandResult(returncode=0, stdout="", stderr="", success=True)

    monkeypatch.setattr(mod, "run_chroot", fake_run_chroot)
    assert mod.run() is None

    env = (tmp_path / "etc/uwsm/env").read_text()
    assert ("AQ_DRM_DEVICES=/dev/dri/by-path/pci-0000:00:02.0-card:"
            "/dev/dri/by-path/pci-0000:01:00.0-card") in env
    assert "GBM_BACKEND" not in env
    assert "prime-run" in env


# ─── shedos_finalize ────────────────────────────────────────────────


def test_finalize_returns_error_when_rootmount_missing(fake_libcalamares):
    fake_libcalamares.globalstorage.value.side_effect = lambda _: None
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
    fake_libcalamares.globalstorage.value.side_effect = lambda _: None
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

    def fake_subprocess_run(*args, **_kw):
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


# ─── I6/I9/I4 regressions ───────────────────────────────────────────


def test_limine_luks_uuid_taken_from_root_partition_only(fake_libcalamares):
    mod = _load_module(
        "shedos_limine_main_scan",
        MODULES_SRC / "shedos_limine/main.py",
    )
    root_uuid, root_fs, luks_uuid, disk, swap_luks = mod._scan_partitions([
        {"mountPoint": "/", "uuid": "root-uuid", "fs": "btrfs",
         "device": "/dev/nvme0n1p2",
         "luksMapperName": "luks-root", "luksUuid": "root-luks"},
        {"mountPoint": "/home", "uuid": "home-uuid", "fs": "btrfs",
         "device": "/dev/nvme0n1p3",
         "luksMapperName": "luks-home", "luksUuid": "home-luks"},
        {"mountPoint": "", "uuid": "swap-uuid", "fs": "linuxswap",
         "device": "/dev/nvme0n1p4",
         "luksMapperName": "swap", "luksUuid": "swap-luks"},
    ])
    assert root_uuid == "root-uuid"
    assert root_fs == "btrfs"
    assert luks_uuid == "root-luks"   # root only, never /home or swap
    assert disk == "/dev/nvme0n1"
    assert swap_luks == ("swap-luks", "swap")   # captured for the resume unlock


def test_limine_rejects_non_btrfs_root(fake_libcalamares, monkeypatch):
    fake_libcalamares.globalstorage.value.side_effect = lambda k: {
        "rootMountPoint": "/tmp/anywhere",
        "partitions": [
            {"mountPoint": "/", "uuid": "root-uuid", "fs": "ext4",
             "device": "/dev/sda2"},
        ],
    }.get(k)
    mod = _load_module(
        "shedos_limine_main_ext4",
        MODULES_SRC / "shedos_limine/main.py",
    )
    monkeypatch.setattr(mod, "is_uefi", lambda: False)
    result = mod.run()
    assert result is not None
    title, detail = result
    assert "filesystem" in title.lower()
    assert "btrfs" in detail


# ─── shedos_luks_escrow ─────────────────────────────────────────────


def _load_escrow(name="shedos_luks_escrow_main"):
    return _load_module(name, MODULES_SRC / "shedos_luks_escrow/main.py")


def test_luks_escrow_enrolls_recovery_key_on_every_container(
        fake_libcalamares, monkeypatch, tmp_path):
    mod = _load_escrow()
    # Calamares stores the partition LUKS passphrase in plaintext (only the
    # user-account password is obscured); the escrow uses it as-is to authorize.
    pw = "hunter2"
    fake_libcalamares.globalstorage.value.side_effect = lambda k: {
        "shedos_recovery_key": "ABCDE-FGHIJ-KLMNO-PQRST-UVWXY",
        "partitions": [
            {"mountPoint": "/", "device": "/dev/vda2",
             "luksMapperName": "luks-root", "luksPassphrase": pw},
            {"mountPoint": "", "device": "/dev/vda3",
             "luksMapperName": "luks-swap", "luksPassphrase": pw},
        ],
    }.get(k)
    # Keep the secret keyfile out of /run (not writable as the test user).
    # Capture the real mkstemp first — mod.tempfile is the same module
    # object we patch, so a naive lambda would recurse into itself.
    real_mkstemp = tempfile.mkstemp
    monkeypatch.setattr(mod.tempfile, "mkstemp",
                        lambda **kw: real_mkstemp(dir=str(tmp_path)))
    calls = []
    # Track slots per device so each luksAddKey makes a new slot appear; the
    # module's before/after diff then finds exactly the slot it just added.
    state: dict = {}

    def fake_run(argv, input=None, **kwargs):
        calls.append({"argv": argv, "input": input})
        if "luksDump" in argv:
            st = state.setdefault(argv[-1], {"slots": {"0"}, "n": 1})
            body = json.dumps({"keyslots": {s: {} for s in sorted(st["slots"])}})
            return types.SimpleNamespace(returncode=0, stderr=b"", stdout=body)
        if "luksAddKey" in argv:
            st = state.setdefault(argv[-2], {"slots": {"0"}, "n": 1})
            st["slots"].add(str(st["n"]))
            st["n"] += 1
        return types.SimpleNamespace(returncode=0, stderr=b"", stdout="")

    monkeypatch.setattr(mod.subprocess, "run", fake_run)
    assert mod.run() is None

    adds = [c for c in calls if "luksAddKey" in c["argv"]]
    imports = [c for c in calls if "token" in c["argv"] and "import" in c["argv"]]
    # Enrolled on the root AND the swap container — a recovery unlock has to
    # open every device the initramfs prompts for at boot, not just root.
    assert {c["argv"][-2] for c in adds} == {"/dev/vda2", "/dev/vda3"}
    # Four spellings (upper/lower x dashed/undashed) per container.
    assert len(adds) == 8
    for c in adds:
        assert c["argv"][:3] == ["cryptsetup", "luksAddKey", "--key-file=-"]
        # The passphrase is fed plaintext on stdin, never on argv.
        assert c["input"] == pw.encode()
        assert pw not in " ".join(c["argv"])
    # Every newly-added slot gets a shedos-recovery LUKS2 token, imported from a
    # file (cryptsetup token import won't read a pipe), on each container.
    assert len(imports) == 8
    for c in imports:
        assert any(a.startswith("--json-file=") for a in c["argv"])
        assert c["argv"][-1] in ("/dev/vda2", "/dev/vda3")


def test_luks_escrow_noop_when_encryption_opted_out(fake_libcalamares, monkeypatch):
    mod = _load_escrow("shedos_luks_escrow_noop")
    fake_libcalamares.globalstorage.value.side_effect = lambda k: None
    called = {"n": 0}
    monkeypatch.setattr(mod.subprocess, "run",
                        lambda *a, **k: called.__setitem__("n", called["n"] + 1))
    assert mod.run() is None
    assert called["n"] == 0
