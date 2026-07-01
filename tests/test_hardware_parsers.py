"""Tests for parsing helpers in shedos_installer.utils.hardware.

Focuses on the pure parsers (lspci output → GpuInfo, /proc/cpuinfo →
dict, _format_size). Uses canned-string fixtures so no real hardware
is touched. The high-level get_disks/get_partitions/connect_wifi
functions are deferred — they're thin wrappers around lsblk/iwd that
need integration coverage.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, mock_open, patch

import pytest

from shedos_installer.utils.command import CommandResult
from shedos_installer.utils.hardware import (
    _format_size,
    get_cpu_info,
    get_gpus,
    is_uefi,
)
from tests.conftest import make_result


def test_is_uefi_true_when_efi_dir_exists(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("shedos_installer.utils.hardware.Path.exists", lambda self: True)
    assert is_uefi() is True


def test_is_uefi_false_when_efi_dir_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("shedos_installer.utils.hardware.Path.exists", lambda self: False)
    assert is_uefi() is False


def test_format_size_returns_human_readable_units() -> None:
    assert _format_size(0) == "0.0 B"
    assert _format_size(512) == "512.0 B"
    assert _format_size(2048) == "2.0 KB"
    assert _format_size(5 * 1024 * 1024) == "5.0 MB"
    assert _format_size(8 * 1024 * 1024 * 1024) == "8.0 GB"


def test_get_cpu_info_parses_cpuinfo() -> None:
    sample = (
        "processor\t: 0\n"
        "vendor_id\t: AuthenticAMD\n"
        "model name\t: AMD Ryzen 7 7840U w/ Radeon 780M Graphics\n"
        "cpu cores\t: 8\n"
        "siblings\t: 16\n"
    )
    with patch("builtins.open", mock_open(read_data=sample)):
        info = get_cpu_info()
    assert info["vendor"] == "AuthenticAMD"
    assert info["model"] == "AMD Ryzen 7 7840U w/ Radeon 780M Graphics"
    assert info["cores"] == "8"
    assert info["threads"] == "16"


def test_get_cpu_info_returns_zero_defaults_on_error() -> None:
    with patch("builtins.open", side_effect=OSError("no /proc")):
        info = get_cpu_info()
    assert info == {"vendor": "", "model": "", "cores": "0", "threads": "0"}


def test_get_gpus_parses_intel_iigpu(monkeypatch: pytest.MonkeyPatch) -> None:
    sample = (
        "00:02.0 VGA compatible controller [0300]: "
        "Intel Corporation Raptor Lake-P [Iris Xe Graphics] [8086:a7a0]\n"
    )
    monkeypatch.setattr(
        "shedos_installer.utils.hardware.run_command",
        lambda *a, **kw: make_result(stdout=sample),
    )
    gpus = get_gpus()
    assert len(gpus) == 1
    assert gpus[0].vendor == "Intel"
    assert gpus[0].driver == "i915"
    assert gpus[0].is_nvidia is False


def test_get_gpus_detects_nvidia_rtx_30_series(monkeypatch: pytest.MonkeyPatch) -> None:
    sample = (
        "01:00.0 VGA compatible controller [0300]: "
        "NVIDIA Corporation GA104 [GeForce RTX 3070] [10de:2484]\n"
    )
    monkeypatch.setattr(
        "shedos_installer.utils.hardware.run_command",
        lambda *a, **kw: make_result(stdout=sample),
    )
    gpus = get_gpus()
    assert len(gpus) == 1
    assert gpus[0].vendor == "NVIDIA"
    assert gpus[0].driver == "nvidia"
    assert gpus[0].is_nvidia is True
    assert gpus[0].nvidia_series == "Ampere"


def test_get_gpus_detects_amd_radeon(monkeypatch: pytest.MonkeyPatch) -> None:
    sample = (
        "0a:00.0 VGA compatible controller [0300]: "
        "Advanced Micro Devices, Inc. [AMD/ATI] Navi 32 [Radeon RX 7800 XT] [1002:747e]\n"
    )
    monkeypatch.setattr(
        "shedos_installer.utils.hardware.run_command",
        lambda *a, **kw: make_result(stdout=sample),
    )
    gpus = get_gpus()
    assert len(gpus) == 1
    assert gpus[0].vendor == "AMD"
    assert gpus[0].driver == "amdgpu"


def test_get_gpus_returns_empty_on_lspci_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "shedos_installer.utils.hardware.run_command",
        lambda *a, **kw: make_result(returncode=1, stderr="no lspci"),
    )
    assert get_gpus() == []


def test_get_gpus_handles_multi_gpu_system(monkeypatch: pytest.MonkeyPatch) -> None:
    # Common laptop layout: Intel iGPU + NVIDIA dGPU
    sample = (
        "00:02.0 VGA compatible controller [0300]: "
        "Intel Corporation Raptor Lake-P [Iris Xe Graphics] [8086:a7a0]\n"
        # Muxless Optimus dGPUs enumerate as "3D controller [0302]", not VGA.
        "01:00.0 3D controller [0302]: "
        "NVIDIA Corporation TU117M [GeForce GTX 1650 Mobile] [10de:1f99]\n"
    )
    monkeypatch.setattr(
        "shedos_installer.utils.hardware.run_command",
        lambda *a, **kw: make_result(stdout=sample),
    )
    gpus = get_gpus()
    assert len(gpus) == 2
    assert {g.vendor for g in gpus} == {"Intel", "NVIDIA"}


def test_get_gpus_detects_3d_controller_nvidia(monkeypatch: pytest.MonkeyPatch) -> None:
    # Muxless Optimus: the dGPU is a "3D controller [0302]", never VGA.
    sample = ("01:00.0 3D controller [0302]: NVIDIA Corporation TU117M "
              "[GeForce GTX 1650 Mobile] [10de:1f99]\n")
    monkeypatch.setattr("shedos_installer.utils.hardware.run_command",
                        lambda *a, **kw: make_result(stdout=sample))
    gpus = get_gpus()
    assert len(gpus) == 1
    assert gpus[0].is_nvidia
    assert gpus[0].vendor == "NVIDIA"


def test_get_gpus_detects_display_controller(monkeypatch: pytest.MonkeyPatch) -> None:
    sample = ("07:00.0 Display controller [0380]: NVIDIA Corporation GA107 "
              "[10de:25a2]\n")
    monkeypatch.setattr("shedos_installer.utils.hardware.run_command",
                        lambda *a, **kw: make_result(stdout=sample))
    gpus = get_gpus()
    assert len(gpus) == 1
    assert gpus[0].is_nvidia


def test_get_gpus_ignores_non_gpu_controllers(monkeypatch: pytest.MonkeyPatch) -> None:
    # Only real GPU classes count; other "... controller" lines are not GPUs.
    sample = (
        "00:1f.3 Ethernet controller [0200]: Intel [8086:1234]\n"
        "00:14.0 USB controller [0c03]: Intel [8086:5678]\n"
        "01:00.0 3D controller [0302]: NVIDIA Corporation TU117M "
        "[GeForce GTX 1650 Mobile] [10de:1f99]\n"
    )
    monkeypatch.setattr("shedos_installer.utils.hardware.run_command",
                        lambda *a, **kw: make_result(stdout=sample))
    gpus = get_gpus()
    assert [g.vendor for g in gpus] == ["NVIDIA"]
