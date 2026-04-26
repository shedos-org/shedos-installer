"""Command execution utilities for ShedOS installer."""

import logging
import subprocess
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class CommandResult:
    """Result of a command execution."""
    returncode: int
    stdout: str
    stderr: str
    success: bool

    @property
    def output(self) -> str:
        """Return stdout, or stderr if stdout is empty."""
        return self.stdout.strip() if self.stdout.strip() else self.stderr.strip()


def run_command(
    cmd: list[str],
    check: bool = False,
    capture_output: bool = True,
    timeout: Optional[int] = None,
    chroot: Optional[str] = None,
    env: Optional[dict[str, str]] = None,
    input: Optional[str] = None,
) -> CommandResult:
    """Run a command and return the result.

    `input`, when set, is forwarded to subprocess.run as text passed
    on stdin — the right way to feed secrets (LUKS passwords, chpasswd
    user:pass pairs) to commands that read from stdin without piping
    them through a shell where they could be word-split or injection-
    interpreted.
    """
    if chroot:
        cmd = ["arch-chroot", chroot] + cmd

    cmd_str = " ".join(cmd)
    logger.debug(f"Running command: {cmd_str}")

    try:
        result = subprocess.run(
            cmd,
            input=input,
            capture_output=capture_output,
            text=True,
            timeout=timeout,
            env=env,
        )
        cmd_result = CommandResult(
            returncode=result.returncode,
            stdout=result.stdout if capture_output else "",
            stderr=result.stderr if capture_output else "",
            success=result.returncode == 0,
        )
        if cmd_result.success:
            logger.debug(f"Command succeeded: {cmd_str}")
        else:
            logger.warning(f"Command failed ({result.returncode}): {cmd_str}")
            if cmd_result.stderr:
                logger.warning(f"stderr: {cmd_result.stderr}")

        if check and not cmd_result.success:
            raise subprocess.CalledProcessError(
                result.returncode, cmd, result.stdout, result.stderr
            )

        return cmd_result
    except subprocess.TimeoutExpired as e:
        logger.error(f"Command timed out: {cmd_str}")
        return CommandResult(
            returncode=-1,
            stdout="",
            stderr=f"Command timed out after {timeout} seconds",
            success=False,
        )
    except Exception as e:
        logger.error(f"Command error: {cmd_str} - {e}")
        return CommandResult(
            returncode=-1,
            stdout="",
            stderr=str(e),
            success=False,
        )


def run_chroot(
    cmd: list[str],
    mount_point: str = "/mnt",
    check: bool = False,
    timeout: Optional[int] = None,
) -> CommandResult:
    """Run a command in arch-chroot."""
    return run_command(cmd, check=check, timeout=timeout, chroot=mount_point)
