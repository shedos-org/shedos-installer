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
    """Stub libcalamares with the surface each module touches:
    globalstorage.value() and utils.{debug,warning}."""
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


# ─── shedos_pacstrap ────────────────────────────────────────────────


def test_shedos_pacstrap_argv_includes_ignore(fake_libcalamares, monkeypatch, tmp_path):
    """pacstrap argv must carry --ignore= so pacman doesn't auto-roll the
    alphabetical-default virtual provider (jack2 vs pipewire-jack)."""
    fake_libcalamares.globalstorage.value.side_effect = lambda key: {
        "rootMountPoint": str(tmp_path),
        "shedos_install_nvidia": False,
    }.get(key)

    captured: dict[str, list[str]] = {}

    def fake_stream(cmd, log_path):
        captured["cmd"] = list(cmd)
        Path(log_path).parent.mkdir(parents=True, exist_ok=True)
        Path(log_path).write_text("ok\n")
        return 0, [], []

    mod = _load_module(
        "shedos_pacstrap_main",
        MODULES_SRC / "shedos_pacstrap/main.py",
    )
    monkeypatch.setattr(mod, "_stream_pacstrap", fake_stream)
    monkeypatch.setattr(mod, "PACSTRAP_LOG", str(tmp_path / "pacstrap.log"))

    assert mod.run() is None
    cmd = captured["cmd"]
    assert cmd[0] == "pacstrap"
    assert cmd[1] == "-c"
    assert cmd[2] == str(tmp_path)
    assert "base" in cmd
    assert "shedos-meta" in cmd
    assert "--needed" in cmd
    ignore_args = [a for a in cmd if a.startswith("--ignore=")]
    assert len(ignore_args) == 1, cmd
    ignored = ignore_args[0].split("=", 1)[1].split(",")
    for must_have in ("jack2", "iptables-legacy", "booster", "dracut",
                      "pipewire-media-session"):
        assert must_have in ignored, f"{must_have!r} missing from --ignore"


def test_shedos_pacstrap_nvidia_extends_base(fake_libcalamares, monkeypatch, tmp_path):
    """When shedos_install_nvidia is true, the NVIDIA package set must
    extend (not replace) BASE_PACKAGES."""
    fake_libcalamares.globalstorage.value.side_effect = lambda key: {
        "rootMountPoint": str(tmp_path),
        "shedos_install_nvidia": True,
    }.get(key)

    captured: dict[str, list[str]] = {}

    def fake_stream(cmd, log_path):
        captured["cmd"] = list(cmd)
        Path(log_path).parent.mkdir(parents=True, exist_ok=True)
        Path(log_path).write_text("ok\n")
        return 0, [], []

    mod = _load_module(
        "shedos_pacstrap_main_nvidia",
        MODULES_SRC / "shedos_pacstrap/main.py",
    )
    monkeypatch.setattr(mod, "_stream_pacstrap", fake_stream)
    monkeypatch.setattr(mod, "PACSTRAP_LOG", str(tmp_path / "pacstrap.log"))

    assert mod.run() is None
    cmd = captured["cmd"]
    for pkg in ("base", "base-devel", "shedos-keyring", "shedos-meta",
                "nvidia-open-dkms", "nvidia-utils"):
        assert pkg in cmd, f"{pkg} missing from pacstrap argv"


def test_shedos_pacstrap_failure_returns_head_and_tail(
    fake_libcalamares, monkeypatch, tmp_path,
):
    """On non-zero rc, the error must include both head and tail of output:
    resolver conflicts surface at the tail, download errors at the head."""
    fake_libcalamares.globalstorage.value.side_effect = lambda key: {
        "rootMountPoint": str(tmp_path),
        "shedos_install_nvidia": False,
    }.get(key)

    def fake_stream(cmd, log_path):
        Path(log_path).parent.mkdir(parents=True, exist_ok=True)
        Path(log_path).write_text("fail\n")
        return 1, ["early-line-1", "early-line-2"], ["late-line-1", "late-line-2"]

    mod = _load_module(
        "shedos_pacstrap_main_fail",
        MODULES_SRC / "shedos_pacstrap/main.py",
    )
    monkeypatch.setattr(mod, "_stream_pacstrap", fake_stream)
    monkeypatch.setattr(mod, "PACSTRAP_LOG", str(tmp_path / "pacstrap.log"))

    result = mod.run()
    assert result is not None
    title, body = result
    assert "rc=1" in title
    assert "early-line-1" in body
    assert "late-line-2" in body


# ─── shedos_local_apps ──────────────────────────────────────────────


def _make_pkg(dirpath: Path, name: str) -> Path:
    dirpath.mkdir(parents=True, exist_ok=True)
    f = dirpath / f"{name}-1.0-1-x86_64.pkg.tar.zst"
    f.write_bytes(b"fake-zst")
    return f


def test_local_apps_pacman_U_uses_in_target_paths(
    fake_libcalamares, monkeypatch, tmp_path,
):
    """Bundled .pkg.tar.zst must be staged into the target's pacman cache
    and pacman -U'd from the in-target path: the live ISO mount isn't
    visible to processes running under arch-chroot."""
    aur_dir = tmp_path / "shedos-payload" / "aur"
    for name in ("google-chrome", "postman-bin",
                 "claude-code-bin", "jetbrains-toolbox"):
        _make_pkg(aur_dir, name)

    target_root = tmp_path / "target"
    fake_libcalamares.globalstorage.value.side_effect = lambda key: {
        "rootMountPoint": str(target_root),
    }.get(key)

    captured: dict[str, list[str]] = {}

    def fake_run(cmd, **_):
        captured["cmd"] = list(cmd)
        return MagicMock(returncode=0, stdout="", stderr="")

    mod = _load_module(
        "shedos_local_apps_main",
        MODULES_SRC / "shedos_local_apps/main.py",
    )
    monkeypatch.setattr(mod, "HOST_AUR_DIR", str(aur_dir))
    monkeypatch.setattr(mod.subprocess, "run", fake_run)

    assert mod.run() is None
    cmd = captured["cmd"]
    assert cmd[0] == "arch-chroot"
    assert cmd[1] == str(target_root)
    assert cmd[2] == "pacman"
    assert cmd[3] == "-U"
    assert "--noconfirm" in cmd
    assert "--needed" in cmd
    pkg_args = [a for a in cmd if a.startswith("/var/cache/pacman/pkg/")]
    assert len(pkg_args) == 4, cmd
    for pkg in ("google-chrome", "postman-bin",
                "claude-code-bin", "jetbrains-toolbox"):
        assert any(pkg in a for a in pkg_args), f"{pkg} missing from argv"
    cache = target_root / "var/cache/pacman/pkg"
    assert cache.is_dir()
    staged = sorted(p.name for p in cache.glob("*.pkg.tar.zst"))
    assert len(staged) == 4


def test_local_apps_missing_bundle_dir_is_nonfatal(
    fake_libcalamares, monkeypatch, tmp_path,
):
    """Missing /shedos-payload/aur/ must warn and return None so the
    rest of the install completes."""
    aur_dir = tmp_path / "missing-aur"  # never created
    target_root = tmp_path / "target"
    fake_libcalamares.globalstorage.value.side_effect = lambda key: {
        "rootMountPoint": str(target_root),
    }.get(key)

    fake_run = MagicMock()
    mod = _load_module(
        "shedos_local_apps_main_nopkgs",
        MODULES_SRC / "shedos_local_apps/main.py",
    )
    monkeypatch.setattr(mod, "HOST_AUR_DIR", str(aur_dir))
    monkeypatch.setattr(mod.subprocess, "run", fake_run)

    assert mod.run() is None
    fake_run.assert_not_called()
    fake_libcalamares.utils.warning.assert_called()


def test_local_apps_pacman_U_failure_is_nonfatal(
    fake_libcalamares, monkeypatch, tmp_path,
):
    """pacman -U failures (sig mismatch, missing dep) must not abort
    Calamares — bootloader install and finalize still need to run."""
    aur_dir = tmp_path / "shedos-payload" / "aur"
    _make_pkg(aur_dir, "google-chrome")

    target_root = tmp_path / "target"
    fake_libcalamares.globalstorage.value.side_effect = lambda key: {
        "rootMountPoint": str(target_root),
    }.get(key)

    def fake_run(cmd, **_):
        return MagicMock(returncode=1, stdout="", stderr="signature is unknown trust")

    mod = _load_module(
        "shedos_local_apps_main_pacfail",
        MODULES_SRC / "shedos_local_apps/main.py",
    )
    monkeypatch.setattr(mod, "HOST_AUR_DIR", str(aur_dir))
    monkeypatch.setattr(mod.subprocess, "run", fake_run)

    assert mod.run() is None
    fake_libcalamares.utils.warning.assert_called()
