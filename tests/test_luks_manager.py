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
    assert cmd[0:2] == ["sh", "-c"]
    shell = cmd[2]
    # Verify the load-bearing flags survive any future formatting
    # tweaks. Argv-token granularity, not whole-string equality.
    assert "echo -n 'hunter2'" in shell
    assert "cryptsetup luksFormat" in shell
    assert "--type luks2" in shell
    assert "--cipher aes-xts-plain64" in shell
    assert "--key-size 512" in shell
    assert "--iter-time 5000" in shell
    assert "/dev/sda2" in shell


def test_format_luks_propagates_failure(
    luks: LuksManager, mock_run_command: MagicMock
) -> None:
    mock_run_command.return_value = make_result(returncode=1, stderr="bad header")
    assert luks.format_luks() is False


def test_open_luks_returns_mapper_path_on_success(
    luks: LuksManager, mock_run_command: MagicMock
) -> None:
    assert luks.open_luks() == "/dev/mapper/cryptroot"


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


@pytest.mark.xfail(
    reason=(
        "LuksManager.format_luks single-quote-interpolates the password into "
        "an `sh -c` string. A password containing a literal apostrophe breaks "
        "the shell quoting and could leak fragments of the next argv as a "
        "shell command. Test documents the gap; fix to follow in a separate "
        "commit so the security change is reviewable on its own."
    ),
    strict=True,
)
def test_password_with_apostrophe_quoted_safely(
    mock_run_command: MagicMock,
) -> None:
    pwn = LuksManager(device="/dev/sda2", password="ab'cd")
    pwn.format_luks()
    cmd = mock_run_command.call_args.args[0]
    shell = cmd[2]
    # The current impl injects `'ab'cd'` which terminates the string
    # early. A safe impl would either base64-encode + decode in shell
    # or use --key-file /dev/stdin with proper exec quoting.
    assert "ab'cd" not in shell or "'ab'\\''cd'" in shell
