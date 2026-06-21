"""UKI wiring on UEFI installs — cmdline baked before mkinitcpio, UKIs placed
and verified before the menu renders, recovery + containers recorded."""

from shedos_installer.core.bootloader import LimineInstaller
from tests.conftest import make_result


def _inst(tmp_path, **kw):
    (tmp_path / "etc").mkdir(exist_ok=True)
    return LimineInstaller(mount_point=str(tmp_path), root_uuid="ROOT-FS", **kw)


def test_writes_cmdline_and_fallback(tmp_path):
    inst = _inst(tmp_path, luks_uuid="ROOTLUKS", uefi=True)
    inst._write_kernel_cmdline()
    ek = tmp_path / "etc" / "kernel"
    cmd = (ek / "cmdline").read_text()
    fb = (ek / "cmdline-fallback").read_text()
    assert "rd.luks.name=ROOTLUKS=luks-ROOTLUKS" in cmd
    assert "quiet" in cmd and "splash" in cmd
    # Fallback keeps the LUKS unlock but strips the silent splash.
    assert "rd.luks.name=ROOTLUKS=luks-ROOTLUKS" in fb
    assert "quiet" not in fb.split() and "splash" not in fb.split()


def test_strip_quiet_splash_only_drops_those_tokens(tmp_path):
    inst = _inst(tmp_path, uefi=True)
    out = inst._strip_quiet_splash("rw quiet splash loglevel=3")
    assert out == "rw loglevel=3"


def test_seed_esp_config_is_idempotent(tmp_path):
    inst = _inst(tmp_path, uefi=True)
    inst._seed_esp_config()
    seed = tmp_path / "boot" / "efi" / "limine.conf"
    assert seed.read_text() == "timeout: 3\n"
    seed.write_text("timeout: 3\n# real menu\n")
    inst._seed_esp_config()   # must not clobber an existing config
    assert "# real menu" in seed.read_text()


def test_verify_uki_requires_default_and_fallback(tmp_path):
    inst = _inst(tmp_path, uefi=True)
    uki = tmp_path / "boot" / "efi" / "EFI" / "Linux"
    uki.mkdir(parents=True)
    (uki / "shedos-linux-zen.efi").write_bytes(b"u")
    assert inst._verify_uki_on_esp() is False   # fallback missing → recovery dead
    (uki / "shedos-linux-zen-fallback.efi").write_bytes(b"f")
    assert inst._verify_uki_on_esp() is True


def test_write_containers_lists_root_then_swap(tmp_path):
    inst = _inst(tmp_path, uefi=True, luks_uuid="ROOT-LUKS",
                 swap_luks_uuid="SWAP-LUKS", swap_luks_mapper="swap")
    inst._write_containers()
    lines = (tmp_path / "etc" / "shedos" / "secureboot" / "containers"
             ).read_text().splitlines()
    assert lines == ["/dev/disk/by-uuid/ROOT-LUKS", "/dev/disk/by-uuid/SWAP-LUKS"]


def test_write_containers_noop_without_luks(tmp_path):
    inst = _inst(tmp_path, uefi=True)
    inst._write_containers()
    assert not (tmp_path / "etc" / "shedos" / "secureboot" / "containers").exists()


def test_place_ukis_renders_only_after_verify(tmp_path, mock_run_command, monkeypatch):
    inst = _inst(tmp_path, uefi=True)
    rendered = []
    monkeypatch.setattr(inst, "_verify_uki_on_esp", lambda: True)
    monkeypatch.setattr(inst, "_create_config",
                        lambda d: rendered.append(d) or True)
    monkeypatch.setattr(inst, "_register_nvram_entry", lambda: None)
    monkeypatch.setattr(inst, "_write_containers", lambda: None)
    assert inst._place_ukis_and_render() is True
    seq = [" ".join(c.args[0]) for c in mock_run_command.call_args_list]
    assert any("build-uki.sh" in c for c in seq)        # placer ran
    assert len(rendered) == 2                            # both ESP config dirs
    assert (tmp_path / "boot" / "efi" / "limine.conf").exists()   # seeded first


def test_place_ukis_aborts_when_uki_unverified(tmp_path, mock_run_command, monkeypatch):
    inst = _inst(tmp_path, uefi=True)
    rendered = []
    monkeypatch.setattr(inst, "_verify_uki_on_esp", lambda: False)
    monkeypatch.setattr(inst, "_create_config",
                        lambda d: rendered.append(d) or True)
    assert inst._place_ukis_and_render() is False
    seq = [" ".join(c.args[0]) for c in mock_run_command.call_args_list]
    assert any("build-uki.sh" in c for c in seq)   # placer still ran
    assert rendered == []   # but the menu never rendered without verified UKIs


def test_register_nvram_adds_recovery_entry(tmp_path, monkeypatch):
    inst = _inst(tmp_path, uefi=True)
    created = []

    def fake_run(cmd, **kw):
        if cmd[:2] == ["findmnt", "-no"]:
            return make_result(stdout="/dev/sda1")
        if cmd[:3] == ["lsblk", "-rno", "PKNAME"]:
            return make_result(stdout="sda")
        if cmd[:3] == ["lsblk", "-rno", "PARTN"]:
            return make_result(stdout="1")
        if cmd == ["efibootmgr"]:
            return make_result(stdout="")
        if "--create" in cmd:
            created.append(cmd[cmd.index("--label") + 1])
        return make_result()

    monkeypatch.setattr("shedos_installer.core.bootloader.run_command", fake_run)
    inst._register_nvram_entry()
    assert "ShedOS" in created
    assert "ShedOS Recovery" in created
