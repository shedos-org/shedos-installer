"""Shared pytest fixtures for the shedos-installer test suite.

Every Manager class (LuksManager, DiskManager, BtrfsManager) routes
through `shedos_installer.utils.command.run_command`. The
`mock_run_command` fixture below replaces that function with a
MagicMock so tests can assert exact argv without touching real
disks or running real commands.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from shedos_installer.utils.command import CommandResult


def make_result(
    returncode: int = 0,
    stdout: str = "",
    stderr: str = "",
) -> CommandResult:
    """Build a CommandResult with success= derived from returncode."""
    return CommandResult(
        returncode=returncode,
        stdout=stdout,
        stderr=stderr,
        success=(returncode == 0),
    )


@pytest.fixture
def mock_run_command(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Patch run_command in every module that imports it.

    Returns a MagicMock that can be configured per-test:

        mock_run_command.return_value = make_result(stdout="...")
        mock_run_command.side_effect = [make_result(0), make_result(1)]

    Then assert with:

        mock_run_command.assert_called_with([...])
        assert mock_run_command.call_args_list[0].args[0] == [...]
    """
    mock = MagicMock(return_value=make_result(returncode=0))
    # Patch every reachable import site. Each Manager class did
    # `from shedos_installer.utils.command import run_command`, which
    # binds the name into the importing module — patching only the
    # source module wouldn't catch those.
    monkeypatch.setattr("shedos_installer.utils.command.run_command", mock)
    monkeypatch.setattr("shedos_installer.core.luks_manager.run_command", mock)
    monkeypatch.setattr("shedos_installer.core.disk_manager.run_command", mock)
    monkeypatch.setattr("shedos_installer.core.btrfs_manager.run_command", mock)
    # installer.py imports both run_command and run_chroot directly.
    # run_chroot in command.py resolves run_command via module scope,
    # which the first patch above already covers — but installer.py's
    # own binding of run_command is independent and needs its own patch.
    monkeypatch.setattr("shedos_installer.core.installer.run_command", mock)
    monkeypatch.setattr("shedos_installer.core.installer.run_chroot", mock)
    return mock


@pytest.fixture
def tmp_mount(tmp_path: Path) -> Path:
    """Disposable mount root mimicking /mnt for tests that touch the
    target filesystem (e.g. crypttab writer)."""
    mount = tmp_path / "mnt"
    mount.mkdir()
    return mount
