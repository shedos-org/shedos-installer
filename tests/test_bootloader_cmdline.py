"""LimineInstaller._build_cmdline — LUKS + encrypted-swap-resume wiring."""
from shedos_installer.core.bootloader import LimineInstaller


def _inst(tmp_path, **kw):
    (tmp_path / "etc").mkdir(exist_ok=True)
    return LimineInstaller(mount_point=str(tmp_path), root_uuid="ROOT-FS", **kw)


def test_encrypted_swap_gets_rd_luks_and_mapper_resume(tmp_path):
    # The swap container is unlocked by its own rd.luks.name, and resume
    # points at the decrypted mapper (encrypted-swap fstab is /dev/mapper/*,
    # never UUID=, so the fstab-UUID path can't supply resume here).
    inst = _inst(
        tmp_path,
        luks_uuid="ROOTLUKS",
        swap_luks_uuid="SWAPLUKS",
        swap_luks_mapper="swap",
    )
    cmd = inst._build_cmdline()
    assert "rd.luks.name=ROOTLUKS=luks-ROOTLUKS" in cmd
    assert "rd.luks.name=SWAPLUKS=swap" in cmd
    assert "resume=/dev/mapper/swap" in cmd
    assert "root=/dev/mapper/luks-ROOTLUKS" in cmd


def test_unencrypted_uses_root_uuid_and_no_rd_luks(tmp_path):
    inst = _inst(tmp_path)  # no LUKS at all
    cmd = inst._build_cmdline()
    assert "rd.luks.name" not in cmd
    assert "root=UUID=ROOT-FS" in cmd


def test_encrypted_root_unencrypted_swap_falls_back_to_fstab_uuid(tmp_path):
    # No swap LUKS, but a plain-UUID swap line in fstab → resume=UUID= still works.
    (tmp_path / "etc").mkdir(exist_ok=True)
    (tmp_path / "etc" / "fstab").write_text("UUID=PLAINSWAP none swap defaults 0 0\n")
    inst = _inst(tmp_path, luks_uuid="ROOTLUKS")
    cmd = inst._build_cmdline()
    assert "rd.luks.name=ROOTLUKS=luks-ROOTLUKS" in cmd
    assert "resume=UUID=PLAINSWAP" in cmd
    assert "/dev/mapper/swap" not in cmd


def test_nvidia_modeset_stays_on_cmdline(tmp_path):
    # nvidia is no longer in MODULES=, so the cmdline is now the only thing
    # turning on nvidia_drm modeset — it applies whenever the module loads.
    assert "nvidia_drm.modeset=1" in _inst(tmp_path, nvidia=True)._build_cmdline()
    assert "nvidia_drm.modeset=1" not in _inst(tmp_path, nvidia=False)._build_cmdline()
