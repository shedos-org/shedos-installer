"""Tests for shell-injection-resistant paths in the orchestrator.

The full Installer is integration-style code (725 lines composing
disk / luks / btrfs / bootloader managers). These tests cover the
specific paths that previously interpolated user input into shell
strings:

- create_user feeds chpasswd via stdin, never via `sh -c "echo ..."`
- _install_aur_packages shlex-quotes each package name into the
  yay -S invocation

Both paths are reachable via direct method calls with a mocked
run_command.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from shedos_installer.config import UserConfig
from shedos_installer.core.installer import Installer


@pytest.fixture
def installer(tmp_path: Path) -> Installer:
    """Minimal installer instance — only the fields the under-test
    methods read are populated. The full config object isn't needed."""
    inst = Installer.__new__(Installer)
    inst.mount_point = tmp_path / "mnt"
    inst.mount_point.mkdir()
    inst.config = SimpleNamespace(user=None)
    return inst


def _user(password: str, username: str = "tester") -> UserConfig:
    return UserConfig(username=username, password=password, full_name="Test User")


def test_create_user_password_via_stdin_not_argv(
    installer: Installer, mock_run_command: MagicMock
) -> None:
    installer.config.user = _user("hunter2")
    assert installer.create_user() is True

    # create_user makes two run_command calls: useradd (via run_chroot)
    # then chpasswd. The chpasswd call is the one that previously
    # injected via sh -c.
    chpasswd_call = next(
        c for c in mock_run_command.call_args_list
        if "chpasswd" in c.args[0]
    )
    cmd = chpasswd_call.args[0]
    assert cmd[0] == "arch-chroot"
    assert cmd[-1] == "chpasswd"
    assert cmd[0] != "sh"
    # Password lands on stdin as `user:pass\n`, never in argv.
    assert chpasswd_call.kwargs.get("input") == "tester:hunter2\n"


def test_create_user_password_with_shell_metacharacters(
    installer: Installer, mock_run_command: MagicMock
) -> None:
    """Apostrophe in password used to break the `echo '...' | chpasswd`
    quoting and could leak adjacent argv as shell. Now safe."""
    installer.config.user = _user("ab'cd;rm -rf /")
    assert installer.create_user() is True

    chpasswd_call = next(
        c for c in mock_run_command.call_args_list
        if "chpasswd" in c.args[0]
    )
    cmd = chpasswd_call.args[0]
    # No element of argv contains the password substring.
    assert all("ab'cd" not in token for token in cmd)
    # No shell wrapper.
    assert cmd[0] != "sh"
    # Password lands intact on stdin.
    assert chpasswd_call.kwargs.get("input") == "tester:ab'cd;rm -rf /\n"


def test_install_aur_packages_quotes_each_package(
    installer: Installer, mock_run_command: MagicMock
) -> None:
    """yay -S goes through `su -c <single shell command>` which can't
    avoid the shell. Defense in depth: each package name is shlex-
    quoted so a list entry containing whitespace or shell metacharacters
    can't break out of the yay invocation."""
    installer.config.user = _user("pw")
    # Note the second package contains a space — shlex.quote should
    # wrap it in single quotes.
    assert installer._install_aur_packages(["foo", "bar baz"]) is True

    cmd = mock_run_command.call_args.args[0]
    # The shell command is the last element of the argv (after `su - <user> -c`).
    shell_cmd = cmd[-1]
    assert "yay -S --noconfirm --needed" in shell_cmd
    # shlex.quote emits 'bar baz' (with single quotes) for an entry
    # containing whitespace; raw substring would be `bar baz` without quoting.
    assert "'bar baz'" in shell_cmd
    # Plain `foo` is shlex-quoted as `foo` (no quotes needed).
    assert " foo " in shell_cmd or shell_cmd.endswith(" foo")


def test_install_aur_packages_short_circuits_on_empty_list(
    installer: Installer, mock_run_command: MagicMock
) -> None:
    installer.config.user = _user("pw")
    assert installer._install_aur_packages([]) is True
    mock_run_command.assert_not_called()
