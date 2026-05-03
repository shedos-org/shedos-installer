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
                          ("6.19.13-shedos", "shedos-kernel")]:
        d = live_modules / kver
        d.mkdir(parents=True)
        (d / "pkgbase").write_text(pkgbase + "\n")
        (d / "vmlinuz").write_bytes(b"\x7fELFvmlinuz")

    live_boot = tmp_path / "bootmnt"
    live_boot.mkdir()
    (live_boot / "initramfs-shedos-kernel.img").write_bytes(b"initramfs1")
    (live_boot / "initramfs-shedos-kernel-fallback.img").write_bytes(b"initramfs2")

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
    assert (boot / "vmlinuz-shedos-kernel").read_bytes().startswith(b"\x7fELF")
    assert (boot / "initramfs-shedos-kernel.img").read_bytes() == b"initramfs1"
    assert (boot / "initramfs-shedos-kernel-fallback.img").read_bytes() == b"initramfs2"


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
