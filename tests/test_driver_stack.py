"""The NVIDIA package list comes from shedos-system's file, not from a
second copy of the names kept here."""

from __future__ import annotations

from pathlib import Path

import pytest

from shedos_installer.driver_stack import driver_stack


def _stack_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, text: str) -> Path:
    path = tmp_path / "nvidia-driver-stack"
    path.write_text(text)
    monkeypatch.setenv("SHEDOS_NVIDIA_STACK_FILE", str(path))
    return path


def test_reads_the_packages_in_file_order(tmp_path, monkeypatch):
    _stack_file(tmp_path, monkeypatch, "nvidia-open-dkms\nnvidia-utils\negl-gbm\n")
    assert driver_stack() == ["nvidia-open-dkms", "nvidia-utils", "egl-gbm"]


def test_comments_and_blank_lines_are_not_packages(tmp_path, monkeypatch):
    """The shipped file opens with five comment lines explaining what it is
    for, and pacman would take any of them as a package name."""
    _stack_file(
        tmp_path,
        monkeypatch,
        "# what this file is\n\n  # indented\nnvidia-utils\n\n  egl-gbm  \n",
    )
    assert driver_stack() == ["nvidia-utils", "egl-gbm"]


def test_a_missing_file_is_an_error(tmp_path, monkeypatch):
    monkeypatch.setenv("SHEDOS_NVIDIA_STACK_FILE", str(tmp_path / "absent"))
    with pytest.raises(OSError):
        driver_stack()


def test_a_file_naming_nothing_is_an_error(tmp_path, monkeypatch):
    """An empty answer would install nothing on an NVIDIA box and strip
    nothing from a machine without one, and say so nowhere."""
    _stack_file(tmp_path, monkeypatch, "# only a comment\n\n")
    with pytest.raises(OSError):
        driver_stack()
