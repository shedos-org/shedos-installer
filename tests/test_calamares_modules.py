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
    """pacstrap argv must carry --ignore=… so pacman doesn't auto-roll
    the alphabetical-default virtual provider (jack2 over pipewire-jack,
    etc.), which would conflict with shedos-meta's explicit deps."""
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
    # PACSTRAP_LOG defaults to /var/log/calamares/pacstrap.log; redirect
    # to tmp so we don't need root to write.
    monkeypatch.setattr(mod, "PACSTRAP_LOG", str(tmp_path / "pacstrap.log"))

    assert mod.run() is None
    cmd = captured["cmd"]
    # Sanity: pacstrap, the target root, base set, and --ignore present.
    assert cmd[0] == "pacstrap"
    assert cmd[1] == "-c"
    assert cmd[2] == str(tmp_path)
    assert "base" in cmd
    assert "shedos-meta" in cmd
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
    """On non-zero rc, the user-visible error must include both the
    head and the tail of captured output. Resolver conflicts surface
    at the tail; download/config errors surface at the head."""
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


# ─── shedos_optional_apps ───────────────────────────────────────────


def _is_yay_cmd(cmd):
    return len(cmd) >= 8 and cmd[5] == "bash" and "yay" in cmd[7]


def test_optional_apps_default_install_set(fake_libcalamares, monkeypatch, tmp_path):
    """All four proprietary apps must be passed to yay unconditionally."""
    fake_libcalamares.globalstorage.value.side_effect = lambda key: {
        "rootMountPoint": str(tmp_path),
        "username": "shedrack",
    }.get(key)

    captured: dict[str, list[str]] = {}

    def fake_run(cmd, **_):
        if _is_yay_cmd(cmd):
            captured["yay"] = list(cmd)
        return MagicMock(returncode=0, stdout="", stderr="")

    mod = _load_module(
        "shedos_optional_apps_main",
        MODULES_SRC / "shedos_optional_apps/main.py",
    )
    monkeypatch.setattr(mod.subprocess, "run", fake_run)

    assert mod.run() is None
    cmd = captured["yay"]
    assert cmd[0] == "arch-chroot"
    assert cmd[1] == str(tmp_path)
    assert cmd[2:5] == ["sudo", "-u", "shedrack"]
    assert cmd[5] == "bash"
    assert cmd[6] == "-c"
    yay_cmd = cmd[7]
    for pkg in mod.DEFAULT_INSTALL:
        assert pkg in yay_cmd, f"{pkg} missing from yay invocation"
    assert set(mod.DEFAULT_INSTALL) == {
        "google-chrome",
        "postman-bin",
        "claude-code-bin",
        "jetbrains-toolbox",
    }


def test_optional_apps_no_username_skips(fake_libcalamares, monkeypatch, tmp_path):
    """If the users module hasn't committed a username yet, warn and
    skip rather than running yay with no `-u <user>`."""
    fake_libcalamares.globalstorage.value.side_effect = lambda key: {
        "rootMountPoint": str(tmp_path),
        "username": None,
    }.get(key)

    fake_run = MagicMock()
    mod = _load_module(
        "shedos_optional_apps_main_nouser",
        MODULES_SRC / "shedos_optional_apps/main.py",
    )
    monkeypatch.setattr(mod.subprocess, "run", fake_run)

    assert mod.run() is None
    fake_run.assert_not_called()
    fake_libcalamares.utils.warning.assert_called()


def test_optional_apps_sudo_probe_failure_skips_yay(
    fake_libcalamares, monkeypatch, tmp_path,
):
    """If the user can't sudo without a password (broken NOPASSWD),
    skip yay and warn. Running yay anyway would fail mid-build with a
    less actionable error."""
    fake_libcalamares.globalstorage.value.side_effect = lambda key: {
        "rootMountPoint": str(tmp_path),
        "username": "shedrack",
    }.get(key)

    yay_called = False

    def fake_run(cmd, **_):
        nonlocal yay_called
        if _is_yay_cmd(cmd):
            yay_called = True
            return MagicMock(returncode=0, stdout="", stderr="")
        return MagicMock(returncode=1, stdout="", stderr="sudo: a password is required")

    mod = _load_module(
        "shedos_optional_apps_main_probefail",
        MODULES_SRC / "shedos_optional_apps/main.py",
    )
    monkeypatch.setattr(mod.subprocess, "run", fake_run)

    assert mod.run() is None
    assert not yay_called
    fake_libcalamares.utils.warning.assert_called()


def test_optional_apps_yay_failure_is_nonfatal(
    fake_libcalamares, monkeypatch, tmp_path,
):
    """yay can fail (offline install, AUR HTTP 500, build error). The
    install must complete anyway; the user can retry via shedman."""
    fake_libcalamares.globalstorage.value.side_effect = lambda key: {
        "rootMountPoint": str(tmp_path),
        "username": "shedrack",
    }.get(key)

    def fake_run(cmd, **_):
        if _is_yay_cmd(cmd):
            return MagicMock(returncode=1, stdout="", stderr="some yay error")
        return MagicMock(returncode=0, stdout="", stderr="")

    mod = _load_module(
        "shedos_optional_apps_main_failnowarn",
        MODULES_SRC / "shedos_optional_apps/main.py",
    )
    monkeypatch.setattr(mod.subprocess, "run", fake_run)

    assert mod.run() is None
    fake_libcalamares.utils.warning.assert_called()
