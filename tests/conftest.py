"""Shared pytest fixtures."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from shedos_installer.utils.command import CommandResult


def make_result(
    returncode: int = 0,
    stdout: str = "",
    stderr: str = "",
) -> CommandResult:
    return CommandResult(
        returncode=returncode,
        stdout=stdout,
        stderr=stderr,
        success=(returncode == 0),
    )


@pytest.fixture
def mock_run_command(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Patch run_command at every live import site.

    Each consumer does `from … import run_command`, which binds the
    name into the importing module — patching only the source
    wouldn't catch those.
    """
    mock = MagicMock(return_value=make_result(returncode=0))
    monkeypatch.setattr("shedos_installer.utils.command.run_command", mock)
    monkeypatch.setattr("shedos_installer.utils.hardware.run_command", mock)
    monkeypatch.setattr("shedos_installer.core.bootloader.run_command", mock)
    monkeypatch.setattr("shedos_installer.core.bootloader.run_chroot", mock)
    return mock


@pytest.fixture
def tmp_mount(tmp_path: Path) -> Path:
    """Disposable /mnt-style root for tests that touch the target FS."""
    mount = tmp_path / "mnt"
    mount.mkdir()
    return mount
