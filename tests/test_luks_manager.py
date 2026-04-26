"""Tests for shedos_installer.core.luks_manager.LuksManager."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from shedos_installer.core.luks_manager import LuksManager
from tests.conftest import make_result


@pytest.fixture
def luks() -> LuksManager:
    return LuksManager(device="/dev/sda2", password="hunter2")


def test_format_luks_invokes_cryptsetup_with_expected_cipher(
    luks: LuksManager, mock_run_command: MagicMock
) -> None:
    assert luks.format_luks() is True
    cmd = mock_run_command.call_args.args[0]
    # Verify the load-bearing flags survive any future formatting
    # tweaks. Argv-token granularity, not whole-string equality.
    assert cmd[0] == "cryptsetup"
    assert cmd[1] == "luksFormat"
    assert "--type" in cmd and cmd[cmd.index("--type") + 1] == "luks2"
    assert "--cipher" in cmd and cmd[cmd.index("--cipher") + 1] == "aes-xts-plain64"
    assert "--key-size" in cmd and cmd[cmd.index("--key-size") + 1] == "512"
    assert "--iter-time" in cmd and cmd[cmd.index("--iter-time") + 1] == "5000"
    assert "--key-file" in cmd and cmd[cmd.index("--key-file") + 1] == "-"
    assert "/dev/sda2" in cmd
    # Password lands on stdin via input=, never in argv.
    assert mock_run_command.call_args.kwargs.get("input") == "hunter2"
    # Belt-and-suspenders: no shell wrapper anywhere in the call.
    assert cmd[0] != "sh"


def test_format_luks_propagates_failure(
    luks: LuksManager, mock_run_command: MagicMock
) -> None:
    mock_run_command.return_value = make_result(returncode=1, stderr="bad header")
    assert luks.format_luks() is False


def test_open_luks_returns_mapper_path_on_success(
    luks: LuksManager, mock_run_command: MagicMock
) -> None:
    assert luks.open_luks() == "/dev/mapper/cryptroot"
    cmd = mock_run_command.call_args.args[0]
    assert cmd[0] == "cryptsetup"
    assert cmd[1] == "open"
    assert "--key-file" in cmd and cmd[cmd.index("--key-file") + 1] == "-"
    assert "/dev/sda2" in cmd
    assert "cryptroot" in cmd
    assert mock_run_command.call_args.kwargs.get("input") == "hunter2"
    assert cmd[0] != "sh"


def test_open_luks_returns_None_on_failure(
    luks: LuksManager, mock_run_command: MagicMock
) -> None:
    mock_run_command.return_value = make_result(returncode=2, stderr="No key")
    assert luks.open_luks() is None


def test_close_luks_invokes_cryptsetup_close(
    luks: LuksManager, mock_run_command: MagicMock
) -> None:
    assert luks.close_luks() is True
    mock_run_command.assert_called_with(["cryptsetup", "close", "cryptroot"])


def test_close_luks_propagates_failure(
    luks: LuksManager, mock_run_command: MagicMock
) -> None:
    mock_run_command.return_value = make_result(returncode=5, stderr="device busy")
    assert luks.close_luks() is False


def test_get_uuid_strips_whitespace(
    luks: LuksManager, mock_run_command: MagicMock
) -> None:
    mock_run_command.return_value = make_result(stdout="abc-123-def\n")
    assert luks.get_uuid() == "abc-123-def"
    mock_run_command.assert_called_with(["cryptsetup", "luksUUID", "/dev/sda2"])


def test_get_uuid_returns_None_on_failure(
    luks: LuksManager, mock_run_command: MagicMock
) -> None:
    mock_run_command.return_value = make_result(returncode=1, stderr="not LUKS")
    assert luks.get_uuid() is None


def test_add_to_crypttab_writes_correct_entry(
    luks: LuksManager, mock_run_command: MagicMock, tmp_mount: Path
) -> None:
    # get_uuid() will hit run_command — give it a value to return
    mock_run_command.return_value = make_result(stdout="abc-123-def")
    (tmp_mount / "etc").mkdir()
    (tmp_mount / "etc" / "crypttab").touch()

    assert luks.add_to_crypttab(str(tmp_mount)) is True

    written = (tmp_mount / "etc" / "crypttab").read_text()
    # Two-space separators (matches the source string exactly).
    assert written == "cryptroot  UUID=abc-123-def  none  luks\n"


def test_add_to_crypttab_short_circuits_on_missing_uuid(
    luks: LuksManager, mock_run_command: MagicMock, tmp_mount: Path
) -> None:
    mock_run_command.return_value = make_result(returncode=1, stderr="not LUKS")
    # crypttab file is never opened — we never get past the UUID check
    assert luks.add_to_crypttab(str(tmp_mount)) is False
    assert not (tmp_mount / "etc" / "crypttab").exists()


def test_password_with_apostrophe_lands_on_stdin_not_argv(
    mock_run_command: MagicMock,
) -> None:
    """A password containing a shell metacharacter must not appear in argv.

    Previously: format_luks() built `sh -c "echo -n '<pw>' | cryptsetup ..."`,
    which would break shell quoting on the apostrophe (and execute arbitrary
    shell on `;` / `$()`). Fix routes the password via subprocess input.
    """
    pwn = LuksManager(device="/dev/sda2", password="ab'cd;rm -rf /")
    pwn.format_luks()
    cmd = mock_run_command.call_args.args[0]
    # No element of argv contains the password substring.
    assert all("ab'cd" not in token for token in cmd)
    # No shell wrapper.
    assert cmd[0] != "sh"
    # Password lands intact on stdin.
    assert mock_run_command.call_args.kwargs.get("input") == "ab'cd;rm -rf /"
